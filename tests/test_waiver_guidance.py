"""Waiver guidance values lineup points, not raw bench points."""

from src.services.waiver_guidance import guidance


def p(pid, pos, weeks, rostered, weekly=None):
    return {"player_id": pid, "name": pid, "position": pos, "roster_ids": [1] if rostered else [], "weekly_points": weekly,
            "engine": {"status": "research", "ros_points": sum(weeks.values()),
                       "weeks": [{"week": w, "points": v, "environment": "market_line"} for w, v in weeks.items()]}
            if weeks else {"status": "position_not_modeled"}}


def run(players, slots=("QB", "WR", "FLEX", "K", "BN", "BN")):
    mine = [x["player_id"] for x in players if x["roster_ids"]]
    return guidance(players, mine, set(mine), list(slots))


def test_unknown_roster_position_is_missing_coverage_not_an_omitted_specialist():
    players=[p('starter','WR',{6:10,7:10},True),p('unknown',None,{},True),
             p('add','WR',{6:20,7:20},False)]
    result=run(players,['WR','BN'])
    assert result['status']=='incomplete_coverage'
    assert not result['rows']
    assert result['coverage_blockers'][0]['missing_player_ids']==['unknown']


def test_a_backup_qb_with_big_raw_points_has_no_lineup_value():
    players = [p("qb", "QB", {6: 20, 7: 20}, True), p("wr", "WR", {6: 10, 7: 10}, True), p("rb", "RB", {6: 6, 7: 6}, True),
               p("bench", "WR", {6: 2, 7: 2}, True), p("fa_qb", "QB", {6: 18, 7: 18}, False),
               p("fa_rb", "RB", {6: 9, 7: 9}, False)]
    rows = {r["add_id"]: r for r in run(players)["rows"]}
    assert "fa_qb" not in rows
    assert rows["fa_rb"]["drop_id"] == "bench" and rows["fa_rb"]["lineup_gain"] == 6.0  # 9 replaces 6 in FLEX, twice


def test_byes_count_as_zero_and_the_required_kicker_is_never_dropped():
    players = [p("qb", "QB", {6: 20, 7: 20}, True), p("wr", "WR", {6: 10}, True),  # wr on bye week 7
               p("rb", "RB", {6: 6, 7: 6}, True), p("k", "K", {}, True, weekly=7.0),
               p("fa_wr", "WR", {6: 8, 7: 8}, False), p("fa_k", "K", {}, False, weekly=9.0)]
    players[1]['engine']['coverage'] = [{'week': 7, 'status': 'verified_bye'}]
    rows = {r["add_id"]: r for r in run(players)["rows"]}
    assert rows["fa_wr"]["drop_id"] != "k"
    # Dropping rb gains +2 in each week; dropping the wr (bye in week 7) loses 2 in week 6
    # but gains 8 in week 7 (+6 total), so the bye-week receiver is the better drop.
    assert rows["fa_wr"]["drop_id"] == "wr" and rows["fa_wr"]["lineup_gain"] == 6.0
    assert (rows["fa_wr"]["week_gain"], rows["fa_wr"]["weeks_improved"]) == (-2.0, 1)
    assert rows["fa_k"] == {"add_id": "fa_k", "drop_id": "k", "lineup_gain": None, "week": None, "week_gain": 2.0, "stream": True}


def test_no_engine_weeks_is_an_explicit_status():
    assert run([p("qb", "QB", {}, True)])["status"] == "insufficient_engine_research"


def test_missing_projection_is_not_an_artificially_expendable_player():
    players = [p('qb', 'QB', {6: 20, 7: 20}, True), p('wr', 'WR', {6: 10}, True),
               p('bench', 'WR', {6: 2, 7: 2}, True), p('free', 'WR', {6: 12, 7: 12}, False)]
    result = run(players, slots=('QB', 'WR', 'BN'))
    assert result['status'] == 'incomplete_coverage' and result['rows'] == []
    assert result['coverage_blockers'] == [{'week': 7, 'missing_player_ids': ['wr']}]


def test_four_week_horizon_alternative_drops_and_negligible_stream_filter():
    weeks = {w: 20 for w in range(6, 10)}
    players = [p('qb', 'QB', weeks, True), p('wr', 'WR', {w: 10 for w in weeks}, True),
               p('bench', 'WR', {w: 4 for w in weeks}, True), p('free', 'WR', {w: 12 for w in weeks}, False),
               p('k', 'K', {}, True, 8), p('fk', 'K', {}, False, 8.1)]
    mine = [x['player_id'] for x in players if x['roster_ids']]
    result = guidance(players, mine, set(mine), ['QB', 'WR', 'K', 'BN'], horizon_weeks=4)
    assert result['weeks'] == [6, 7, 8, 9]
    assert len(result['rows']) == 1 and result['rows'][0]['lineup_gain'] == 8
    assert len(result['rows'][0]['alternative_drops']) == 2  # the sole QB cannot be dropped
    assert len(result['rows'][0]['weekly']) == 4


def test_incomplete_slots_never_become_a_full_lineup_total():
    from src.services.waiver_guidance import lineup_total
    assert lineup_total([p('qb', 'QB', {6: 20}, True)], ['QB', 'WR'], 6) is None


def test_stale_specialist_projection_never_creates_a_streaming_move():
    players = [p('qb', 'QB', {6: 20, 7: 20}, True), p('k', 'K', {}, True, 8), p('fk', 'K', {}, False, 12)]
    players[-1]['weekly_evidence'] = {'week': 6, 'status': 'unavailable_stale_or_started'}
    assert run(players, slots=('QB', 'K', 'BN'))['rows'] == []
