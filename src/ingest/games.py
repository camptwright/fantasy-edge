"""Single resolution layer for Game identity, mirroring resolve_team/resolve_player.

nflverse, ESPN, MLB Stats API, and the NHL API each find-or-create a Game
keyed on their own external id (nflverse_game_id / espn_event_id /
mlb_game_pk / nhl_game_id) with no reconciliation between them - this is
what stops that from creating two rows for one real fixture.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game

# Odds/props sources (The Odds API, Pinnacle, Bovada, ...) never create a
# Game row themselves - they have no season/week, which Game.season requires
# NOT NULL. They only need to find an existing fixture a schedule source
# (ESPN/nflverse) already created, by team pair + kickoff window.
_MATCH_WINDOW_SECONDS = 86400


async def resolve_game(
    db: AsyncSession,
    *,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    kickoff: datetime | None,
    nflverse_id: str | None = None,
    espn_id: str | None = None,
    mlb_id: str | None = None,
    nhl_id: str | None = None,
) -> Game:
    """Find the Game this fixture already has a row for, by whichever
    external id is provided, falling back to team-pair + kickoff-window
    matching so the OTHER source's id can be backfilled onto the same row
    rather than creating a second one.

    mlb_id/nhl_id don't participate in the nflverse_id/espn_id cross-
    backfill below: a different sport's teams never collide (resolve_team
    scopes by sport), so an MLB or NHL fixture can never legitimately match
    an NFL/NCAAF schedule source's id anyway - each only needs its own
    find-or-create path.
    """
    if mlb_id:
        existing = await db.scalar(select(Game).where(Game.mlb_game_pk == mlb_id))
        if existing is not None:
            return existing
    if nhl_id:
        existing = await db.scalar(select(Game).where(Game.nhl_game_id == nhl_id))
        if existing is not None:
            return existing
    if nflverse_id:
        existing = await db.scalar(select(Game).where(Game.nflverse_game_id == nflverse_id))
        if existing is not None:
            if espn_id and not existing.espn_event_id:
                existing.espn_event_id = espn_id
            return existing
    if espn_id:
        existing = await db.scalar(select(Game).where(Game.espn_event_id == espn_id))
        if existing is not None:
            if nflverse_id and not existing.nflverse_game_id:
                existing.nflverse_game_id = nflverse_id
            return existing

    # Neither external id matched. Try team-pair + kickoff window before
    # creating a new row - this is what lets nflverse's historically-seeded
    # row and ESPN's live-synced row for the SAME real game converge onto
    # one Game instead of two.
    if kickoff is not None:
        candidates = list(
            (
                await db.execute(
                    select(Game).where(
                        Game.home_team_id == home_team_id,
                        Game.away_team_id == away_team_id,
                    )
                )
            ).scalars()
        )
        for candidate in candidates:
            # Adjacent MLB series games/doubleheaders are different fixtures.
            # A time window may backfill a missing ID, never override a conflict.
            if any(incoming and stored and incoming != stored for incoming, stored in (
                (mlb_id,candidate.mlb_game_pk),(nhl_id,candidate.nhl_game_id),
                (espn_id,candidate.espn_event_id),(nflverse_id,candidate.nflverse_game_id))):
                continue
            if candidate.game_time is not None and abs(
                (candidate.game_time - kickoff).total_seconds()
            ) < 86400:
                if nflverse_id and not candidate.nflverse_game_id:
                    candidate.nflverse_game_id = nflverse_id
                if espn_id and not candidate.espn_event_id:
                    candidate.espn_event_id = espn_id
                if mlb_id and not candidate.mlb_game_pk:
                    candidate.mlb_game_pk = mlb_id
                if nhl_id and not candidate.nhl_game_id:
                    candidate.nhl_game_id = nhl_id
                return candidate

    # Deliberately NOT flushed here: `Game.season` is NOT NULL and this
    # brand-new row has no season yet - that's set by the caller
    # immediately afterward (both nflverse.py and espn.py already flush
    # once, after every field is assigned, exactly as they did before this
    # function existed). Flushing this bare row here would hit the same
    # premature-INSERT NOT NULL violation documented in both callers'
    # docstrings. SQLAlchemy's autoflush still sees this pending row for
    # any SELECT issued later in the same session (e.g. this function's own
    # team-pair candidate search on a later record), so nothing is lost by
    # deferring the flush to the caller.
    game = Game(
        nflverse_game_id=nflverse_id, espn_event_id=espn_id, mlb_game_pk=mlb_id, nhl_game_id=nhl_id
    )
    db.add(game)
    return game


async def find_game_by_teams(
    db: AsyncSession,
    *,
    home_team_id: uuid.UUID,
    away_team_id: uuid.UUID,
    kickoff: datetime | None,
) -> Game | None:
    """Find (never create) the Game a market/prop observation belongs to.

    Shared by every odds/props ingester that identifies a fixture by team
    pair + kickoff time rather than a source-specific game id (The Odds
    API, Pinnacle, Bovada). Originally theodds.py's own `_match_game`,
    extracted once Pinnacle and Bovada needed the identical logic - see
    CLAUDE.md constraint #2 (game_time is nullable) for why an untimed
    candidate is only trusted when it is the SOLE candidate.
    """
    candidates = list(
        (
            await db.execute(
                select(Game).where(
                    Game.home_team_id == home_team_id, Game.away_team_id == away_team_id
                )
            )
        ).scalars()
    )
    if not candidates:
        return None
    if kickoff is not None:
        timed = [
            game
            for game in candidates
            if game.game_time is not None
            and abs((game.game_time - kickoff).total_seconds()) < _MATCH_WINDOW_SECONDS
        ]
        if timed:
            timed.sort(key=lambda game:abs((game.game_time-kickoff).total_seconds()))
            if len(timed)>1 and abs((timed[0].game_time-kickoff).total_seconds())==abs((timed[1].game_time-kickoff).total_seconds()):
                return None
            return timed[0]
    # No timed candidate matched (or no kickoff was given at all). Only
    # trust an unconditional single match when its game_time is unknown -
    # a known, mismatched kickoff almost certainly means a different
    # season's fixture for the same recurring team pair (division rivals),
    # and attaching current odds to it would silently corrupt that game's
    # line history.
    untimed = [game for game in candidates if game.game_time is None]
    return untimed[0] if len(untimed) == 1 else None
