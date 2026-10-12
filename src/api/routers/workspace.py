"""V2 presentation reads. Never build forecasts or call a provider on a GET."""
from datetime import datetime
from math import isfinite
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.client import get_db
from src.models.sleeper import SleeperLeague
from src.services.workspace_checkpoints import read
from src.services.workspace_player_evidence import availability_evidence, uncertainty_evidence

router = APIRouter(prefix="/api/v2/fantasy", tags=["workspace"])


class TradeAdjustment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    add: list[str] = Field(default_factory=list, max_length=6)
    drop: list[str] = Field(default_factory=list, max_length=6)


class TradeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: datetime
    side_a: list[str] = Field(min_length=1, max_length=6)
    side_b: list[str] = Field(min_length=1, max_length=6)
    a: TradeAdjustment = Field(default_factory=TradeAdjustment)
    b: TradeAdjustment = Field(default_factory=TradeAdjustment)


class TradeSide(BaseModel):
    team: str
    conditional_lineup_gain: float | None = None
    roster_size_before: int | None = None
    roster_size_after: int | None = None
    missing_players: list[str] = Field(default_factory=list)
    availability_review_players: list[str] = Field(default_factory=list)


class TradeWeek(BaseModel):
    week: int
    gain: float


class TradeOutlookSide(BaseModel):
    team: str | None = None
    status: str
    weeks: int | None = None
    lineup_gain: float | None = None
    by_position: dict[str, float] = Field(default_factory=dict)
    weekly: list[TradeWeek] = Field(default_factory=list)
    unmodeled_players: list[str] = Field(default_factory=list)


class TradeOutlook(BaseModel):
    status: str
    side_a: TradeOutlookSide | None = None
    side_b: TradeOutlookSide | None = None
    player_ros_points: dict[str, float | None] = Field(default_factory=dict)
    note: str = ('Engine research: each remaining week your best offensive lineup is re-solved before and after the trade '
                 '(byes and missing projections count as zero), summed by the starting player\'s position. '
                 'Not validated, not market value, and not acceptance advice.')


class TradeResult(BaseModel):
    status: str
    actionable: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    generated_at: datetime
    expires_at: datetime
    side_a: TradeSide | None = None
    side_b: TradeSide | None = None
    outlook: TradeOutlook | None = None
    note: str = 'Conditional offensive lineup points per game, not ROS gains, market fairness or acceptance advice. No byes, injury recovery or transaction processing modeled.'


def trade_context(data: dict, request: TradeRequest) -> TradeResult:
    from src.services.fantasy_values import compare
    evidence = data['read_model']
    result = TradeResult(status='withheld', generated_at=evidence['generated_at'], expires_at=evidence['expires_at'])
    if result.generated_at != request.generated_at:
        result.blockers = ['snapshot_changed_refresh_before_comparing']
        return result
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    catalog = {p.player_id: p for p in comparison_context(data, by_id)}
    ids = request.side_a + request.side_b
    if len(set(ids)) != len(ids) or any(pid not in catalog for pid in ids):
        result.blockers = ['unknown_or_duplicate_player']
        return result
    if any(catalog[pid].ownership not in ('your_roster', 'other_roster') for pid in ids):
        result.blockers = ['uncorroborated_roster_ownership']
        return result
    plans = {'a': request.a.model_dump(), 'b': request.b.model_dump()}
    extra = request.a.add + request.a.drop + request.b.add + request.b.drop
    if len(extra) > 12 or len(set(ids + extra)) != len(ids + extra) or any(pid not in catalog for pid in extra):
        result.blockers = ['unknown_duplicate_or_excess_adjustment']
        return result
    if any(catalog[pid].ownership != 'unrostered_snapshot' for pid in request.a.add + request.b.add):
        result.blockers = ['add_not_corroborated_unrostered']
        return result
    if any(catalog[pid].ownership not in ('your_roster', 'other_roster') for pid in request.a.drop + request.b.drop):
        result.blockers = ['drop_not_corroborated_rostered']
        return result
    if any(catalog[pid].locked for pid in extra):
        result.blockers = ['adjustment_player_locked_or_game_binding_unknown']
        return result
    # Apply the preview's stricter identity/scoring/schedule evidence to all
    # roster-supporting players, not just the selected trade pieces.
    safe_players = [{**p, 'ros': {**p.get('ros', {}), 'full_ros_value': catalog[str(p['player_id'])].ros_points}}
                    for p in data.get('players', [])]
    raw = compare({**data, 'players': safe_players}, request.side_a, request.side_b, adjustments=plans)
    result.status = raw['status']
    result.blockers = raw.get('blockers', [])
    result.outlook = trade_outlook_context(data, by_id, request, plans)
    for key in ('side_a', 'side_b'):
        if raw.get(key):
            setattr(result, key, TradeSide(team=raw[key]['team'],
                missing_players=[by_id.get(pid, {}).get('name') or f'Unresolved player ({pid})'
                                 for pid in raw[key].get('missing_player_ids', [])],
                availability_review_players=[by_id.get(pid, {}).get('name') or f'Unresolved player ({pid})'
                                             for pid in raw[key].get('availability_review_ids', [])],
                roster_size_before=raw[key].get('roster_size_before'), roster_size_after=raw[key].get('roster_size_after'), conditional_lineup_gain=
                finite_points(raw[key].get('conditional_lineup_gain')) if result.status == 'research_candidate' else None))
    return result


def trade_outlook_context(data: dict, by_id: dict, request: TradeRequest, plans: dict) -> TradeOutlook:
    from src.services.trade_outlook import outlook
    raw = outlook(data, request.side_a, request.side_b, plans)
    if raw['status'] != 'research':
        return TradeOutlook(status=raw['status'])
    def side(row):
        if row.get('status') != 'research':
            return TradeOutlookSide(team=row.get('team'), status=row.get('status', 'unavailable'))
        return TradeOutlookSide(team=row.get('team'), status='research', weeks=row['weeks'],
            lineup_gain=finite_points(row['lineup_gain']),
            by_position={k: v for k, v in row['by_position'].items() if finite_points(v) is not None},
            weekly=[TradeWeek(**w) for w in row['weekly']],
            unmodeled_players=[by_id.get(pid, {}).get('name') or pid for pid in row['unmodeled_player_ids']])
    return TradeOutlook(status='research', side_a=side(raw['side_a']), side_b=side(raw['side_b']),
                        player_ros_points={k: finite_points(v) for k, v in raw['player_ros_points'].items()})


@router.post('/leagues/{league_id}/trade-preview', response_model=TradeResult)
async def trade_preview(league_id: str, request: TradeRequest, response: Response,
                        db: AsyncSession = Depends(get_db)):
    from src.services.workspace_capacity import admitted_trade
    response.headers['Cache-Control'] = 'no-store'
    async def load():
        league = await db.get(SleeperLeague, league_id)
        if league is None:
            raise HTTPException(404, 'League not found')
        if league.sport != 'nfl':
            raise HTTPException(422, 'NFL only')
        data = await read(db, league_id)
        if data is None:
            raise HTTPException(409, 'Current checkpoint unavailable; refresh before comparing')
        return data
    return await admitted_trade(load, lambda data: trade_context(data, request))


class LeagueSummary(BaseModel):
    league_id: str
    name: str
    sport: str
    platform: str


class Leagues(BaseModel):
    items: list[LeagueSummary]


@router.get('/leagues', response_model=Leagues)
async def leagues(response: Response, db: AsyncSession = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    rows = (await db.scalars(select(SleeperLeague).order_by(SleeperLeague.name))).all()
    return Leagues(items=[LeagueSummary(league_id=row.league_id, name=row.name,
                                       sport=row.sport, platform=row.platform) for row in rows])


class Starter(BaseModel):
    slot: str
    player_id: str | None = None
    name: str
    points: float | None = None
    source: str
    locked: bool = False


class MatchupSide(BaseModel):
    name: str
    recorded_points: float | None = None
    pregame_points: float | None = None
    starters: list[Starter] = Field(default_factory=list)


class MatchupView(BaseModel):
    status: str = 'unavailable'
    reason: str = 'No matchup snapshot is available.'
    recorded_at: str | None = None
    mine: MatchupSide | None = None
    opponent: MatchupSide | None = None


class LineupChanges(BaseModel):
    status: Literal['available', 'withheld'] = 'withheld'
    reason: str = 'A complete, lock-preserving comparison is not available.'
    start: list[Starter] = Field(default_factory=list)
    bench: list[Starter] = Field(default_factory=list)


def finite_points(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def decision_context(data: dict, by_id: dict, candidate: list[Starter]):
    """Present stored decisions only; no optimization, probability or score inference."""
    slots = [s for s in data.get('roster_positions', []) if s not in {'BN', 'IR', 'TAXI'}]
    matchup = data.get('matchup', {})
    rows = data.get('matchup_rosters', {})
    def side(key, projection, fallback):
        row = rows.get(key)
        if not row:
            return None
        ids = row.get('starters', [])
        entries = []
        for i in range(max(len(slots), len(ids))):
            pid = str(ids[i]) if i < len(ids) and ids[i] not in (None, '', '0', 0) else None
            player = by_id.get(pid, {})
            entries.append(Starter(slot=slots[i] if i < len(slots) else 'Unknown slot',
                player_id=pid, name=player.get('name') or ('Unresolved player' if pid else 'Unfilled slot'),
                points=finite_points(player.get('decision_points')),
                source=player.get('decision_tier', 'unknown'), locked=player.get('locked') is not False))
        name = next((r.get('name') for r in data.get('rosters', [])
                     if r.get('roster_id') == row.get('roster_id')), None)
        return MatchupSide(name=name or fallback, recorded_points=finite_points(row.get('points')),
            pregame_points=finite_points(matchup.get(projection)) if matchup.get('status') == 'pregame_candidate' else None,
            starters=entries)
    view = MatchupView(status=matchup.get('status', 'unavailable'),
        reason=matchup.get('reason') or 'No matchup forecast is available.',
        recorded_at=data.get('input_timestamps', {}).get('matchups'),
        mine=side('mine', 'your_pregame_projection', 'Your team'),
        opponent=side('opponent', 'opponent_pregame_projection', 'Opponent'))
    changes = LineupChanges()
    current = view.mine.starters if view.mine else []
    valid = (data.get('lineup_decision', {}).get('status') == 'lock_preserving_candidate'
             and bool(slots) and len(current) == len(candidate) == len(slots)
             and all(p.player_id in by_id for p in current + candidate)
             and len({p.player_id for p in current}) == len(current)
             and len({p.player_id for p in candidate}) == len(candidate)
             and all(p.slot == slots[i] for i, p in enumerate(candidate)))
    if valid:
        current_ids = {p.player_id for p in current}
        candidate_ids = {p.player_id for p in candidate}
        start = [p for p in candidate if p.player_id not in current_ids]
        bench = [p for p in current if p.player_id not in candidate_ids]
        locked_preserved = all(not p.locked or p.player_id == candidate[i].player_id
                               for i, p in enumerate(current))
        if locked_preserved and all(not p.locked for p in start + bench):
            changes = LineupChanges(status='available', start=start, bench=bench,
                reason='Review the complete candidate lineup; these are not independent one-for-one swaps.'
                if start else 'The candidate uses the same starters. Slot rearrangements are not player changes.')
    return view, changes


class ResearchCount(BaseModel):
    reason: str
    count: int


class ResearchStatus(BaseModel):
    status: str = 'unavailable'
    generated_at: str | None = None
    recipe: str | None = None
    requested_weeks: list[int] = Field(default_factory=list)
    new_captures: int = 0
    counts: list[ResearchCount] = Field(default_factory=list)
    blockers: list[ResearchCount] = Field(default_factory=list)
    serving_promoted: Literal[False] = False


class FantasyResearch(BaseModel):
    retention: ResearchStatus = Field(default_factory=ResearchStatus)
    specialists: ResearchStatus = Field(default_factory=ResearchStatus)


class Overview(BaseModel):
    schema_version: Literal["2"] = "2"
    league_id: str
    status: Literal["snapshot_available", "updating", "unsupported"]
    message: str
    actionable: Literal[False] = False
    generated_at: datetime | None = None
    expires_at: datetime | None = None
    week: int | None = None
    model_version: str | None = None
    recipe_version: str | None = None
    scoring_contract_hash: str | None = None
    lineup_status: str | None = None
    starters: list[Starter] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    matchup: MatchupView = Field(default_factory=MatchupView)
    lineup_changes: LineupChanges = Field(default_factory=LineupChanges)
    roster_players: list['PlayerDetail'] = Field(default_factory=list)
    comparison_players: list['PlayerDetail'] = Field(default_factory=list)
    waivers: 'WaiverView' = Field(default_factory=lambda: WaiverView())
    engine_waivers: 'EngineWaivers' = Field(default_factory=lambda: EngineWaivers())
    outcomes: 'OutcomeView' = Field(default_factory=lambda: OutcomeView())
    strength: 'StrengthView' = Field(default_factory=lambda: StrengthView())
    research: FantasyResearch = Field(default_factory=FantasyResearch)


class DistributionEvidence(BaseModel):
    source: str = 'unknown'
    status: str = 'unknown'
    observed_samples: int = 0
    reconciliation_samples: int | None = None
    reconciliation_mismatches: int | None = None
    assumed_prior: bool = False
    scope: str = 'historical_variability_not_ros_or_prospective_validation'


class SpecialistResearch(BaseModel):
    status: str
    points: float | None = None
    conditional_ros_points: float | None = None
    games: int = 0
    remaining_games: int = 0
    horizon_status: str
    scope: str
    serving_promoted: Literal[False] = False


class GameLogWeek(BaseModel):
    week: int
    points: float


class PositionStrength(BaseModel):
    position: str
    value: float | None = None
    rank: int | None = None
    teams: int = 0
    league_best: float | None = None


class StrengthView(BaseModel):
    status: str = 'unavailable'
    scope: str = 'engine_ros_research_best_starters_by_position_not_validated'
    overall_rank: int | None = None
    teams: int = 0
    positions: list[PositionStrength] = Field(default_factory=list)


class EngineWeek(BaseModel):
    week: int
    points: float
    environment: str


class PlayerDetail(BaseModel):
    player_id: str
    name: str
    position: str | None = None
    team: str | None = None
    points: float | None = None
    source: str = 'unknown'
    locked: bool = True
    injury_status: str | None = None
    identity_status: str = 'unknown'
    canonical_team_id: str | None = None
    game_availability_status: str = 'not_collected'
    game_availability_observed_at: str | None = None
    game_availability_hold: bool = False
    availability_status: str = 'unconfirmed_missing_designation'
    distribution: DistributionEvidence = Field(default_factory=DistributionEvidence)
    projection_observed_at: str | None = None
    history_through: str | None = None
    history_status: str = 'unknown'
    complete_scored_games: int | None = None
    missing_scoring_keys: list[str] = Field(default_factory=list)
    ros_status: str = 'unknown'
    ros_points: float | None = None
    known_schedule_subtotal: float | None = None
    known_remaining_games: int | None = None
    unknown_kickoffs: int | None = None
    through_week: int | None = None
    ownership: Literal['your_roster', 'other_roster', 'unrostered_snapshot', 'unknown'] = 'unknown'
    roster_names: list[str] = Field(default_factory=list)
    roster_id: str | None = None
    specialist_ros_research: SpecialistResearch | None = None
    # Engine research (projection_engine_serving): conditional on playing,
    # not prospectively qualified, never a decision input.
    engine_status: str = 'unknown'
    engine_week_points: float | None = None
    engine_ros_points: float | None = None
    engine_ros_games: int = 0
    engine_ros_lined_games: int = 0
    engine_weeks: list[EngineWeek] = Field(default_factory=list)
    engine_generated_at: str | None = None
    game_log: list[GameLogWeek] = Field(default_factory=list)


class EngineWaiverRow(BaseModel):
    add: PlayerDetail
    compare: PlayerDetail | None = None
    ros_gain: float | None = None
    week: int | None = None
    week_gain: float | None = None
    tier: Literal['priority', 'consider', 'depth', 'stream'] = 'depth'
    reasons: list[str] = Field(default_factory=list)


class EngineWaivers(BaseModel):
    status: str = 'unavailable'
    scope: str = 'engine_research_ros_not_validated'
    rows: list[EngineWaiverRow] = Field(default_factory=list)
    waiver_type: str = 'unknown'
    waiver_position: int | None = None
    teams: int | None = None
    waiver_clear_days: int | None = None
    tier_rule: str = ('priority: adds >= 15 starting-lineup points over the remaining weeks; consider: >= 5; '
                      'depth: positive but smaller; stream: K/DEF weekly provider gain. '
                      'Engine research thresholds, not validated value.')


class PlayerRange(BaseModel):
    density: list[float] = Field(default_factory=list)  # 2-point bins from -4 to 50
    mean: float | None = None
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    boom_probability: float | None = None
    bust_probability: float | None = None
    basis: str = 'unknown'


class LineupChange(BaseModel):
    slot: str
    start: str
    start_name: str
    replaces: str
    replaces_name: str


class OutcomeView(BaseModel):
    status: str = 'unavailable'
    reason: str = 'No outcome simulation in this snapshot.'
    validated: Literal[False] = False
    win_probability: float | None = None
    monte_carlo_standard_error: float | None = None
    mean: float | None = None
    opponent_mean: float | None = None
    p10: float | None = None
    p90: float | None = None
    opponent_p10: float | None = None
    opponent_p90: float | None = None
    best_win_probability: float | None = None
    best_expected_points: float | None = None
    best_changes: list[LineupChange] = Field(default_factory=list)
    known_final_starters: int = 0
    blockers: list[str] = Field(default_factory=list)
    player_ranges: dict[str, PlayerRange] = Field(default_factory=dict)
    blend_status: str | None = None
    validation_matchups: int | None = None
    validation_brier: float | None = None
    coin_flip_brier: float | None = None
    assumptions: list[str] = Field(default_factory=list)


def outcome_context(data: dict, by_id: dict) -> OutcomeView:
    stored = data.get('outcome_simulation') or {}
    model = stored.get('model') or {}
    matchups = ((model.get('validation') or {}).get('matchups') or {})
    view = OutcomeView(status=stored.get('status', 'unavailable'), reason=stored.get('reason') or OutcomeView().reason,
        blend_status=model.get('blend_status'), validation_matchups=matchups.get('n'),
        validation_brier=(matchups.get('correlated') or {}).get('brier'),
        coin_flip_brier=(matchups.get('coin') or {}).get('brier'), assumptions=stored.get('assumptions', []),
        blockers=[f"{b.get('name')}: {str(b.get('reason')).replace('_', ' ')}" for b in stored.get('blockers', [])])
    if view.status != 'estimated_research':
        return view
    current = stored.get('current') or {}
    for key in ('win_probability', 'monte_carlo_standard_error', 'mean', 'opponent_mean', 'p10', 'p90',
                'opponent_p10', 'opponent_p90'):
        setattr(view, key, finite_points(current.get(key)))
    best = stored.get('max_win_probability_lineup') or {}
    view.best_win_probability = finite_points(best.get('win_probability'))
    view.best_expected_points = finite_points(best.get('expected_points'))
    name = lambda pid: (by_id.get(pid) or {}).get('name') or 'Unresolved player'
    view.best_changes = [LineupChange(slot=c['slot'], start=c['start'], start_name=name(c['start']),
                                      replaces=c['replaces'], replaces_name=name(c['replaces']))
                         for c in best.get('changes', [])]
    view.known_final_starters = stored.get('known_final_starters', 0)
    view.player_ranges = {pid: PlayerRange(**{k: v if k in ('basis', 'density') else finite_points(v) for k, v in r.items()})
                          for pid, r in (stored.get('player_ranges') or {}).items()}
    return view


class WaiverMove(BaseModel):
    add: PlayerDetail
    drop: PlayerDetail
    unstarted_slot_gain: float
    recommendation_status: Literal['research_only'] = 'research_only'
    retention_warnings: list[str] = Field(default_factory=list)
    equivalent_drops: list[PlayerDetail] = Field(default_factory=list)


class WaiverView(BaseModel):
    status: str = 'unavailable'
    moves: list[WaiverMove] = Field(default_factory=list)
    excluded_moves: int = 0


Overview.model_rebuild()


def player_detail(player: dict) -> PlayerDetail:
    diagnostics = player.get('history_diagnostics', {})
    ros = player.get('ros', {})
    history = ros.get('per_game', {})
    full_ros = (ros.get('status') == 'complete_schedule_candidate'
                and history.get('status') == 'candidate' and not history.get('missing_scoring_keys')
                and player.get('identity_status') == 'exact')
    return PlayerDetail(player_id=str(player['player_id']), name=player.get('name') or 'Unresolved player',
        specialist_ros_research=player.get('specialist_ros_research'),
        position=player.get('position'), team=player.get('team'),
        points=finite_points(player.get('decision_points')), source=player.get('decision_source', 'unknown'),
        locked=player.get('locked') is not False, injury_status=player.get('injury_status'),
        identity_status=(player.get('_workspace_team_identity', {}).get('status', 'unresolved_team')
                         if player.get('position') in ('DEF', 'DST') else player.get('identity_status', 'unknown')),
        canonical_team_id=(player.get('_workspace_team_identity', {}).get('canonical_team_id')
                           if player.get('position') in ('DEF', 'DST') else None),
        availability_status=availability_evidence(player),
        game_availability_status=player.get('game_availability',{}).get('status','not_collected'),
        game_availability_observed_at=player.get('game_availability',{}).get('observed_at'),
        game_availability_hold=player.get('game_availability',{}).get('hold_recommendation') is True,
        distribution=DistributionEvidence(**uncertainty_evidence(player)),
        projection_observed_at=player.get('weekly_evidence', {}).get('observed_at'),
        history_through=player.get('history_through'),
        history_status=player.get('ros', {}).get('per_game', {}).get('status', 'unknown'),
        complete_scored_games=diagnostics.get('complete_scored_games'),
        missing_scoring_keys=diagnostics.get('missing_scoring_keys', []),
        ros_status=ros.get('status', 'unknown'),
        ros_points=finite_points(ros.get('full_ros_value')) if full_ros else None,
        known_schedule_subtotal=finite_points(ros.get('known_schedule_subtotal')),
        known_remaining_games=ros.get('known_remaining_games'), unknown_kickoffs=ros.get('unknown_kickoffs'),
        through_week=ros.get('through_week'), **engine_detail(player.get('engine') or {}),
        game_log=[GameLogWeek(week=r['week'], points=r['points'])
                  for r in (player.get('distribution_evidence') or {}).get('evidence', [])
                  if isinstance(r.get('week'), int) and finite_points(r.get('points')) is not None])


def engine_detail(engine: dict) -> dict:
    research = engine.get('status') in ('research', 'research_partial_scoring')
    return {'engine_status': engine.get('status', 'unknown'),
            'engine_week_points': finite_points(engine.get('week_points')) if research else None,
            'engine_ros_points': finite_points(engine.get('ros_points')) if research else None,
            'engine_ros_games': engine.get('ros_games', 0) if research else 0,
            'engine_ros_lined_games': engine.get('ros_lined_games', 0) if research else 0,
            'engine_weeks': [EngineWeek(**w) for w in engine.get('weeks', []) if finite_points(w.get('points')) is not None] if research else [],
            'engine_generated_at': engine.get('generated_at')}


def strength_context(data: dict, by_id: dict) -> StrengthView:
    """Rank each roster's best starters per position by engine ROS research.

    Uses the league's starting counts (FLEX excluded). A roster whose needed
    starters lack engine research is not ranked at that position.
    """
    rosters = data.get('rosters', [])
    slots = [s for s in data.get('roster_positions', []) if s in ('QB', 'RB', 'WR', 'TE')]
    if not rosters or not slots or sum(r.get('is_mine') is True for r in rosters) != 1:
        return StrengthView()
    def ros(pid):
        e = (by_id.get(pid) or {}).get('engine') or {}
        return finite_points(e.get('ros_points')) if e.get('status') == 'research' else None
    values = {}
    for r in rosters:
        ids = [str(pid) for pid in r.get('player_ids', [])]
        for pos in dict.fromkeys(slots):
            need = slots.count(pos)
            best = sorted((v for pid in ids if (by_id.get(pid) or {}).get('position') == pos
                           and (v := ros(pid)) is not None), reverse=True)[:need]
            values[(r['roster_id'], pos)] = round(sum(best), 1) if len(best) == need else None
    mine = next(r for r in rosters if r.get('is_mine') is True)['roster_id']
    out = []
    for pos in dict.fromkeys(slots):
        scores = [values[(r['roster_id'], pos)] for r in rosters if values[(r['roster_id'], pos)] is not None]
        own = values[(mine, pos)]
        out.append(PositionStrength(position=pos, value=own, teams=len(scores),
                                    rank=1 + sum(v > own for v in scores) if own is not None else None,
                                    league_best=max(scores) if scores else None))
    totals = {r['roster_id']: sum(values[(r['roster_id'], p)] for p in dict.fromkeys(slots))
              for r in rosters if all(values[(r['roster_id'], p)] is not None for p in dict.fromkeys(slots))}
    overall = 1 + sum(v > totals[mine] for v in totals.values()) if mine in totals else None
    return StrengthView(status='research', overall_rank=overall, teams=len(totals), positions=out)


WAIVER_TYPES = {0: 'rolling', 1: 'reverse_standings', 2: 'faab'}


def engine_waiver_context(data: dict, by_id: dict) -> EngineWaivers:
    """Present background waiver guidance (src/services/waiver_guidance.py); no computation here.

    Every row is revalidated against this checkpoint's ownership: the add must
    be unrostered and the drop on your roster, or the row is skipped.
    """
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    if len(mine) != 1:
        return EngineWaivers(status='owner_roster_unresolved')
    settings = data.get('waiver_settings') or {}
    context = dict(waiver_type=WAIVER_TYPES.get(settings.get('waiver_type'), 'unknown'),
                   waiver_position=mine[0].get('waiver_position'), teams=len(data.get('rosters', [])) or None,
                   waiver_clear_days=settings.get('waiver_clear_days'))
    stored = data.get('waiver_guidance') or {}
    if stored.get('status') != 'research':
        return EngineWaivers(status=stored.get('status', 'unavailable'), **context)
    owned = {str(pid) for r in data.get('rosters', []) for pid in r.get('player_ids', [])}
    my_ids = set(map(str, mine[0].get('player_ids', [])))
    rows = []
    for row in stored.get('rows', []):
        add, drop = by_id.get(row['add_id']), by_id.get(row['drop_id'])
        if not add or not drop or row['add_id'] in owned or add.get('roster_ids') != [] or row['drop_id'] not in my_ids:
            continue
        gain, week_gain = finite_points(row.get('lineup_gain')), finite_points(row.get('week_gain'))
        if row.get('stream'):
            rows.append(EngineWaiverRow(add=player_detail(add), compare=player_detail(drop), week_gain=week_gain,
                tier='stream', reasons=[f'Provider projects {week_gain:+.1f} this week over {drop.get("name")}; '
                                        'K/DEF rest-of-season is not modeled.']))
            continue
        if gain is None:
            continue
        reasons = [f'Adds {gain:+.1f} points to your best starting lineup across the next {row.get("weeks")} '
                   f'weeks (improves {row.get("weeks_improved")} of them) by replacing {drop.get("name")}.']
        if drop.get('position') != add.get('position'):
            reasons.append(f'Cross-position swap ({drop.get("position")} for {add.get("position")}).')
        if add.get('injury_status'):
            reasons.append(f'Added player has a {add["injury_status"]} designation.')
        if ((add.get('engine') or {}).get('ros_lined_games') or 0) <= 1:
            reasons.append('Most weeks have no market line yet (team-model environment).')
        rows.append(EngineWaiverRow(add=player_detail(add), compare=player_detail(drop), ros_gain=gain,
            week=row.get('week'), week_gain=week_gain, reasons=reasons,
            tier='priority' if gain >= 15 else 'consider' if gain >= 5 else 'depth'))
    if not rows:
        return EngineWaivers(status='no_positive_research_moves', **context)
    order = {'priority': 0, 'consider': 1, 'stream': 2, 'depth': 3}
    rows.sort(key=lambda r: (order[r.tier], -(r.ros_gain if r.ros_gain is not None else r.week_gain or 0),
                             r.add.player_id))
    return EngineWaivers(status='research', rows=rows[:20], **context)


def roster_context(data: dict, by_id: dict):
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    ids = set(map(str, mine[0].get('player_ids', []))) if len(mine) == 1 else set()
    roster = [player_detail(by_id[pid]) if pid in by_id else player_detail({'player_id': pid})
              for pid in sorted(ids)]
    stored = data.get('waivers', {})
    view = WaiverView(status=stored.get('status', 'unavailable'))
    starters = set(map(str, (data.get('matchup_rosters', {}).get('mine') or {}).get('starters', [])))
    for move in stored.get('moves', []):
        add_id, drop_id = str(move.get('add_id')), str(move.get('drop_id'))
        add, drop = by_id.get(add_id), by_id.get(drop_id)
        gain = finite_points(move.get('lineup_gain'))
        eligible = (view.status == 'lock_preserving_candidate' and bool(ids) and bool(starters)
                    and move.get('scope') == 'unstarted_slots_only' and gain is not None and gain > 0
                    and add and drop and drop_id in ids and drop_id not in starters and add_id not in ids
                    and add.get('replacement_pool_member') is True and add.get('roster_ids') == []
                    and add.get('locked') is False and drop.get('locked') is False
                    and finite_points(add.get('decision_points')) is not None)
        if eligible:
            addition, removal = player_detail(add), player_detail(drop)
            warnings = ['Long-term roster cost is not included in the weekly gain. This is not a drop recommendation.']
            if addition.ros_points is None or removal.ros_points is None:
                warnings.append('Full rest-of-season evidence is missing for one or both players; the cost of releasing this player is unresolved.')
            elif removal.ros_points > addition.ros_points:
                warnings.append('The dropped player has a higher conditional ROS estimate. These research estimates are not validated trade values.')
            if not addition.position or not removal.position:
                warnings.append('Position coverage is incomplete; positional depth cannot be assessed.')
            elif addition.position != removal.position:
                warnings.append('This exchanges different positions; bye-week cover and positional depth are not valued by the weekly gain.')
            if removal.injury_status:
                warnings.append('The proposed drop has an injury designation; temporary absence does not establish low long-term value.')
            equivalent=[]
            for pid in sorted(set(map(str,move.get('equivalent_drop_ids',[])))):
                alternative=by_id.get(pid)
                if (pid != drop_id and pid in ids and pid not in starters and alternative
                        and alternative.get('locked') is False):
                    equivalent.append(player_detail(alternative))
            if equivalent:
                warnings.append('Multiple drops produce the same rounded weekly gain. Display order is not a retention-value ranking.')
            view.moves.append(WaiverMove(add=addition, drop=removal, unstarted_slot_gain=gain,
                                        retention_warnings=warnings, equivalent_drops=equivalent))
        else:
            view.excluded_moves += 1
    return roster, view


def comparison_context(data: dict, by_id: dict) -> list[PlayerDetail]:
    """Bounded checkpoint catalog, not a live free-agent lookup."""
    rosters = data.get('rosters', [])
    membership = {}
    for roster in rosters:
        for pid in set(map(str, roster.get('player_ids', []))):
            membership.setdefault(pid, []).append(roster)
    result = []
    for pid in sorted(set(by_id) | set(membership)):
        raw = by_id.get(pid, {'player_id': pid})
        player = player_detail(raw)
        owners = membership.get(pid, [])
        owner_ids = {str(r['roster_id']) for r in owners if r.get('roster_id') is not None}
        declared = raw.get('roster_ids')
        corroborated = isinstance(declared, list) and set(map(str, declared)) == owner_ids
        if corroborated and len(owners) == 1 and len(owner_ids) == 1:
            player.ownership = 'your_roster' if owners[0].get('is_mine') is True else 'other_roster'
            player.roster_id = next(iter(owner_ids))
        elif corroborated and not owners and rosters:
            player.ownership = 'unrostered_snapshot'
        player.roster_names = [r.get('name') or 'Unnamed roster' for r in owners]
        result.append(player)
    return sorted(result, key=lambda p: (p.name.casefold(), p.player_id))


def overview(league_id: str, data: dict | None) -> Overview:
    if data is None:
        return Overview(league_id=league_id, status="updating", message=
                        "No current background snapshot is available. No forecast was rebuilt by this request.")
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    lineup = data.get('lineup_decision', {})
    starters = []
    for entry in lineup.get('lineup', []):
        pid = str(entry['player_id']) if entry.get('player_id') is not None else None
        player = by_id.get(pid, {})
        starters.append(Starter(slot=entry['slot'], player_id=pid,
            name=player.get('name') or ('Unresolved player' if pid else 'Unfilled slot'),
            points=finite_points(player.get('decision_points')), source=player.get('decision_tier', 'unknown'),
            locked=player.get('locked') is not False))
    matchup, changes = decision_context(data, by_id, starters)
    roster, waivers = roster_context(data, by_id)
    evidence = data['read_model']
    return Overview(league_id=league_id, status="snapshot_available",
        message="Background snapshot available. Estimates are not validated probabilities or submitted lineup changes.",
        generated_at=evidence['generated_at'], expires_at=evidence['expires_at'],
        week=data.get('week'), model_version=data.get('model_version'),
        recipe_version=data.get('recipe_version'), scoring_contract_hash=data.get('scoring_contract_hash'),
        lineup_status=lineup.get('status'), starters=starters, notes=data.get('notes', []),
        matchup=matchup, lineup_changes=changes, roster_players=roster, waivers=waivers,
        engine_waivers=engine_waiver_context(data, by_id), outcomes=outcome_context(data, by_id),
        strength=strength_context(data, by_id),
        comparison_players=comparison_context(data, by_id))


@router.get('/leagues/{league_id}/overview', response_model=Overview)
async def league_overview(league_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    if league.sport != 'nfl':
        return Overview(league_id=league_id, status='unsupported',
                        message='The replacement fantasy workspace currently supports NFL leagues.')
    result = overview(league_id, await read(db, league_id))
    from asyncio import to_thread
    from config.settings import get_settings
    from src.services.fantasy_research_status import latest
    if result.status == 'snapshot_available':
        result.research = FantasyResearch(**await to_thread(latest,
            get_settings().raw_archive_dir, league_id, league.season))
    if result.status == 'updating':
        response.headers['Retry-After'] = '30'
    return result


class PairedSummary(BaseModel):
    n: int = 0
    weeks: list[int] = Field(default_factory=list)
    engine_mae: float | None = None
    sleeper_mae: float | None = None
    paired_difference: float | None = None
    ci: list[float] | None = None


class QualificationTrack(BaseModel):
    name: str
    status: str
    generated_at: datetime | None = None
    version: str | None = None
    engine_forecasts: int | None = None
    graded_weeks: int = 0
    required_weeks: int
    eligible_for_owner_review: bool = False
    serving_promoted: Literal[False] = False
    blockers: list[str] = Field(default_factory=list)
    pool: PairedSummary = Field(default_factory=PairedSummary)
    statuses: dict[str, int] = Field(default_factory=dict)


class WinProbabilityCheck(BaseModel):
    status: str
    generated_at: datetime | None = None
    captured_matchups: int = 0
    graded: int = 0
    brier: float | None = None
    coin_flip_brier: float = 0.25
    log_loss: float | None = None
    statuses: dict[str, int] = Field(default_factory=dict)


class EngineQualification(BaseModel):
    tracks: list[QualificationTrack]
    win_probability: WinProbabilityCheck
    note: str = ('Prospective pairing against Sleeper on the projected-starter pool, graded on league-scored results '
                 'after kickoff. Nothing is promoted automatically; eligibility only opens an owner review.')


def qualification_tracks(root) -> list[QualificationTrack]:
    """Latest saved prospective report per track; a missing report is a status, not zeros."""
    import json
    from src.services.projection_engine_prospective import VARIANT_MIN_WEEKS, VARIANTS

    def summary(raw):
        raw = raw or {}
        return PairedSummary(**{k: raw.get(k) for k in PairedSummary.model_fields if raw.get(k) is not None})

    tracks = []
    for variant, label in (('v1', 'Projection engine v1'), ('depth', 'Engine + depth chart/status')):
        MIN_WEEKS = VARIANT_MIN_WEEKS[variant]
        files = sorted((root / VARIANTS[variant][1]).glob('*.json'))
        if not files:
            tracks.append(QualificationTrack(name=label, status='no_report_yet', required_weeks=MIN_WEEKS))
            continue
        try:
            report = json.loads(files[-1].read_text())
        except (OSError, ValueError):
            tracks.append(QualificationTrack(name=label, status='report_unreadable', required_weeks=MIN_WEEKS))
            continue
        for name, block, meta in ((label, report.get('promotion') or {}, report),
                                  (f'{label} · Sleeper blend', (report.get('candidate_blend') or {}).get('promotion') or {}, None)):
            if meta is None and variant != 'v1':
                continue  # the candidate blend is graded once, on the v1 report
            pool = summary(block.get('pool'))
            tracks.append(QualificationTrack(name=name, status=report.get('status', 'unknown'),
                generated_at=report.get('generated_at'), version=report.get('version'),
                engine_forecasts=report.get('engine_forecasts') if meta else None, graded_weeks=len(pool.weeks),
                required_weeks=block.get('required_weeks', MIN_WEEKS), eligible_for_owner_review=bool(block.get('eligible_for_owner_review')),
                blockers=block.get('blockers', []), pool=pool, statuses=report.get('statuses', {}) if meta else {}))
    return tracks


def win_probability_check(root) -> WinProbabilityCheck:
    import json
    files = sorted((root / 'reports').glob('*.json'))
    if not files:
        return WinProbabilityCheck(status='no_report_yet')
    try:
        report = json.loads(files[-1].read_text())
    except (OSError, ValueError):
        return WinProbabilityCheck(status='report_unreadable')
    summary = report.get('summary') or {}
    return WinProbabilityCheck(status=report.get('status', 'unknown'), generated_at=report.get('generated_at'),
        captured_matchups=report.get('captured_matchups', 0), graded=summary.get('n', 0), brier=summary.get('brier'),
        log_loss=summary.get('log_loss'), statuses=report.get('statuses', {}))


@router.get('/engine-qualification', response_model=EngineQualification)
async def engine_qualification(response: Response):
    from src.services.projection_engine_prospective import archive_root
    from src.services.outcome_prospective import archive_root as outcome_root
    response.headers['Cache-Control'] = 'no-store'
    return EngineQualification(tracks=qualification_tracks(archive_root()),
                               win_probability=win_probability_check(outcome_root()))
