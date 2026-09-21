"""Prove completed-week data eligibility and use without retraining or promotion."""
from collections import Counter
from datetime import datetime,timezone
import statistics
from sqlalchemy import select, or_
from src.models.facts import Game,PlayerGameStat
from src.models.identity import Player
from src.services.result_eligibility import no_pending_correction
from src.services.projections import project_stats
from src.services.stat_identity import canonical_results


async def audit(db,season=2026,week=1):
    games=list((await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==season,
        Game.week==week,Game.game_type=='REG'))).all())
    ids={g.id for g in games}
    rows=(await db.execute(select(PlayerGameStat.player_id,PlayerGameStat.game_id,PlayerGameStat.stat_type,
        PlayerGameStat.value).where(PlayerGameStat.game_id.in_(ids)))).all()
    eligible=(await db.execute(select(PlayerGameStat.player_id,PlayerGameStat.game_id,PlayerGameStat.stat_type,
        PlayerGameStat.value).join(Game,Game.id==PlayerGameStat.game_id).where(Game.id.in_(ids),
            Game.status=='final',Game.game_time<datetime.now(timezone.utc),no_pending_correction()))).all()
    passers={r.player_id for r in eligible if r.stat_type=='passing_yards'}
    quarterbacks=list((await db.scalars(select(Player.id).where(Player.id.in_(passers),
        Player.position=='QB').order_by(Player.id))).all())
    keys={(p,'passing_yards') for p in quarterbacks}
    served=await project_stats(db,keys)
    histories=(await db.execute(select(PlayerGameStat.player_id,PlayerGameStat.game_id,PlayerGameStat.stat_type,
        PlayerGameStat.value).join(Game,Game.id==PlayerGameStat.game_id).where(PlayerGameStat.player_id.in_(quarterbacks),
        PlayerGameStat.stat_type=='passing_yards',Game.status=='final',or_(Game.game_type.is_(None),Game.game_type!='PRE'),
        Game.game_time<datetime.now(timezone.utc),no_pending_correction()))).all()
    facts=canonical_results(histories)
    names={p.id:p.full_name for p in (await db.scalars(select(Player).where(Player.id.in_(quarterbacks)))).all()}
    proof=[]
    for pid in quarterbacks:
        values=[v for (p,g,s),v in facts.items() if p==pid]
        prior=[v for (p,g,s),v in facts.items() if p==pid and g not in ids]
        current=[v for (p,g,s),v in facts.items() if p==pid and g in ids]
        result=served.get((pid,'passing_yards'))
        proof.append({'player':names[pid],'week_values':current,'history_games':len(values),
            'served_mean':result[0] if result else None,'without_week_mean':statistics.fmean(prior) if prior else None,
            'matches_inclusive_history':bool(result and current and abs(result[0]-statistics.fmean(values))<1e-9)})
    return {'season':season,'week':week,'generated_at':datetime.now(timezone.utc).isoformat(),
        'game_statuses':dict(Counter(g.status for g in games)),'games_with_stats':len({r.game_id for r in rows}),
        'players':len({r.player_id for r in rows}),'stat_rows':len(rows),'eligible_rows':len(eligible),
        'quarterback_usage_proof':proof,'note':'All-history serving projections update from eligible finals; this does not prove model accuracy or retrain frozen experimental coefficients.'}
