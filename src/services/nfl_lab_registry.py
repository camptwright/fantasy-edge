"""Version-bound experimental artifact registry, paired captures and gate review."""
import hashlib
import json
from datetime import datetime,timedelta
from pathlib import Path
from uuid import UUID
from sqlalchemy import select,text
from config.settings import get_settings
from src.models.base import utcnow
from src.models.facts import Game,TeamMarketLine
from src.models.governance import ModelArtifact,ModelPrediction,ModelReviewEvidence
from src.services.quote_eligibility import availability,exclusion
from src.services.roster_stat_prospective import publish
from src.services.prospective_review import scorecard,nfl_lab_protocol
from src.services.sharp_pricing import brand,SHARP
from src.utils.odds_math import remove_vig_two_way


def artifact_version(artifact):
    code=(Path(__file__).parent/'nfl_predictor_lab.py').read_bytes()
    # Changing the prospective comparator starts a new cohort, never rewrites
    # old captures or manufactures missing historical baseline probabilities.
    protocol_version=b'retained-serving-baseline-and-market-fixed-sample-v4'
    return hashlib.sha256(json.dumps(artifact,sort_keys=True,allow_nan=False).encode()+code+protocol_version).hexdigest()


async def persist_forecast(db, record, version):
    """Import original frozen evidence, never reconstruct missing pregame inputs."""
    if record['version'] != version or record.get('usage') != 'research_only' or record.get('actionable') is not False:
        raise ValueError('Invalid lab forecast provenance')
    at=datetime.fromisoformat(record['captured_at'])
    kickoff=datetime.fromisoformat(record['kickoff'])
    if at.tzinfo is None or kickoff.tzinfo is None or at>=kickoff:
        raise ValueError('Lab forecast was not captured before kickoff')
    existing=await db.scalar(select(ModelPrediction).where(ModelPrediction.artifact_version==version,
        ModelPrediction.game_id==UUID(record['game_id']),ModelPrediction.market=='moneyline',ModelPrediction.side=='home'))
    if existing is None:
        existing=ModelPrediction(artifact_version=version,game_id=UUID(record['game_id']),market='moneyline',side='home',
            probability=record['probability'],generated_at=at,evidence=record)
        db.add(existing)
    elif existing.evidence is None:
        if existing.probability!=record['probability'] or existing.generated_at!=at:
            raise ValueError('Archived forecast disagrees with registered prediction')
        existing.evidence=record
    elif existing.evidence!=record:
        raise ValueError('Frozen forecast evidence cannot be overwritten')
    await db.flush()
    return existing


async def market_reference(db,game,now):
    q=TeamMarketLine;keys=(q.source,q.side)
    rows=(await db.scalars(select(q).where(q.game_id==game.id,q.market=='moneyline')
        .distinct(*keys).order_by(*keys,q.observed_at.desc(),q.id.desc()))).all()
    seen=await availability(db,'team',[r.id for r in rows]);pairs={}
    for r in rows:
        if brand(r.source) not in SHARP or exclusion(game,r,seen.get(r.id),now) is not None:continue
        if not isinstance(r.price_american,int) or abs(r.price_american)<100:continue
        pairs.setdefault(r.source,{})[r.side]=r
    valid=[]
    for source,pair in pairs.items():
        if set(pair)!={'home','away'}:continue
        h,a=pair['home'],pair['away']
        if abs(h.observed_at-a.observed_at)>timedelta(seconds=60):continue
        valid.append((min(h.observed_at,a.observed_at),source,h,a))
    if not valid:return None
    _,source,h,a=max(valid,key=lambda r:(r[0],r[1]))
    return {'probability':remove_vig_two_way(h.price_american,a.price_american)[0],
        'source':source,'quote_ids':[str(h.id),str(a.id)],'captured_at':now.isoformat(),
        'scope':'pregame_two_way_moneyline_conditional_on_non_tie'}


async def retained_baseline(db,game):
    from src.models.ratings import TeamRating
    from src.services.elo import moneyline_probability
    ratings=(await db.scalars(select(TeamRating).where(TeamRating.team_id.in_(
        [g for g in (game.home_team_id,game.away_team_id) if g is not None])))).all()
    by_team={r.team_id:r for r in ratings}
    if game.home_team_id not in by_team or game.away_team_id not in by_team:return None
    return moneyline_probability(by_team[game.home_team_id].rating,by_team[game.away_team_id].rating)


async def execute(db):
    from src.api.routers.nfl_predictor import ARTIFACT,nfl_predictor
    await db.execute(text('SELECT pg_advisory_xact_lock(78241904)'))
    artifact=json.loads(ARTIFACT.read_text());version=artifact_version(artifact)
    root=Path(get_settings().raw_archive_dir)/'nfl-lab-prospective'
    target=Path(get_settings().raw_archive_dir).parent/'models'/'nfl-lab'/f'{version}.json'
    publish(target,artifact)
    saved=await db.scalar(select(ModelArtifact).where(ModelArtifact.version==version))
    if saved is None:
        saved=ModelArtifact(version=version,kind='independent',trained_at=datetime.fromisoformat(artifact['trained_at']),
            seasons_used=list(range(artifact['first_season'],artifact['last_season']+1)),
            artifact_path=str(target),artifact_payload=artifact,brier=artifact['evaluation']['candidate']['brier'],
            log_loss=artifact['evaluation']['candidate']['log_loss'],passed_gate=False)
        db.add(saved)
    elif saved.artifact_payload is None:
        saved.artifact_payload=artifact
    elif saved.artifact_payload!=artifact:
        raise ValueError('Registered artifact payload mismatch')
    await db.flush()
    # One-way migration of historical frozen files. Database evidence wins on
    # subsequent runs; missing archives must never erase a prospective cohort.
    for path in (root/'forecasts').glob('*.json'):
        record=json.loads(path.read_text())
        if record['version']==version:
            await persist_forecast(db,record,version)
    lab=await nfl_predictor(db);now=utcnow();captured=0
    # This helper always loads the same checked-in artifact; refuse a concurrent
    # file edit between registering its hash and generating predictions.
    if artifact_version(json.loads(ARTIFACT.read_text()))!=version:
        raise ValueError('Lab artifact changed during capture')
    for row in lab['games']:
        if row['status']!='experimental' or not row.get('venue_verified'):continue
        game=await db.get(Game,UUID(row['id']))
        if not game or game.status!='scheduled' or not game.game_time or not now+timedelta(minutes=5)<game.game_time<=now+timedelta(hours=72):continue
        key=hashlib.sha256(f'{version}:{game.id}:moneyline:home'.encode()).hexdigest()
        path=root/'forecasts'/f'{key}.json'
        registered=await db.scalar(select(ModelPrediction).where(ModelPrediction.artifact_version==version,
            ModelPrediction.game_id==game.id,ModelPrediction.market=='moneyline',ModelPrediction.side=='home'))
        if registered is not None and registered.evidence is not None:
            continue
        if path.exists():record=json.loads(path.read_text())
        else:
            market=await market_reference(db,game,now)
            from src.services.nfl_epa_feed import latest_features
            record={'id':key,'version':version,'game_id':str(game.id),'market_key':'moneyline_home',
                'captured_at':now.isoformat(),'kickoff':game.game_time.isoformat(),
                'probability':row['home_probability'],'baseline':row['baseline_home_probability'],
                'retained_serving_baseline':await retained_baseline(db,game),
                'market_probability':market['probability'] if market else None,'market_evidence':market,
                'epa_features':latest_features(row['home'],row['away'],now),
                'blend_25_probability':.75*row['home_probability']+.25*market['probability'] if market else None,
                'protocol_verified':True,'usage':'research_only','actionable':False}
            captured+=publish(path,record)
            record=json.loads(path.read_text())
        await persist_forecast(db,record,version)
    records=[]
    predictions=(await db.scalars(select(ModelPrediction).where(ModelPrediction.artifact_version==version,
        ModelPrediction.market=='moneyline',ModelPrediction.side=='home'))).all()
    for prediction in predictions:
        r=prediction.evidence
        if r is None:continue
        game=await db.get(Game,UUID(r['game_id']));at=datetime.fromisoformat(r['captured_at'])
        valid=game is not None and game.game_time is not None and at<game.game_time
        complete=valid and game.status=='final' and game.home_score is not None and game.away_score is not None
        tied=complete and game.home_score==game.away_score
        records.append({**r,'captured_at':at,'baseline':r.get('retained_serving_baseline'),
            'evaluation_kickoff':game.game_time.isoformat() if game and game.game_time else None,
            'protocol_verified':bool(valid and r.get('protocol_verified') is True
                and r.get('retained_serving_baseline') is not None and r.get('market_probability') is not None),
            'outcome':int(game.home_score>game.away_score) if complete and not tied else None,
            'status':'push' if tied else 'graded' if complete else 'awaiting_final'})
    review=scorecard(records,now,policy=nfl_lab_protocol())
    blend_records=[{**r,'baseline':r['probability'],'probability':r['blend_25_probability']}
        for r in records if r.get('blend_25_probability') is not None]
    report={'version':version,'artifact_path':str(target),'captured':captured,
        'evidence_store':'postgresql','reviewed_at':now.isoformat(),
        'baseline_identity':'retained_serving_elo',
        'comparison_eligibility':'pregame_capture_with_retained_baseline_and_sharp_market',
        'legacy_forecasts_without_serving_baseline':sum(p.evidence is not None and p.evidence.get('retained_serving_baseline') is None for p in predictions),
        'predictions_missing_frozen_evidence':sum(p.evidence is None for p in predictions),
        'forecast_count':len(records),'promotion_check':review,'serving_promoted':False,
        'market_blend_25_review':scorecard(blend_records,now,policy=nfl_lab_protocol()),
        'market_blend_25_retained_baseline_review':scorecard(
            [{**r,'probability':r['blend_25_probability']} for r in records if r.get('blend_25_probability') is not None],
            now,policy=nfl_lab_protocol()),
        'blend_recipe':{'lab_weight':.75,'market_weight':.25,'selection':'fixed_before_outcomes','usage':'research_only'},
        'historical_metrics_scope':'expanding_season_recipe_not_final_artifact_prospective_performance'}
    if report['predictions_missing_frozen_evidence']:
        for key in ('promotion_check','market_blend_25_review','market_blend_25_retained_baseline_review'):
            report[key]['review']['blockers'].append('registered_predictions_missing_frozen_evidence')
            report[key]['review']['promotion_eligible']=False
    # Passing a review is evidence, not permission to replace serving behavior.
    db.add(ModelReviewEvidence(artifact_version=version,report=report))
    await db.commit()
    # Archive is a secondary copy. A mount failure cannot roll back the durable
    # review or cause an already captured prediction to be recaptured later.
    publish(root/'reviews'/f'{now.strftime("%Y%m%dT%H%M%S%f")}-{version}.json',report)
    return report
