"""P(plays | designation, practice, position) from the fitted nflverse table."""

from datetime import datetime, timezone

from src.services import availability_rates as ar

ARTIFACT = {"shrink": 40, "tables": {
    "status": {"Questionable": {"played": 680, "n": 1000}, "Doubtful": {"played": 2, "n": 200}},
    "status_practice": {"Questionable|full": {"played": 180, "n": 200}, "Questionable|dnp": {"played": 100, "n": 200}},
    "status_practice_position": {"Questionable|full|WR": {"played": 95, "n": 100}}}}

CSV = """season,season_type,game_type,team,week,gsis_id,position,full_name,first_name,last_name,report_primary_injury,report_secondary_injury,report_status,practice_primary_injury,practice_secondary_injury,practice_status
2026,REG,REG,DET,5,00-1,WR,A,A,A,Ankle,,Questionable,Ankle,,Did Not Participate In Practice
2026,REG,REG,DET,6,00-1,WR,A,A,A,,,,Ankle,,Limited Participation in Practice
2026,REG,REG,GB,6,00-2,RB,B,B,B,,,,Knee,,
"""


def test_probability_shrinks_each_level_toward_the_one_above():
    full = ar.probability("Questionable", "full", "WR", ARTIFACT)
    level = (180 + 40 * 0.68) / 240
    assert full["probability"] == round((95 + 40 * level) / 140, 3) and full["basis"] == "Questionable, full practice, WR"
    # No position cell: the practice level; no practice: the status level; never for healthy players.
    assert ar.probability("Q", "dnp", "TE", ARTIFACT)["probability"] == round((100 + 40 * 0.68) / 240, 3)
    assert ar.probability("questionable", None, "RB", ARTIFACT) == {"probability": 0.68, "n": 1000, "basis": "Questionable"}
    assert ar.probability("Doubtful", None, "QB", ARTIFACT)["probability"] == 0.01
    assert ar.probability("Out", None, "WR", ARTIFACT) is None and ar.probability(None, None, "WR", ARTIFACT) is None
    assert ar.probability("Questionable", None, "K", ARTIFACT) is None


def test_parse_keeps_each_players_latest_week():
    rows = ar.parse(CSV)
    assert rows["00-1"] == {"season": 2026, "week": 6, "team": "DET", "report_status": None, "practice": "limited", "injury": "Ankle", "reported_at": None}
    assert rows["00-2"]["practice"] is None


async def test_refresh_stores_the_report_and_is_throttled(db):
    now = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)

    async def fetcher(season):
        assert season == 2026
        return CSV

    assert (await ar.refresh(db, now=now, fetcher=fetcher)) == {"status": "refreshed", "players": 2}
    assert (await ar.refresh(db, now=now, fetcher=fetcher))["status"] == "fresh"
    assert (await ar.latest(db, 2026))["players"]["00-1"]["week"] == 6


def test_shipped_artifact_matches_the_research_evidence():
    artifact = ar.load()
    assert artifact["recipe"] == "availability_rates_v1"
    models = artifact["evidence"]["models"]
    assert models[artifact["chosen"]]["brier"] < models["serving_rule"]["brier"]
    q_full = ar.probability("Questionable", "full", "WR")["probability"]
    q_dnp = ar.probability("Questionable", "dnp", "WR")["probability"]
    assert 0.8 < q_full <= 1 and q_dnp < q_full and ar.probability("Doubtful", "dnp", "RB")["probability"] < 0.1


def test_practice_requires_same_team_week_season_and_both_fresh_dates():
    now = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    row = {'season': 2026, 'week': 6, 'team': 'LA', 'reported_at': '2026-10-16T17:00:00Z', 'practice': 'full'}
    report = {'season': 2026, 'fetched_at': '2026-10-18T10:00:00Z'}
    def status(r=row, p=report, **kw):
        return ar.practice_evidence(r, p, season=2026, week=6, team=kw.get('team', 'LAR'), now=now)['status']
    assert status() == 'matched_fresh_report'
    assert status(team='DET') == 'team_mismatch'
    assert status({**row, 'week': 5}) == 'season_or_week_mismatch'
    assert status({**row, 'season': 2025}) == 'season_or_week_mismatch'
    assert status({**row, 'reported_at': None}) == 'undated_report'
    assert status({**row, 'reported_at': '2026-10-20'}) == 'stale_or_future_report'
    assert status(p={**report, 'fetched_at': '2026-10-17T10:00:00Z'}) == 'stale_or_future_report'


def test_parse_uses_latest_report_timestamp_within_a_week():
    header = 'season,game_type,team,week,gsis_id,practice_status,date_modified\n'
    rows = ar.parse(header + '2026,REG,DET,6,a,Full Participation in Practice,2026-10-16\n'
                    + '2026,REG,DET,6,a,Did Not Participate In Practice,2026-10-15\n')
    assert rows['a']['practice'] == 'full'
