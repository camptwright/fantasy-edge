from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.services.quote_eligibility import confirm_quote
from types import SimpleNamespace
import pytest

from src.services import serving_calibration as serving
from src.services.elo import moneyline_probability
from src.services.forecast_capture import model_digest
from src.api.routers.sportsbook import signal_rows
from src.ingest.identity import resolve_team
from src.models.facts import Game, TeamMarketLine
from src.models.ratings import TeamRating


def test_override_scope_and_rollback(monkeypatch):
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(ncaaf_moneyline_calibration_enabled=True))
    assert serving.calibrate_home_probability(.6, 'ncaaf', 'moneyline') == pytest.approx(.63667, abs=.0001)
    for sport, market in [('nfl', 'moneyline'), ('ncaaf', 'spread'), ('ncaaf', 'total'), ('nba', 'moneyline')]:
        assert serving.calibrate_home_probability(.6, sport, market) == .6
    enabled_digest = model_digest()
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(ncaaf_moneyline_calibration_enabled=False))
    assert serving.calibrate_home_probability(.6, 'ncaaf', 'moneyline') == .6
    assert model_digest() != enabled_digest
    assert serving.deployment_status()['status'] == 'baseline'


async def test_served_pair_preserves_baseline_and_reprices_ev(db, monkeypatch):
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(ncaaf_moneyline_calibration_enabled=True))
    home = await resolve_team(db, 'Ohio State Buckeyes', sport='ncaaf')
    away = await resolve_team(db, 'Michigan Wolverines', sport='ncaaf')
    db.add_all([TeamRating(team_id=home.id, sport='ncaaf', rating=1600),
                TeamRating(team_id=away.id, sport='ncaaf', rating=1500)])
    game = Game(sport='ncaaf', season=2026, status='scheduled', home_team_id=home.id, away_team_id=away.id,
                game_time=datetime.now(timezone.utc)+timedelta(days=1))
    db.add(game)
    await db.flush()
    for side in ['home', 'away']:
        db.add(TeamMarketLine(game_id=game.id, source='test', market='moneyline', side=side,
            line_type='live', price_american=100, observed_at=datetime.now(timezone.utc)))
    await db.commit()
    for quote in (await db.scalars(select(TeamMarketLine))).all():
        await confirm_quote(db, 'team', quote)
    await db.commit()
    rows = await signal_rows(db, 'ncaaf')
    baseline = moneyline_probability(1600, 1500)
    p = serving.calibrate_home_probability(baseline, 'ncaaf', 'moneyline')
    h = next(r for r in rows if r['selection'].startswith('Ohio'))
    a = next(r for r in rows if r is not h)
    assert h['model_probability'] == round(p, 4)
    assert h['baseline_model_probability'] == round(baseline, 4)
    assert a['model_probability'] == round(1-p, 4)
    assert h['ev_percent'] == round((2*p-1)*100, 2)
    assert h['calibration_status'] == 'experimental_user_override'
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(ncaaf_moneyline_calibration_enabled=False))
    rolled = await signal_rows(db, 'ncaaf')
    assert all(r['model_probability'] == r['baseline_model_probability'] for r in rolled)
