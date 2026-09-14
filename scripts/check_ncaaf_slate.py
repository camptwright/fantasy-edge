"""Read-only live ESPN-vs-database slate and served probability audit."""
import asyncio
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import json

import httpx
from sqlalchemy import select
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.api.routers.sportsbook import signal_rows, prop_rows
from src.ingest.identity import _aliases


async def main():
    async with get_worker_db() as db:
        games = (await db.scalars(select(Game).where(Game.sport == 'ncaaf'))).all()
        signals = await signal_rows(db, 'ncaaf')
        props = await prop_rows(db, 'ncaaf')
        known = {v['espn_id'] for v in _aliases('ncaaf').values()}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(get_settings().espn_base_urls['ncaaf']+'/scoreboard',
                params={'dates': '20260905-20260907', 'groups': '80', 'limit': 1000})
            response.raise_for_status()
            all_events = response.json().get('events', [])
            for day in ('2026-09-05', '2026-09-06'):
                local = [g for g in games if g.game_time and g.game_time.astimezone(ZoneInfo('America/Chicago')).date().isoformat() == day]
                events = [e for e in all_events if datetime.fromisoformat(e['date'].replace('Z', '+00:00')).astimezone(ZoneInfo('America/Chicago')).date().isoformat() == day]
                supported = [e for e in events if all(str(c['team']['id']) in known for c in e['competitions'][0]['competitors'])]
                live_ids = {e['id'] for e in events}
                local_ids = {g.espn_event_id for g in local}
                ids = {str(g.id) for g in local}
                p = [p for p in props if p.get('game_id') in ids]
                s = [s for s in signals if s.get('game_time') and datetime.fromisoformat(s['game_time']).astimezone(ZoneInfo('America/Chicago')).date().isoformat() == day]
                print(json.dumps({'day': day, 'db_games': len(local), 'espn_games': len(events),
                    'unsupported_matchups': len(events)-len(supported),
                    'missing_supported_games': [e['name'] for e in supported if e['id'] not in local_ids],
                    'db_only_ids': sorted(local_ids-live_ids), 'signals': len(s), 'signal_markets': dict(Counter(s['market'] for s in s)),
                    'linked_props': len(p), 'qualified_props': sum(p['model_probability'] is not None for p in p),
                    'prop_stats': dict(Counter(p['stat_type'] for p in p))}))


if __name__ == '__main__':
    asyncio.run(main())
