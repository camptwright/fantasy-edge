"""Capture pregame specialist research and grade complete exact-rule horizons."""
import asyncio
import json
from src.services.fantasy_specialist_prospective import execute

if __name__=='__main__':
    print(json.dumps(asyncio.run(execute())))
