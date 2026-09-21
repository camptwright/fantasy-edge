from datetime import datetime,timedelta,timezone
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import pytest
from src.ingest.games import resolve_game,find_game_by_teams
from src.services.football_venue_coordinates import match


@pytest.mark.asyncio
async def test_distinct_external_game_ids_never_merge():
    now=datetime.now(timezone.utc)
    earlier=SimpleNamespace(game_time=now,mlb_game_pk='one',nhl_game_id=None,espn_event_id=None,nflverse_game_id=None)
    db=MagicMock();db.scalar=AsyncMock(return_value=None)
    result=MagicMock();result.scalars.return_value=[earlier];db.execute=AsyncMock(return_value=result)
    game=await resolve_game(db,home_team_id=uuid4(),away_team_id=uuid4(),kickoff=now+timedelta(hours=5),mlb_id='two')
    assert game is not earlier and game.mlb_game_pk=='two'


def test_secondary_venue_requires_exact_postal_identity():
    venue={'fullName':'Test Park','address':{'city':'Test City','zipCode':'12345'}}
    row={'stadium_name':'Test Park','city':'Test City','zipcode':'12345','lat':'40','lon':'-70','roof_type':'Outdoors'}
    assert match(venue,[row],2026)['roof']=='unknown'
    assert match(venue,[{**row,'zipcode':'54321'}],2026) is None
    assert match(venue,[{**row,'closed':'2025'}],2026) is None


@pytest.mark.asyncio
async def test_quote_matching_uses_nearest_game_and_rejects_ties():
    now=datetime.now(timezone.utc)
    earlier=SimpleNamespace(game_time=now-timedelta(hours=4))
    later=SimpleNamespace(game_time=now+timedelta(hours=1))
    db=MagicMock();result=MagicMock();result.scalars.return_value=[earlier,later]
    db.execute=AsyncMock(return_value=result)
    assert await find_game_by_teams(db,home_team_id=uuid4(),away_team_id=uuid4(),kickoff=now) is later
    later.game_time=now+timedelta(hours=4)
    assert await find_game_by_teams(db,home_team_id=uuid4(),away_team_id=uuid4(),kickoff=now) is None
