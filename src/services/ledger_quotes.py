"""Resolve immutable quote IDs server-side; never parse a selection label."""
from uuid import UUID
from fastapi import HTTPException
from src.models.facts import Game, PlayerPropLine, TeamMarketLine
from src.models.identity import Player, Team
from src.services.quote_eligibility import availability, exclusion


async def resolve_quote(db, kind, quote_id, side):
    cls = PlayerPropLine if kind == 'player' else TeamMarketLine
    quote = await db.get(cls, quote_id)
    if not quote:
        raise HTTPException(404, 'Quote not found')
    if kind == 'player' and side not in ('over', 'under'):
        raise HTTPException(422, 'Invalid player side')
    if kind == 'team' and side != quote.side:
        raise HTTPException(422, 'Side does not match quote')
    game = await db.get(Game, quote.game_id) if quote.game_id else None
    if not game:
        raise HTTPException(422, 'Quote has no exact game binding')
    price = getattr(quote, side + '_price_american') if kind == 'player' else quote.price_american
    if price is None or abs(price) < 100:
        raise HTTPException(422, 'Quote has no usable price')
    seen = await availability(db, 'prop' if kind == 'player' else 'team', [quote.id])
    reason = exclusion(game, quote, seen.get(quote.id))
    home = await db.get(Team, game.home_team_id) if game.home_team_id else None
    away = await db.get(Team, game.away_team_id) if game.away_team_id else None
    player = await db.get(Player, quote.player_id) if kind == 'player' else None
    terms = dict(game_id=str(game.id), kind=kind, player_id=str(quote.player_id) if kind == 'player' else None,
        market=quote.stat_type if kind == 'player' else quote.market, side=side, line=quote.line,
        price_american=price, book=quote.source, quote_id=str(quote.id))
    return {'terms': terms, 'observed_at': quote.observed_at.isoformat(),
            'game_time': game.game_time.isoformat() if game.game_time else None,
            'label': f'{away.name if away else "Away"} @ {home.name if home else "Home"}',
            'player': player.full_name if player else None,
            'availability': reason or 'current_pregame_offer',
            'notice': 'This copies an observed offer, not a placed wager. Confirm actual receipt terms.'}
