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


class DraftPickInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    side: Literal['a','b']
    season: int = Field(ge=2020,le=2100)
    round: int = Field(ge=1,le=10)
    slot: int | None = Field(default=None,ge=1,le=32)
    value: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    source: str | None = Field(default=None,max_length=200)
    original_roster_id: str | None = Field(default=None,max_length=100)
    pick_id: str | None = Field(default=None,max_length=40)


class DynastyPackage(BaseModel):
    player_ids: list[str] = Field(default_factory=list)
    picks: list['DraftPickView'] = Field(default_factory=list)
    observed_player_index: float | None = None
    scenario_package_index: float | None = None
    unpriced_player_ids: list[str] = Field(default_factory=list)
    unpriced_picks: int = 0


class DraftPickView(DraftPickInput):
    valuation_type: str = 'unpriced'
    ownership_verified: bool = False
    market_id: str | None = None
    basis: str | None = None


class DynastyPlan(BaseModel):
    status: str
    goal: str | None = None
    packages: dict[str,DynastyPackage] = Field(default_factory=dict)
    side_a_market_index_change: float | None = None
    market_captured_at: str | None = None
    goal_guidance: str | None = None
    pick_ownership_verified: bool = False
    note: str | None = None


class MarketChange(BaseModel):
    player_id: str
    current: float | None = None
    prior: float | None = None
    change: float | None = None


class MarketTrends(BaseModel):
    status: str
    captured_at: str | None = None
    prior_captured_at: str | None = None
    players: list[MarketChange] = Field(default_factory=list)


class TradeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: datetime
    side_a: list[str] = Field(min_length=1, max_length=6)
    side_b: list[str] = Field(min_length=1, max_length=6)
    a: TradeAdjustment = Field(default_factory=TradeAdjustment)
    b: TradeAdjustment = Field(default_factory=TradeAdjustment)
    goal: Literal['balanced','contender','rebuild'] = 'balanced'
    picks: list[DraftPickInput] = Field(default_factory=list,max_length=12)


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


class TradeMarket(BaseModel):
    """FantasyCalc trade-market values (an index built from real trades), not fantasy points."""
    status: str
    captured_at: str | None = None
    values: dict[str, float | None] = Field(default_factory=dict)
    side_a_total: float | None = None
    side_b_total: float | None = None
    attribution: str = 'FantasyCalc'
    note: str = ('Market value index from real trades in leagues of this format; custom scoring is not fully '
                 'represented. Not fantasy points and not a fairness verdict.')


class TradeOutlook(BaseModel):
    status: str
    market: TradeMarket | None = None
    side_a: TradeOutlookSide | None = None
    side_b: TradeOutlookSide | None = None
    player_ros_points: dict[str, float | None] = Field(default_factory=dict)
    note: str = ('Engine research: each remaining week your best offensive lineup is re-solved before and after the trade '
                 '(only verified byes or confirmed absences supply zero; missing coverage withholds comparisons), summed by the starting player\'s position. '
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
    dynasty: DynastyPlan | None = None
    market_trends: MarketTrends | None = None
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
    if raw['status'] != 'research' and not (raw.get('side_a') and raw.get('side_b')):
        return TradeOutlook(status=raw['status'])
    def side(row):
        if row.get('status') != 'research':
            return TradeOutlookSide(team=row.get('team'), status=row.get('status', 'unavailable'))
        return TradeOutlookSide(team=row.get('team'), status='research', weeks=row['weeks'],
            lineup_gain=finite_points(row['lineup_gain']),
            by_position={k: v for k, v in row['by_position'].items() if finite_points(v) is not None},
            weekly=[TradeWeek(**w) for w in row['weekly']],
            unmodeled_players=[by_id.get(pid, {}).get('name') or pid for pid in row['unmodeled_player_ids']])
    return TradeOutlook(status=raw['status'], side_a=side(raw['side_a']), side_b=side(raw['side_b']),
                        player_ros_points={k: finite_points(v) for k, v in raw.get('player_ros_points',{}).items()})


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
    league_ref = {}

    async def load_with_league():
        data = await load()
        league_ref['league'] = await db.get(SleeperLeague, league_id)
        league_ref['inventory'] = await draft_inventory(db, league_ref['league']) if request.picks else None
        return data
    return await admitted_trade(load_with_league, lambda data: with_market(
        trade_context(data, request), data, league_ref.get('league'), request, league_ref.get('inventory')))


class DraftPickOffer(BaseModel):
    id: str
    season: int
    round: int
    original_roster_id: int
    owner_roster_id: int
    value: float | None = None
    market_id: str | None = None
    basis: str


class DraftPickInventory(BaseModel):
    status: str
    picks: list[DraftPickOffer] = Field(default_factory=list)
    ownership_source: str | None = None
    market_captured_at: str | None = None
    attribution: str | None = None
    note: str | None = None


@router.get('/leagues/{league_id}/draft-picks', response_model=DraftPickInventory)
async def draft_picks(league_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    """Read-only: synced ownership plus the archived daily market snapshot; no provider call."""
    response.headers['Cache-Control'] = 'no-store'
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    return DraftPickInventory(**(await draft_inventory(db, league) or {'status': 'not_a_dynasty_league'}))


async def draft_inventory(db: AsyncSession, league) -> dict | None:
    """Verified rookie-pick ownership and FantasyCalc prices; None outside Sleeper dynasty leagues."""
    from src.models.sleeper import SleeperLeagueSnapshot, SleeperRoster
    from src.services.draft_picks import inventory
    from src.services.fantasy_market import cohort, snapshot
    if league is None or league.platform != 'sleeper' or (league.settings or {}).get('type') != 2:
        return None
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league.league_id))).all()
    traded = await db.scalar(select(SleeperLeagueSnapshot.payload).where(
        SleeperLeagueSnapshot.league_id == league.league_id, SleeperLeagueSnapshot.kind == 'traded_picks'))
    return inventory(league, list(rosters), traded if isinstance(traded, list) else None,
                     snapshot(cohort(league, len(rosters))))


def with_market(result: TradeResult, data: dict, league, request: TradeRequest, inventory: dict | None = None) -> TradeResult:
    """Attach FantasyCalc values for the traded players (daily archive; stale or unmatched is a status)."""
    from src.services.fantasy_market import cohort, selected
    if result.outlook is None or league is None:
        return result
    ids = request.side_a + request.side_b
    raw = selected(cohort(league, len(data.get('rosters', []))), league.platform, ids)
    values = {p['player_id']: finite_points(p.get('value')) for p in raw.get('players', [])}
    total = lambda side: sum(values[i] for i in side) if side and all(values.get(i) is not None for i in side) else None
    result.outlook.market = TradeMarket(status=raw.get('status', 'unavailable'), captured_at=raw.get('captured_at'),
        values=values, side_a_total=total(request.side_a), side_b_total=total(request.side_b))
    from src.services.dynasty_trade_planning import plan
    from src.services.fantasy_market_trends import trends
    result.dynasty=DynastyPlan(**plan(data,request.side_a,request.side_b,goal=request.goal,
        picks=[p.model_dump(exclude_none=True) for p in request.picks],market=raw,
        inventory=inventory))
    result.market_trends=MarketTrends(**trends(cohort(league,len(data.get('rosters',[]))),league.platform,ids))
    return result


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
    recorded_points: float | None = None  # the platform's points so far this week
    position: str | None = None


class MatchupSide(BaseModel):
    name: str
    recorded_points: float | None = None
    pregame_points: float | None = None
    starters: list[Starter] = Field(default_factory=list)
    # Hindsight: the best lineup from this roster's recorded points so far.
    optimal_points: float | None = None
    optimal: list[Starter] = Field(default_factory=list)
    start_sit_accuracy: float | None = None


class AccuracyWeek(BaseModel):
    week: int
    actual: float
    optimal: float
    accuracy: float


def hindsight(row: dict, by_id: dict, roster_positions: list[str]):
    """Best possible lineup from the roster's recorded points (FantasyPros' "Optimal" view)."""
    from src.services.fantasy_decision_models import optimize
    points = row.get('players_points') or {}
    pool = [{'player_id': str(pid), 'name': by_id.get(str(pid), {}).get('name') or str(pid),
             'position': by_id.get(str(pid), {}).get('position'), 'weekly_points': finite_points(points.get(str(pid), points.get(pid)))}
            for pid in row.get('players', []) or []]
    pool = [p for p in pool if p['weekly_points'] is not None and p['position']]
    if not pool:
        return None, []
    result = optimize(pool, roster_positions)
    if not result['modeled_subtotal']:
        return None, []  # nothing recorded yet this week: no hindsight to show
    return result['modeled_subtotal'], [Starter(slot=e['slot'], player_id=e['player_id'], name=e['name'] or 'Unfilled slot',
        source='recorded', recorded_points=e['points'], position=by_id.get(str(e['player_id']), {}).get('position'))
        for e in result['lineup']]


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
            recorded = (row.get('players_points') or {}).get(pid) if pid else None
            entries.append(Starter(slot=slots[i] if i < len(slots) else 'Unknown slot',
                player_id=pid, name=player.get('name') or ('Unresolved player' if pid else 'Unfilled slot'),
                points=finite_points(player.get('decision_points')),
                source=player.get('decision_tier', 'unknown'), locked=player.get('locked') is not False,
                recorded_points=finite_points(recorded), position=player.get('position')))
        name = next((r.get('name') for r in data.get('rosters', [])
                     if r.get('roster_id') == row.get('roster_id')), None)
        best, optimal = hindsight(row, by_id, data.get('roster_positions', []))
        actual = finite_points(row.get('points'))
        return MatchupSide(name=name or fallback, recorded_points=actual,
            pregame_points=finite_points(matchup.get(projection)) if matchup.get('status') == 'pregame_candidate' else None,
            starters=entries, optimal_points=best, optimal=optimal,
            start_sit_accuracy=round(actual / best, 4) if actual is not None and best else None)
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


class LateSwapPlan(BaseModel):
    starter_id: str
    starter_name: str
    slot: str
    replacement_id: str
    replacement_name: str
    replacement_points: float
    projection_source: str
    check_by: str
    replacement_kickoff: str
    availability_trigger: str
    risk_adjusted_points: float | None = None


class SwapBlocker(BaseModel):
    player_id: str
    reason: str


class LateSwapView(BaseModel):
    status: str = 'unavailable'
    plans: list[LateSwapPlan] = Field(default_factory=list)
    blockers: list[SwapBlocker] = Field(default_factory=list)


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
    season_accuracy: list[AccuracyWeek] = Field(default_factory=list)
    strength: 'StrengthView' = Field(default_factory=lambda: StrengthView())
    research: FantasyResearch = Field(default_factory=FantasyResearch)
    late_swap: LateSwapView = Field(default_factory=LateSwapView)


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


class SlotStrength(BaseModel):
    slot: str                 # QB, RB1, RB2, WR1, ..., FLEX, or BENCH
    player_name: str | None = None
    value: float | None = None
    rank: int | None = None
    teams: int = 0


class TeamRanking(BaseModel):
    roster_id: str
    name: str | None = None
    is_mine: bool = False
    score: float              # 0-100: starting-lineup ROS points vs the league's best
    rank: int


class StrengthView(BaseModel):
    status: str = 'unavailable'
    scope: str = 'engine_ros_research_best_starters_by_position_not_validated'
    overall_rank: int | None = None
    teams: int = 0
    positions: list[PositionStrength] = Field(default_factory=list)
    slots: list[SlotStrength] = Field(default_factory=list)
    team_rankings: list[TeamRanking] = Field(default_factory=list)


def lineup_slots(players: list[dict], roster_positions: list[str], bench_size: int):
    """Best ROS lineup by slot (RB1/RB2 ordered by value) plus the top bench players' total."""
    from src.services.fantasy_decision_models import optimize
    slots = [s for s in roster_positions if s not in ('BN', 'IR', 'TAXI', 'K', 'DEF', 'DST')]
    pool = [{'player_id': p['player_id'], 'name': p.get('name'), 'position': p.get('position'),
             'weekly_points': (p.get('engine') or {}).get('ros_points')} for p in players
            if (p.get('engine') or {}).get('status') == 'research' and finite_points((p.get('engine') or {}).get('ros_points')) is not None]
    if not slots or not pool:
        return {}, None
    lineup = optimize(pool, slots)['lineup']
    out = {}
    for base in dict.fromkeys(e['slot'] for e in lineup):
        filled = sorted((e for e in lineup if e['slot'] == base and e['player_id'] is not None), key=lambda e: -(e['points'] or 0))
        many = sum(e['slot'] == base for e in lineup) > 1
        for i, e in enumerate(filled, 1):
            label = f'{base}{i}' if many else base
            out[label] = (e['name'], round(e['points'], 1))
    used = {e['player_id'] for e in lineup if e['player_id'] is not None}
    bench = sorted((p['weekly_points'] for p in pool if p['player_id'] not in used), reverse=True)[:bench_size]
    return out, round(sum(bench), 1)


class EngineWeek(BaseModel):
    week: int
    points: float
    environment: str


class AvailabilityReport(BaseModel):
    status: str
    source: str
    fetched_at: str | None = None
    reported_at: str | None = None
    season: int | None = None
    week: int | None = None
    team: str | None = None


class RoleTrend(BaseModel):
    recent: float | None = None
    prior: float | None = None
    change: float | None = None
    recent_games: int = 0
    prior_games: int = 0


class RoleProfile(BaseModel):
    status: str
    trends: dict[str,RoleTrend] = Field(default_factory=dict)
    note: str | None = None


class PlayerDetail(BaseModel):
    player_id: str
    name: str
    # 'IR' or 'Taxi' when the platform holds this player in a reserve slot on your roster.
    reserve_slot: str | None = None
    position: str | None = None
    team: str | None = None
    points: float | None = None
    source: str = 'unknown'
    locked: bool = True
    injury_status: str | None = None
    normalized_injury_status: str | None = None
    availability_evidence: AvailabilityReport | None = None
    practice_observed_at: str | None = None
    practice_evidence_status: str | None = None
    role_changes: RoleProfile | None = None
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
    # Second source and consensus (FantasyPros method): ESPN's projection in
    # this league's scoring and the mean of the available sources (provider,
    # ESPN, engine). Research columns, graded prospectively; never decisions.
    # Strength of schedule for the player's position: 1-5 stars, 5 = easiest.
    sos_ros_stars: int | None = None
    sos_next4_stars: int | None = None
    # Questionable/Doubtful: how often regulars with this designation and practice
    # participation played (2016-2025 nflverse reports; src/services/availability_rates).
    play_probability: float | None = None
    play_basis: str | None = None
    play_sample: int | None = None
    practice_status: Literal['dnp', 'limited', 'full'] | None = None
    # This week's NFL game (for "Are they playing?"): opponent, status, kickoff.
    opponent: str | None = None
    week_game_status: str | None = None
    week_kickoff: str | None = None
    espn_week_points: float | None = None
    consensus_week_points: float | None = None
    consensus_sources: int = 0
    engine_status: str = 'unknown'
    engine_week_points: float | None = None
    engine_ros_points: float | None = None
    engine_ros_games: int = 0
    engine_ros_lined_games: int = 0
    engine_weeks: list[EngineWeek] = Field(default_factory=list)
    engine_generated_at: str | None = None
    # Decision projection = 50/50 provider + engine v2 when v2 projects the
    # player (fantasy_decision_models.blend_engine_v2); `points` is that value.
    provider_week_points: float | None = None
    engine_v2_status: str = 'unknown'
    engine_v2_week_points: float | None = None
    projection_source: str = 'provider'
    # Owner's never-drop list (src/services/never_drop): never offered as a drop.
    never_drop: bool = False
    # Why this rostered player is never the drop: 'never_drop', 'starter' or 'core_rank'
    # (fantasy_decision_models.drop_protection); `drop_rank` is e.g. 'RB14'.
    drop_protection: str | None = None
    drop_rank: str | None = None
    drop_starter_spots: int | None = None
    game_log: list[GameLogWeek] = Field(default_factory=list)


class WaiverWeek(TradeWeek):
    add_status: str | None = None


class EngineWaiverRow(BaseModel):
    trending_adds: int | None = None  # Sleeper adds in the last 24 h (context only)
    add: PlayerDetail
    compare: PlayerDetail | None = None
    ros_gain: float | None = None
    week: int | None = None
    week_gain: float | None = None
    tier: Literal['priority', 'consider', 'depth', 'stream'] = 'depth'
    reasons: list[str] = Field(default_factory=list)
    weekly: list[WaiverWeek] = Field(default_factory=list)
    alternative_drops: list['AlternativeDrop'] = Field(default_factory=list)
    needed_by_week: int | None = None
    target_game_kickoff: str | None = None
    claim_timing: str | None = None


class AlternativeDrop(BaseModel):
    drop_id: str
    name: str | None = None
    lineup_gain: float
    weekly: list[TradeWeek] = Field(default_factory=list)


class MissingCoveragePlayer(BaseModel):
    name: str
    position: str | None = None


class WaiverCoverageBlocker(BaseModel):
    week: int | None = None
    missing_player_ids: list[str] = Field(default_factory=list)
    missing_players: list[MissingCoveragePlayer] = Field(default_factory=list)


class WaiverThresholds(BaseModel):
    min_lineup_gain: float = 1.0
    min_stream_gain: float = 1.0


class TrendingAdd(BaseModel):
    player: PlayerDetail
    adds: int


class FaabBid(BaseModel):
    add_id: str
    drop_id: str
    lineup_gain: float
    share_of_remaining: float
    bid_low: int
    bid_high: int


class FaabHistory(BaseModel):
    claims: int = 0
    median_share: float | None = None


class FaabPlan(BaseModel):
    status: str = 'not_a_faab_league'
    rows: list[FaabBid] = Field(default_factory=list)
    remaining_budget: int | None = None
    budget: int | None = None
    weeks_left: int | None = None
    rival_max_remaining: int | None = None
    league_history: FaabHistory | None = None
    note: str | None = None


class EngineWaivers(BaseModel):
    status: str = 'unavailable'
    # Bid ranges, only in leagues that bid; absent (not_a_faab_league) elsewhere.
    faab: FaabPlan | None = None
    scope: str = 'engine_research_selected_horizon'
    rows: list[EngineWaiverRow] = Field(default_factory=list)
    # Sleeper's most-added players (24 h) still unrostered in this league; crowd context only.
    trending: list[TrendingAdd] = Field(default_factory=list)
    waiver_type: str = 'unknown'
    waiver_position: int | None = None
    teams: int | None = None
    waiver_clear_days: int | None = None
    # Your IR/taxi players: never suggested as drops (each add is re-solved without them).
    protected: list[PlayerDetail] = Field(default_factory=list)
    horizon_weeks: int = 2
    thresholds: WaiverThresholds = Field(default_factory=WaiverThresholds)
    coverage_blockers: list[WaiverCoverageBlocker] = Field(default_factory=list)
    tier_rule: str = ('priority: adds >= 15 starting-lineup points over the selected horizon; consider: >= 5; '
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
    # Count only starters with a recorded final; bye/out zeros are not finished games.
    starters = {str(x) for side in ('mine', 'opponent') for x in (data.get('matchup_rosters', {}).get(side) or {}).get('starters', [])}
    view.known_final_starters = sum((stored.get('player_ranges') or {}).get(pid, {}).get('basis') == 'final_recorded'
                                    for pid in starters)
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
    from src.services.availability_status import normalize_status
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
        normalized_injury_status=normalize_status(player.get('injury_status')),
        availability_evidence=(player.get('_play') or {}).get('evidence'),
        practice_observed_at=(player.get('_play') or {}).get('observed_at'),
        practice_evidence_status=(player.get('_play') or {}).get('practice_evidence_status'),
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
        **consensus_detail(player),
        provider_week_points=finite_points(player.get('provider_points', player.get('weekly_points'))),
        engine_v2_status=(player.get('engine_v2') or {}).get('status', 'unknown'),
        engine_v2_week_points=finite_points((player.get('engine_v2') or {}).get('week_points'))
        if (player.get('engine_v2') or {}).get('status') in ('research', 'research_partial_scoring') else None,
        projection_source=player.get('projection_source', 'provider'), never_drop=player.get('never_drop') is True,
        drop_protection=(player.get('drop_protection') or {}).get('reason'),
        drop_rank=(player.get('drop_protection') or {}).get('rank'),
        drop_starter_spots=(player.get('drop_protection') or {}).get('starter_spots'),
        sos_ros_stars=(player.get('_sos') or {}).get('ros_stars'), sos_next4_stars=(player.get('_sos') or {}).get('next4_stars'),
        reserve_slot=player.get('_reserve_slot'),
        play_probability=(player.get('_play') or {}).get('probability'), play_basis=(player.get('_play') or {}).get('basis'),
        play_sample=(player.get('_play') or {}).get('n'), practice_status=(player.get('_play') or {}).get('practice'),
        opponent=player.get('opponent'), week_game_status=player.get('week_game_status'),
        week_kickoff=player.get('week_kickoff'),
        game_log=[GameLogWeek(week=r['week'], points=r['points'])
                  for r in (player.get('distribution_evidence') or {}).get('evidence', [])
                  if isinstance(r.get('week'), int) and finite_points(r.get('points')) is not None])


def consensus_detail(player: dict) -> dict:
    engine = player.get('engine') or {}
    members = [finite_points(player.get('provider_points', player.get('weekly_points'))), finite_points(player.get('_espn_points')),
               finite_points(engine.get('week_points')) if engine.get('status') in ('research', 'research_partial_scoring') else None]
    known = [v for v in members if v is not None]
    return {'espn_week_points': members[1], 'consensus_sources': len(known),
            'consensus_week_points': round(sum(known) / len(known), 2) if len(known) >= 2 else None}


async def attach_espn(db, league, data: dict) -> None:
    """Join the latest ESPN projections (same week, Sleeper leagues) onto checkpoint players, in memory."""
    from src.services import espn_projections
    from src.services.fantasy_decision_models import offensive_weights
    if not data or league.platform != 'sleeper':
        return
    latest = await espn_projections.latest(db)
    if not latest or latest.get('week') != data.get('week'):
        return
    weights = offensive_weights(league.scoring_settings)
    for p in data.get('players', []):
        row = latest['players'].get(str(p.get('canonical_player_id')))
        if row and row.get('position') == p.get('position'):
            p['_espn_points'] = round(espn_projections.score(row['stats'], weights), 2)


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
    # League Analyzer: starter-slot and bench ranks, and a team ranking table.
    bench_size = max(1, data.get('roster_positions', []).count('BN'))
    per = {r['roster_id']: lineup_slots([by_id[pid] for pid in map(str, r.get('player_ids', [])) if pid in by_id],
                                        data.get('roster_positions', []), bench_size) for r in rosters}
    slot_rows = []
    for label, (name, value) in (per.get(mine, ({}, None))[0] or {}).items():
        others = [v[label][1] for v in (x[0] for x in per.values()) if label in v]
        slot_rows.append(SlotStrength(slot=label, player_name=name, value=value, teams=len(others),
                                      rank=1 + sum(o > value for o in others)))
    benches = [b for _, b in per.values() if b is not None]
    if per.get(mine, ({}, None))[1] is not None:
        mine_bench = per[mine][1]
        slot_rows.append(SlotStrength(slot='BENCH', value=mine_bench, teams=len(benches), rank=1 + sum(b > mine_bench for b in benches)))
    starters_total = {rid: sum(v for _, v in slots_.values()) for rid, (slots_, _) in per.items() if slots_}
    best = max(starters_total.values(), default=0) or 1
    names = {r['roster_id']: r.get('name') for r in rosters}
    ordered = sorted(starters_total.items(), key=lambda kv: -kv[1])
    rankings = [TeamRanking(roster_id=str(rid), name=names.get(rid), is_mine=rid == mine, score=round(100 * v / best, 1), rank=i)
                for i, (rid, v) in enumerate(ordered, 1)]
    return StrengthView(status='research', overall_rank=overall, teams=len(totals), positions=out,
                        slots=slot_rows, team_rankings=rankings)


WAIVER_TYPES = {0: 'rolling', 1: 'reverse_standings', 2: 'faab'}


def resolve_without(data: dict, mine: dict, protected: dict) -> dict | None:
    """Waiver guidance re-solved with IR/taxi players out of your roster (unavailable while held there,
    and never a drop). Same function the background snapshot uses; only its input changes."""
    from src.services.waiver_guidance import guidance
    owned = {str(pid) for r in data.get('rosters', []) for pid in r.get('player_ids', [])}
    ids = [str(pid) for pid in mine.get('player_ids', []) if str(pid) not in protected]
    result = guidance(data.get('players', []), ids, owned, data.get('roster_positions', []))
    return result if result.get('status') == 'research' else None


def engine_waiver_context(data: dict, by_id: dict) -> EngineWaivers:
    """Present background waiver guidance (src/services/waiver_guidance.py); no computation here.

    Every row is revalidated against this checkpoint's ownership: the add must
    be unrostered and the drop on your roster, or the row is skipped.
    """
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    if len(mine) != 1:
        return EngineWaivers(status='owner_roster_unresolved')
    view = _engine_waivers(data, by_id, mine)
    view.protected = [player_detail(by_id[pid]) for pid in sorted(data.get('_protected') or {}) if pid in by_id]
    faab = data.get('_faab')
    if faab:
        from src.services.faab import bids
        shown = {(r.add.player_id, r.compare.player_id) for r in view.rows if r.add and r.compare}
        stored = [r for r in (data.get('waiver_guidance') or {}).get('rows', []) if (r.get('add_id'), r.get('drop_id')) in shown]
        view.faab = FaabPlan(**bids(stored, faab['money'], mine[0]['roster_id'], data.get('week'),
                                    playoff_start=faab.get('playoff_start'), history=faab.get('history')))
    trending = data.get('_trending') or {}
    owned_now = {str(pid) for r in data.get('rosters', []) for pid in r.get('player_ids', [])}
    for row in view.rows:
        row.trending_adds = trending.get(row.add.player_id)
        if row.trending_adds:
            row.reasons.append(f'Trending on Sleeper: {row.trending_adds:,} adds in the last 24 hours (crowd signal, not value).')
    view.trending = [TrendingAdd(player=player_detail(by_id[pid]), adds=n) for pid, n in
                     sorted(trending.items(), key=lambda kv: -kv[1])
                     if pid in by_id and pid not in owned_now and by_id[pid].get('roster_ids') == []][:8]
    return view


def _engine_waivers(data: dict, by_id: dict, mine: list) -> EngineWaivers:
    settings = data.get('waiver_settings') or {}
    context = dict(waiver_type=WAIVER_TYPES.get(settings.get('waiver_type'), 'unknown'),
                   waiver_position=mine[0].get('waiver_position'), teams=len(data.get('rosters', [])) or None,
                   waiver_clear_days=settings.get('waiver_clear_days'))
    stored = data.get('waiver_guidance') or {}
    context.update(horizon_weeks=stored.get('horizon_weeks',2),thresholds=stored.get('thresholds',{}),
        coverage_blockers=[{**b,'missing_players':[{'name':by_id.get(pid,{}).get('name',pid),
            'position':by_id.get(pid,{}).get('position')} for pid in b.get('missing_player_ids',[])]}
            for b in stored.get('coverage_blockers',[])],
        tier_rule='Conditional 2–4 week lineup comparisons; minimum gains apply. Each row is an alternative, with claim timing requiring platform confirmation.')
    if stored.get('status') not in ('research','incomplete_coverage'):
        return EngineWaivers(status=stored.get('status', 'unavailable'), **context)
    protected = data.get('_protected') or {}
    # The producer excludes reserve/taxi players. Revalidate ownership here,
    # but never invoke the optimizer while serving a request.
    owned = {str(pid) for r in data.get('rosters', []) for pid in r.get('player_ids', [])}
    my_ids = set(map(str, mine[0].get('player_ids', []))) - set(protected)
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
            weekly=row.get('weekly',[]),needed_by_week=row.get('needed_by_week'),
            target_game_kickoff=row.get('target_game_kickoff'),claim_timing=row.get('claim_timing'),
            alternative_drops=[{**r,'name':by_id.get(r['drop_id'],{}).get('name',r['drop_id'])}
                for r in row.get('alternative_drops',[]) if r['drop_id'] in my_ids],
            tier='priority' if gain >= 15 else 'consider' if gain >= 5 else 'depth'))
    if not rows:
        return EngineWaivers(status=stored['status'] if stored['status']=='incomplete_coverage' else 'no_positive_research_moves', **context)
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
    protected = data.get('_protected') or {}
    for move in stored.get('moves', []):
        add_id, drop_id = str(move.get('add_id')), str(move.get('drop_id'))
        if drop_id in protected:
            # An equally good drop that is not on IR/taxi replaces it; otherwise the move is withheld.
            swap = next((pid for pid in sorted(map(str, move.get('equivalent_drop_ids', [])))
                         if pid not in protected and pid != drop_id), None)
            if swap is None:
                view.excluded_moves += 1
                continue
            move = {**move, 'drop_id': swap, 'equivalent_drop_ids': [x for x in move.get('equivalent_drop_ids', []) if str(x) != swap]}
            drop_id = swap
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
                if (pid != drop_id and pid in ids and pid not in starters and pid not in protected and alternative
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


async def season_accuracy(db, league_id: str, data: dict) -> list[AccuracyWeek]:
    """Start/sit accuracy for each completed week: recorded points / hindsight-optimal points."""
    from src.models.sleeper import SleeperLeagueSnapshot
    mine = [r['roster_id'] for r in data.get('rosters', []) if r.get('is_mine') is True]
    week = data.get('week')
    if len(mine) != 1 or not week:
        return []
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    rows = (await db.scalars(select(SleeperLeagueSnapshot).where(
        SleeperLeagueSnapshot.league_id == league_id, SleeperLeagueSnapshot.kind == 'matchups',
        SleeperLeagueSnapshot.week < week, SleeperLeagueSnapshot.week >= 1).order_by(SleeperLeagueSnapshot.week))).all()
    out = []
    for snap in rows:
        row = next((r for r in snap.payload if isinstance(r, dict) and r.get('roster_id') == mine[0]), None) if isinstance(snap.payload, list) else None
        actual = finite_points((row or {}).get('points'))
        best, _ = hindsight(row, by_id, data.get('roster_positions', [])) if row else (None, [])
        if actual is not None and best:
            out.append(AccuracyWeek(week=snap.week, actual=round(actual, 2), optimal=round(best, 2), accuracy=round(min(1.0, actual / best), 4)))
    return out


async def attach_faab(db: AsyncSession, league, data: dict | None) -> None:
    """data['_faab'] for leagues that bid: budgets from the latest roster sync, this league's past winning bids."""
    from src.services.faab import budgets, history_share
    if not data or league is None or league.platform != 'sleeper':
        return
    from src.models.sleeper import SleeperLeagueSnapshot, SleeperRoster
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league.league_id))).all()
    money = budgets(league.settings or {}, [{'roster_id': r.roster_id, 'settings': r.settings} for r in rosters])
    if money is None:
        return
    transactions = [t for payload in (await db.scalars(select(SleeperLeagueSnapshot.payload).where(
        SleeperLeagueSnapshot.league_id == league.league_id, SleeperLeagueSnapshot.kind == 'transactions'))).all()
        if isinstance(payload, list) for t in payload]
    data['_faab'] = {'money': money, 'history': history_share(transactions, money['budget']),
                     'playoff_start': (league.settings or {}).get('playoff_week_start')}


async def attach_protected(db: AsyncSession, league_id: str, data: dict | None) -> None:
    """data['_protected'] = {player_id: 'IR' | 'Taxi'} for your roster, from the latest platform sync."""
    if not data:
        return
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    if len(mine) != 1:
        return
    from src.models.sleeper import SleeperRoster
    row = await db.get(SleeperRoster, (league_id, mine[0]['roster_id']))
    if row is None:
        return
    protected = {**{str(p): 'Taxi' for p in row.taxi or []}, **{str(p): 'IR' for p in row.reserve or []}}
    data['_protected'] = protected
    for p in data.get('players', []):
        if str(p.get('player_id')) in protected:
            p['_reserve_slot'] = protected[str(p['player_id'])]


@router.get('/leagues/{league_id}/overview', response_model=Overview)
async def league_overview(league_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    if league.sport != 'nfl':
        return Overview(league_id=league_id, status='unsupported',
                        message='The replacement fantasy workspace currently supports NFL leagues.')
    data = await read(db, league_id)
    await attach_espn(db, league, data)
    await attach_protected(db, league_id, data)
    await attach_faab(db, league, data)
    from src.services import availability_rates
    await availability_rates.attach(db, getattr(league, 'platform', 'sleeper'), data)
    if data:
        from src.services import schedule_strength
        sos = (await schedule_strength.latest(db) or {}).get('teams', {})
        for p in data.get('players', []):
            row = (sos.get(str(p.get('nfl_team_id'))) or {}).get(p.get('position'))
            if row:
                p['_sos'] = row
    if data and league.platform == 'sleeper':
        from src.services import sleeper_trending
        data['_trending'] = (await sleeper_trending.latest(db) or {}).get('players', {})
    result = overview(league_id, data)
    if result.status=='snapshot_available':
        from src.services.fantasy_late_swap import plans
        result.late_swap=LateSwapView(**plans([p.model_dump() for p in result.roster_players],
            [p.model_dump() for p in result.matchup.mine.starters] if result.matchup.mine else []))
    if result.status == 'snapshot_available':
        result.season_accuracy = await season_accuracy(db, league_id, data)
    from asyncio import to_thread
    from config.settings import get_settings
    from src.services.fantasy_research_status import latest
    if result.status == 'snapshot_available':
        result.research = FantasyResearch(**await to_thread(latest,
            get_settings().raw_archive_dir, league_id, league.season))
    if result.status == 'updating':
        response.headers['Retry-After'] = '30'
    return result


@router.get('/leagues/{league_id}/view',response_model=Overview,response_model_exclude_unset=True)
async def league_view(league_id:str,response:Response,
    tool:Literal['today','overview','team','startsit','waivers','players','player','trade','league','recap','journal']='overview',
    player:str|None=None,compare:str|None=None,horizon:int=2,db:AsyncSession=Depends(get_db)):
    if horizon not in (2,3,4):raise HTTPException(422,'Choose a 2–4 week horizon')
    result=await league_overview(league_id,response,db)
    selected=[p for p in (player,compare) if p]
    if any(len(p)>100 for p in selected):raise HTTPException(422,'Player ID too long')
    if tool=='waivers' and horizon!=2 and result.status=='snapshot_available':
        data=await read(db,league_id)
        if data:
            await attach_protected(db,league_id,data)
            await attach_faab(db,await db.get(SleeperLeague,league_id),data)
            data['waiver_guidance']=data.get('waiver_guidance_by_horizon',{}).get(str(horizon),{})
            result.engine_waivers=engine_waiver_context(data,{str(p['player_id']):p for p in data.get('players',[])})
    if tool=='player' and selected and result.status=='snapshot_available':
        from src.services.player_identity import resolve_platform_players
        from src.services.role_change_profiles import profile
        league=await db.get(SleeperLeague,league_id)
        identities=await resolve_platform_players(db,league.platform,set(selected))
        for p in result.comparison_players:
            identity=identities.get(p.player_id)
            if p.player_id in selected and identity:
                p.role_changes=RoleProfile(**await profile(db,identity.id,season=int(league.season)))
    from src.services.workspace_view_response import trim
    return trim(result,tool,selected)


@router.get('/leagues/{league_id}/players/{player_id}',response_model=PlayerDetail)
async def detailed_player(league_id:str,player_id:str,response:Response,generated_at:str|None=None,db:AsyncSession=Depends(get_db)):
    if len(player_id)>100:raise HTTPException(422,'Player ID too long')
    result=await league_view(league_id,response,tool='player',player=player_id,db=db)
    players=result.get('comparison_players',[])
    if result.get('status')!='snapshot_available':raise HTTPException(409,'Current checkpoint unavailable; retry shortly')
    if generated_at is not None and generated_at!=result.get('generated_at'):
        raise HTTPException(409,'The league snapshot changed; refresh before comparing player evidence')
    if not players:raise HTTPException(404,'Player missing from current checkpoint')
    return PlayerDetail(**players[0])


class PairedSummary(BaseModel):
    n: int = 0
    weeks: list[int] = Field(default_factory=list)
    engine_mae: float | None = None
    sleeper_mae: float | None = None
    paired_difference: float | None = None
    ci: list[float] | None = None
    independent_weeks: int = 0


class QualificationWeek(PairedSummary):
    season: int | None = None
    week: int
    positions: dict[str, PairedSummary] = Field(default_factory=dict)


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
    evidence_type: str = 'prospective_report_unavailable'
    current_version: bool = False
    by_position: dict[str, PairedSummary] = Field(default_factory=dict)
    by_week: list[QualificationWeek] = Field(default_factory=list)


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
    from src.services.projection_engine_prospective import VARIANT_MIN_WEEKS, VARIANTS, variant_version

    def summary(raw):
        raw = raw or {}
        return PairedSummary(**{k: raw.get(k) for k in PairedSummary.model_fields if raw.get(k) is not None})

    tracks = []
    for variant, label in (('v1', 'Projection engine v1'), ('depth', 'Engine + depth chart/status'),
                           ('v2', 'Projection engine v2 (half of decisions)')):
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
        extra = [(f'{label} · Sleeper blend', (report.get('candidate_blend') or {}).get('promotion') or {}, report.get('candidate_blend') or {}),
                 ('ESPN projections', (report.get('espn') or {}).get('promotion') or {}, report.get('espn') or {}),
                 ('Consensus: Sleeper + ESPN + engine', (report.get('consensus') or {}).get('promotion') or {}, report.get('consensus') or {})
                 ] if variant == 'v1' else []
        for name, block, meta in ((label, report.get('promotion') or {}, report), *extra):
            if not meta and not block:
                continue  # older reports carry no ESPN/consensus grading yet
            reconstructed = 'Sleeper blend' in name
            current = report.get('version') == variant_version(variant)
            pool = summary(block.get('pool') or (meta.get('all_paired') if reconstructed else {}))
            independent = pool.independent_weeks or len(pool.weeks)
            blockers = list(block.get('blockers', []))
            eligible = bool(block.get('eligible_for_owner_review')) and current and not reconstructed
            if bool(block.get('eligible_for_owner_review')) and not current:
                blockers.append('report_does_not_match_current_version')
            if bool(block.get('eligible_for_owner_review')) and reconstructed:
                blockers.append('blend_weights_not_frozen_with_forecasts')
            tracks.append(QualificationTrack(name=name, status=report.get('status', 'unknown'),
                generated_at=report.get('generated_at'), version=report.get('version'),
                engine_forecasts=report.get('engine_forecasts') if meta is report else None, graded_weeks=independent,
                required_weeks=block.get('required_weeks', MIN_WEEKS), eligible_for_owner_review=eligible,
                blockers=blockers, pool=pool, statuses=report.get('statuses', {}) if meta is report else {},
                current_version=current,
                evidence_type='retrospective_reconstructed_current_weights' if reconstructed else ('immutable_pregame_forecasts_current_version' if current else 'historical_older_version'),
                by_position={p: summary(raw) for p, raw in (meta.get('by_position') or block.get('positions') or {}).items()},
                by_week=meta.get('by_week') or []))
    # Full pool (every projected player, box-score results): the FantasyPros pool, not only rostered players.
    files = sorted((root / 'pool' / 'reports').glob('*.json'))
    try:
        report = json.loads(files[-1].read_text()) if files else None
    except (OSError, ValueError):
        report = None
    for key, label in (('engine_v1', 'Projection engine v1'), ('espn', 'ESPN projections'),
                       ('consensus', 'Consensus: Sleeper + ESPN + engine')):
        name = f'Full pool · {label}'
        block = ((report or {}).get('tracks') or {}).get(key, {}).get('promotion')
        if not block:
            tracks.append(QualificationTrack(name=name, status='no_report_yet' if report is None else 'awaiting_results',
                                             required_weeks=VARIANT_MIN_WEEKS['v1']))
            continue
        pool = summary(block.get('pool'))
        current = report.get('engine_version') == variant_version('v1')
        meta = report.get('tracks', {}).get(key, {})
        tracks.append(QualificationTrack(name=name, status=report.get('status', 'unknown'), generated_at=report.get('generated_at'),
            version=report.get('engine_version'), graded_weeks=pool.independent_weeks or len(pool.weeks), required_weeks=block.get('required_weeks', 6),
            eligible_for_owner_review=bool(block.get('eligible_for_owner_review')) and current, blockers=block.get('blockers', []) + (['report_does_not_match_current_version'] if block.get('eligible_for_owner_review') and not current else []),
            pool=pool, statuses=report.get('statuses', {}), current_version=current,
            evidence_type='immutable_pregame_forecasts_current_version' if current else 'historical_older_version',
            by_position={p: summary(raw) for p, raw in (meta.get('by_position') or block.get('positions') or {}).items()},
            by_week=meta.get('by_week') or []))
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


class TradeIdea(BaseModel):
    give: PlayerDetail
    get: PlayerDetail
    partner: str | None = None
    my_gain: float
    their_gain: float
    weeks: int
    give_market_value: float | None = None
    get_market_value: float | None = None


class TradeIdeas(BaseModel):
    status: str
    generated_at: datetime | None = None
    mutual_trades: int = 0
    rows: list[TradeIdea] = Field(default_factory=list)
    market_status: str = 'unavailable'
    note: str = ('One-for-one trades where both starting lineups gain points over the remaining weeks (engine '
                 'research; byes count as zero). Market values are FantasyCalc trade-index values. Nothing is '
                 'proposed for you; check injuries and league rules before offering.')


@router.get('/leagues/{league_id}/trade-ideas', response_model=TradeIdeas)
async def trade_ideas(league_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    from src.services.workspace_background import cached
    response.headers['Cache-Control']='no-store'
    league=await db.get(SleeperLeague,league_id)
    if league is None:raise HTTPException(404,'League not found')
    data=await read(db,league_id)
    summary=await cached(db,league_id,'trade-ideas',data)
    return TradeIdeas(**summary) if summary is not None else TradeIdeas(status='updating')


async def compute_trade_ideas(league_id,db,data):
    from src.services import trade_finder
    from src.services.fantasy_market import cohort, selected
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    if data is None:
        return TradeIdeas(status='updating')
    await attach_protected(db, league_id, data)
    raw = trade_finder.find(data)
    if raw['status'] != 'research':
        return TradeIdeas(status=raw['status'], generated_at=data['read_model']['generated_at'])
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    names = {r['roster_id']: r.get('name') for r in data.get('rosters', [])}
    ids = sorted({x for r in raw['rows'] for x in (r['give_id'], r['get_id'])})[:12]
    market = selected(cohort(league, len(data.get('rosters', []))), league.platform, ids)
    values = {m['player_id']: finite_points(m.get('value')) for m in market.get('players', [])}
    rows = [TradeIdea(give=player_detail(by_id[r['give_id']]), get=player_detail(by_id[r['get_id']]),
                      partner=names.get(r['partner_roster_id']), my_gain=r['my_gain'], their_gain=r['their_gain'],
                      weeks=r['weeks'], give_market_value=values.get(r['give_id']), get_market_value=values.get(r['get_id']))
            for r in raw['rows']]
    return TradeIdeas(status='research', generated_at=data['read_model']['generated_at'],
                      mutual_trades=raw['mutual_trades'], rows=rows, market_status=market.get('status', 'unavailable'))


class StandingRow(BaseModel):
    roster_id: str
    name: str | None = None
    is_mine: bool = False
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    playoff_odds: float | None = None
    first_seed_odds: float | None = None
    projected_wins: float | None = None


class StandingsView(BaseModel):
    status: str
    week: int | None = None
    playoff_teams: int | None = None
    remaining_games: int = 0
    simulations: int = 0
    rows: list[StandingRow] = Field(default_factory=list)
    note: str = ('Standings from completed weeks. Odds simulate the remaining schedule 10,000 times: each team scores '
                 'around its points per game, scaled each week by its projected starting lineup (byes dip); seeds by '
                 'wins then points for. No divisions or league-specific tiebreakers. Research.')


@router.get('/leagues/{league_id}/standings', response_model=StandingsView)
async def league_standings(league_id: str, response: Response, db: AsyncSession = Depends(get_db)):
    from src.services.workspace_background import cached
    response.headers['Cache-Control']='no-store'
    league=await db.get(SleeperLeague,league_id)
    if league is None:raise HTTPException(404,'League not found')
    data=await read(db,league_id)
    summary=await cached(db,league_id,'standings',data)
    return StandingsView(**summary) if summary is not None else StandingsView(status='updating')


async def compute_standings(league_id,db,data):
    from src.models.sleeper import SleeperLeagueSnapshot
    from src.services import season_sim
    from src.services.fantasy_decision_models import FLEX, RESERVE
    from src.services.waiver_guidance import OFFENSE, lineup_total
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    if data is None or not data.get('week'):
        return StandingsView(status='updating')
    week = int(data['week'])
    snaps = (await db.scalars(select(SleeperLeagueSnapshot).where(
        SleeperLeagueSnapshot.league_id == league_id, SleeperLeagueSnapshot.kind.in_(('matchups', 'schedule')),
        SleeperLeagueSnapshot.week >= 1))).all()
    results, remaining = [], {}
    for snap in snaps:
        rows = snap.payload if isinstance(snap.payload, list) else []
        if snap.kind == 'matchups' and snap.week < week:
            results += [{'week': snap.week, 'roster_id': r['roster_id'], 'matchup_id': r['matchup_id'],
                         'points': finite_points(r.get('points'))} for r in rows if r.get('matchup_id') is not None]
        elif (snap.kind == 'matchups' and snap.week == week) or (snap.kind == 'schedule' and snap.week > week):
            for r in rows:
                if r.get('matchup_id') is not None:
                    remaining.setdefault((snap.week, r['matchup_id']), set()).add(r['roster_id'])
    games = sorted((w, *sorted(teams)) for (w, _), teams in remaining.items() if len(teams) == 2)
    table = season_sim.standings(results)
    if not table:
        return StandingsView(status='partial_completed_history' if results else 'no_completed_weeks', week=week)
    completed = season_sim.completed_results(results)
    expected_teams = {r['roster_id'] for r in data.get('rosters', [])}
    history_complete = (len(completed) == len(results) and set(table) == expected_teams and
                        all(t['games'] == week - 1 for t in table.values()))
    playoff_teams = int((league.settings or {}).get('playoff_teams') or
                        ((league.raw or {}).get('settings', {}).get('scheduleSettings', {}) or {}).get('playoffTeamCount') or 6)
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    slots = [s for s in data.get('roster_positions', []) if s not in RESERVE and FLEX.get(s, {s}) <= OFFENSE]
    weeks = sorted({g[0] for g in games})
    lineups = {}
    for r in data.get('rosters', []):
        members = [by_id[pid] for pid in map(str, r.get('player_ids', [])) if pid in by_id and (by_id[pid].get('position') in OFFENSE or not by_id[pid].get('position'))]
        for w in weeks:
            total = lineup_total(members, slots, w) if slots else None
            lineups[(r['roster_id'], w)] = total or None
    strength = season_sim.weekly_strength(table, weeks, lineups)
    scores = [r['points'] for r in completed]
    sd = max(season_sim.MIN_SD, float(__import__('numpy').std(scores))) if len(scores) > 4 else 25.0
    odds = season_sim.simulate(table, games, strength, playoff_teams, sd=sd) if games and history_complete else {}
    names = {r['roster_id']: r.get('name') for r in data.get('rosters', [])}
    mine = {r['roster_id'] for r in data.get('rosters', []) if r.get('is_mine') is True}
    rows = [StandingRow(roster_id=str(t), name=names.get(t), is_mine=t in mine, wins=v['wins'], losses=v['losses'],
                        ties=v['ties'], points_for=round(v['pf'], 2), points_against=round(v['pa'], 2),
                        **(odds.get(t) or {})) for t, v in table.items()]
    rows.sort(key=lambda r: (-(r.wins + 0.5 * r.ties), -r.points_for))
    return StandingsView(status='research' if history_complete else 'partial_completed_history', week=week,
                         playoff_teams=playoff_teams, remaining_games=len(games),
                         simulations=season_sim.SIMS if games and history_complete else 0, rows=rows,
                         **({} if history_complete else {'note': 'Standings include complete paired outcomes only. Missing completed results withhold playoff probabilities.'}))


class RecapGame(BaseModel):
    home: str | None = None
    away: str | None = None
    home_points: float
    away_points: float


class RecapWeek(BaseModel):
    week: int
    points: float
    opponent: str | None = None
    opponent_points: float | None = None
    result: Literal['W', 'L', 'T'] | None = None
    league_median: float
    score_rank: int
    teams: int
    all_play_wins: int
    all_play_losses: int
    top_scorer: str | None = None
    top_scorer_points: float | None = None
    best_bench: str | None = None
    best_bench_points: float | None = None
    bench_points_left: float | None = None
    high_score: RecapGame | None = None
    closest_game: RecapGame | None = None
    biggest_blowout: RecapGame | None = None
    low_team: str | None = None
    low_points: float | None = None


class RecapSeason(BaseModel):
    weeks: list[int] = Field(default_factory=list)
    my_points: list[float] = Field(default_factory=list)
    median_points: list[float] = Field(default_factory=list)
    all_play_wins: int = 0
    all_play_losses: int = 0
    wins: int = 0
    expected_wins: float | None = None
    luck: float | None = None


class Recap(BaseModel):
    status: str
    week: RecapWeek | None = None
    completed_weeks: list[int] = Field(default_factory=list)
    season: RecapSeason = Field(default_factory=RecapSeason)
    note: str = ('From the platform’s recorded matchup results. All-play: your score against every team that week. '
                 'Expected wins = all-play win rate x games; luck = actual minus expected.')


@router.get('/leagues/{league_id}/recap', response_model=Recap)
async def league_recap(league_id: str, response: Response, week: int | None = None, db: AsyncSession = Depends(get_db)):
    from statistics import median
    from src.models.sleeper import SleeperLeagueSnapshot
    response.headers['Cache-Control'] = 'no-store'
    league = await db.get(SleeperLeague, league_id)
    if league is None:
        raise HTTPException(404, 'League not found')
    data = await read(db, league_id)
    if data is None or not data.get('week'):
        return Recap(status='updating')
    current = int(data['week'])
    mine = [r['roster_id'] for r in data.get('rosters', []) if r.get('is_mine') is True]
    if len(mine) != 1:
        return Recap(status='owner_roster_unresolved')
    me = mine[0]
    names = {r['roster_id']: r.get('name') for r in data.get('rosters', [])}
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    snaps = {s.week: s.payload for s in (await db.scalars(select(SleeperLeagueSnapshot).where(
        SleeperLeagueSnapshot.league_id == league_id, SleeperLeagueSnapshot.kind == 'matchups',
        SleeperLeagueSnapshot.week >= 1, SleeperLeagueSnapshot.week < current))).all() if isinstance(s.payload, list)}
    completed = sorted(w for w, rows in snaps.items() if any(r.get('roster_id') == me for r in rows))
    if not completed:
        return Recap(status='no_completed_weeks')
    season = RecapSeason()
    games_played = 0
    for w in completed:
        rows = [r for r in snaps[w] if isinstance(r, dict) and r.get('points') is not None]
        scores = {r['roster_id']: float(r['points']) for r in rows}
        mine_pts = scores.get(me)
        if mine_pts is None:
            continue
        season.weeks.append(w)
        season.my_points.append(round(mine_pts, 2))
        season.median_points.append(round(median(scores.values()), 2))
        season.all_play_wins += sum(mine_pts > v for t, v in scores.items() if t != me)
        season.all_play_losses += sum(mine_pts < v for t, v in scores.items() if t != me)
        mine_row = next(r for r in rows if r['roster_id'] == me)
        opp = next((r for r in rows if r.get('matchup_id') == mine_row.get('matchup_id') and r['roster_id'] != me), None)
        if opp is not None and mine_row.get('matchup_id') is not None:
            games_played += 1
            season.wins += mine_pts > float(opp['points'])
    total_ap = season.all_play_wins + season.all_play_losses
    if total_ap and games_played:
        season.expected_wins = round(games_played * season.all_play_wins / total_ap, 2)
        season.luck = round(season.wins - season.expected_wins, 2)
    target = week if week in completed else completed[-1]
    rows = [r for r in snaps[target] if isinstance(r, dict) and r.get('points') is not None]
    scores = {r['roster_id']: float(r['points']) for r in rows}
    mine_row = next(r for r in rows if r['roster_id'] == me)
    opp = next((r for r in rows if r.get('matchup_id') == mine_row.get('matchup_id') and r['roster_id'] != me
                and mine_row.get('matchup_id') is not None), None)
    pairs = {}
    for r in rows:
        if r.get('matchup_id') is not None:
            pairs.setdefault(r['matchup_id'], []).append(r)
    games = [RecapGame(home=names.get(a['roster_id']), away=names.get(b['roster_id']), home_points=float(a['points']),
                       away_points=float(b['points'])) for a, b in (g for g in pairs.values() if len(g) == 2)]
    points = mine_row.get('players_points') or {}
    starters = [str(x) for x in mine_row.get('starters') or [] if x not in (None, '0', 0)]
    bench = [str(x) for x in mine_row.get('players') or [] if str(x) not in starters]
    def best(ids):
        scored = [(finite_points(points.get(pid)), pid) for pid in ids if finite_points(points.get(pid)) is not None]
        return max(scored, default=(None, None))
    top_pts, top_id = best(starters)
    bench_pts, bench_id = best(bench)
    optimal, _ = hindsight(mine_row, by_id, data.get('roster_positions', []))
    mine_pts = scores[me]
    low = min(scores.items(), key=lambda kv: kv[1])
    recap = RecapWeek(
        week=target, points=round(mine_pts, 2), opponent=names.get(opp['roster_id']) if opp else None,
        opponent_points=round(float(opp['points']), 2) if opp else None,
        result=None if opp is None else 'W' if mine_pts > float(opp['points']) else 'L' if mine_pts < float(opp['points']) else 'T',
        league_median=round(median(scores.values()), 2), score_rank=1 + sum(v > mine_pts for v in scores.values()), teams=len(scores),
        all_play_wins=sum(mine_pts > v for t, v in scores.items() if t != me),
        all_play_losses=sum(mine_pts < v for t, v in scores.items() if t != me),
        top_scorer=(by_id.get(top_id) or {}).get('name') if top_id else None, top_scorer_points=top_pts,
        best_bench=(by_id.get(bench_id) or {}).get('name') if bench_id else None, best_bench_points=bench_pts,
        bench_points_left=round(optimal - mine_pts, 2) if optimal else None,
        high_score=max(games, key=lambda g: max(g.home_points, g.away_points), default=None),
        closest_game=min(games, key=lambda g: abs(g.home_points - g.away_points), default=None),
        biggest_blowout=max(games, key=lambda g: abs(g.home_points - g.away_points), default=None),
        low_team=names.get(low[0]), low_points=round(low[1], 2))
    return Recap(status='available', week=recap, completed_weeks=completed, season=season)
