"""Power Four current-team cohort, prior-day stat replay. Research only."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from sqlalchemy import select, text
from config.settings import get_settings
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, PlayerExternalId, Team
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_model import STATS, RECIPE, estimate, finite
from src.services.roster_stat_prospective import publish

CONFERENCES = {'acc': 'ACC', 'big10': 'Big Ten', 'big12': 'Big 12', 'sec': 'SEC'}


def membership(payload):
    teams = {}
    for conference in payload.get('children', []):
        name = CONFERENCES.get(conference.get('abbreviation'))
        if not name: continue
        for entry in conference.get('standings', {}).get('entries', []):
            team = entry['team']
            if str(team['id']) in teams: raise ValueError('Duplicate conference team')
            teams[str(team['id'])] = {'conference': name, 'name': team['displayName']}
    if Counter(t['conference'] for t in teams.values()) != Counter({'ACC':17,'Big Ten':18,'Big 12':16,'SEC':16}):
        raise ValueError('Unexpected 2026 Power Four membership; review source')
    return teams


def replay(history, stats, season):
    history = sorted(history, key=lambda r:(r['time'], r['game_id']))
    if len({r['game_id'] for r in history}) != len(history): raise ValueError('Duplicate player-game')
    results = []
    for target in history:
        if target['season'] != season: continue
        # Same-day games cannot leak across a retrospective prediction cutoff.
        past = [r for r in history if r['time'].date() < target['time'].date()]
        for stat in stats:
            actual = target['values'].get(stat)
            if not finite(actual): continue
            prediction = estimate(past, stat)
            row = {'stat':stat, 'game_id':target['game_id'], 'week':target['week'],
                   'status':prediction['status'], 'training_games':prediction['games']}
            if prediction['status'] == 'ready':
                row.update(actual=actual, baseline_error=abs(prediction['baseline']-actual),
                    candidate_error=abs(prediction['candidate']-actual), method=prediction['method'])
            results.append(row)
    return results


async def run(db, conference_snapshot):
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    now = datetime.now(timezone.utc)
    season = conference_snapshot['season']
    if season != now.year: raise ValueError('Conference snapshot season mismatch')
    member = conference_snapshot['teams']
    teams = (await db.scalars(select(Team).where(Team.sport=='ncaaf',Team.espn_id.in_(member)))).all()
    by_id = {t.id:t for t in teams}
    roster = conference_snapshot['rosters']
    team_by_external = {t.espn_id:t for t in teams}
    links = (await db.execute(select(PlayerExternalId.external_id,Player).join(Player,Player.id==PlayerExternalId.player_id)
        .where(Player.sport=='ncaaf',PlayerExternalId.source=='espn_ncaaf',PlayerExternalId.external_id.in_(roster)))).all()
    players, player_team, positions = [], {}, {}
    for external, player in links:
        info = roster[external]
        if info['position'] not in STATS or info['team_id'] not in team_by_external: continue
        players.append(player)
        player_team[player.id] = team_by_external[info['team_id']].id
        positions[player.id] = info['position']
    by_player = {p.id:p for p in players}
    games = (await db.scalars(select(Game).where(Game.sport=='ncaaf',Game.season.in_([season-1,season])))).all()
    game_by_id = {g.id:g for g in games}
    # Unknown kickoff is counted as a coverage gap, never used for replay.
    finals = {g.id:g for g in games if g.status=='final' and g.game_time and g.game_time < now and g.game_type!='PRE'}
    rows = (await db.scalars(select(PlayerGameStat).where(PlayerGameStat.player_id.in_(by_player),
        PlayerGameStat.game_id.in_(finals),no_pending_correction()))).all()
    history = defaultdict(dict)
    mismatched = 0
    for row in rows:
        game, player = finals[row.game_id], by_player[row.player_id]
        # Do not attribute an old team's performance to the current team or
        # silently transfer a historical role across colleges.
        if player_team[player.id] not in (game.home_team_id,game.away_team_id):
            mismatched += 1
            continue
        item = history[player.id].setdefault(game.id, {'game_id':str(game.id),'time':game.game_time,
            'season':game.season,'week':game.week,'values':{}})
        item['values'][row.stat_type] = row.value
    evaluations, cards = [], []
    for player in players:
        records = list(history[player.id].values())
        if not any(r['season']==season for r in records): continue
        conf = member[by_id[player_team[player.id]].espn_id]['conference']
        evaluation = replay(records, STATS[positions[player.id]], season)
        evaluations.extend({**r,'player_id':str(player.id),'conference':conf} for r in evaluation)
        upcoming = sorted((g for g in games if g.status=='scheduled' and g.game_time and
            now < g.game_time <= now+timedelta(days=10) and player_team[player.id] in (g.home_team_id,g.away_team_id)),key=lambda g:g.game_time)
        forecasts = [{'stat':s,**estimate(sorted(records,key=lambda r:r['time']),s)} for s in STATS[positions[player.id]]]
        cards.append({'player_id':str(player.id),'name':player.full_name,'position':positions[player.id],
            'team':by_id[player_team[player.id]].name,'conference':conf,
            'game_id':str(upcoming[0].id) if upcoming else None,
            'game_time':upcoming[0].game_time.isoformat() if upcoming else None,'stats':forecasts})
    groups = defaultdict(list)
    for row in evaluations:
        if row['status']=='ready': groups[(row['conference'],row['stat'])].append(row)
    metrics = [{'conference':c,'stat':s,'samples':len(rs),'players':len({r['player_id'] for r in rs}),
        'games':len({r['game_id'] for r in rs}), 'baseline_mae':fmean(r['baseline_error'] for r in rs),
        'candidate_mae':fmean(r['candidate_error'] for r in rs),
        'usage_blend_samples':sum(r['method']=='opportunity_blend' for r in rs)} for (c,s),rs in sorted(groups.items())]
    current = [g for g in games if g.season==season and (g.home_team_id in by_id or g.away_team_id in by_id)]
    completed = [g for g in current if g.id in finals]
    covered = {r['game_id'] for rs in history.values() for r in rs.values() if r['season']==season}
    report = {'status':'experimental','season':season,'generated_at':now.isoformat(),'recipe':RECIPE,
        'membership_source':conference_snapshot['source'],'membership_fetched_at':conference_snapshot['fetched_at'],
        'teams':len(member),'mapped_teams':len(teams),'players':cards,'metrics':metrics,
        'coverage':{'completed_power4_games':len(completed),'games_with_cohort_stats':len(covered),
            'completed_by_week':dict(Counter(str(g.week) for g in completed)),
            'unknown_kickoffs':sum(g.game_time is None for g in current),
            'evaluated_player_stat_results':sum(r['status']=='ready' for r in evaluations),
            'insufficient_history_results':sum(r['status']!='ready' for r in evaluations),
            'excluded_other_team_stat_rows':mismatched},
        'serving_enabled':False,'evaluation_type':'retrospective_prior_day_corrected_history',
        'notes':['Current Power Four team cohort, not historical conference membership. Notre Dame excluded.',
            'Completed 2026 results tested only against prior-day history; minimum eight recorded games.',
            'Transfers and unknown prior team attribution excluded. Missing stats are not zero.',
            'ESPN receiving targets are generally unavailable: receptions/receiving-yard candidates may equal baseline.',
            'Current corrected data and current roster selection are not point-in-time prospective evidence.',
            'No verified gameday availability or opponent adjustment; conditional-on-playing research only.']}
    root = Path(get_settings().raw_archive_dir)/'college-player-lab'
    publish(root/'sources'/f"{now.strftime('%Y%m%dT%H%M%S.%f')}.json",conference_snapshot)
    publish(root/f"{now.strftime('%Y%m%dT%H%M%S.%f')}.json",report)
    return {k:v for k,v in report.items() if k!='players'}


def latest():
    files = sorted((Path(get_settings().raw_archive_dir)/'college-player-lab').glob('*.json'))
    return json.loads(files[-1].read_text()) if files else {'status':'not_started','players':[],'metrics':[]}
