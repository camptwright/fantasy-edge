"""Restore verified evidence to a new directory, or import historical forecasts."""
import argparse
import asyncio
import json
from src.db.client import get_worker_db
from src.services.forecast_evidence import import_archives,restore,KINDS

async def run(args):
    async with get_worker_db() as db:
        if args.operation=='restore':
            report=await restore(db,args.directory,kind=args.kind)
        else:
            report=await import_archives(db,args.directory,limit=args.limit,kind=args.kind)
        print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['import','restore'])
    parser.add_argument('directory')
    parser.add_argument('--kind',choices=KINDS,default='forecasts')
    parser.add_argument('--limit',type=int,default=100)
    asyncio.run(run(parser.parse_args()))
