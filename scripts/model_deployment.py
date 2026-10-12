"""Explicit promotion or unconditional rollback to retained NFL baseline."""
import argparse,asyncio,json
from src.db.client import get_worker_db
from src.services.model_deployment import select_model

async def run(args):
    if args.action=='promote':
        from src.services.nfl_lab_registry import execute
        async with get_worker_db() as db:await execute(db)
        if not args.version:raise ValueError('--version is required for promotion')
    async with get_worker_db() as db:
        print(json.dumps(await select_model(db,args.version if args.action=='promote' else None,
            actor=args.actor,reason=args.reason)))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['promote','rollback'])
    p.add_argument('--version');p.add_argument('--actor',required=True);p.add_argument('--reason',required=True)
    asyncio.run(run(p.parse_args()))
