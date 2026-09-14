"""Manual research capture; does not place wagers or modify serving forecasts."""
import asyncio
import json
from src.db.client import get_worker_db
from src.scheduler.calibration import archive
from src.services.period_shadow_capture import capture


async def run():
    async with get_worker_db() as db:
        payload = await capture(db)
    print(json.dumps({'archive': archive('period-shadow-forecasts', payload),
                      'status': payload['status'], 'records': len(payload['records'])}))


if __name__ == '__main__':
    asyncio.run(run())
