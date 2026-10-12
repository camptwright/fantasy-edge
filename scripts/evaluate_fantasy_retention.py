"""Capture available multiweek scenarios and grade immutable prior captures."""
import asyncio
import json
from src.services.retention_pipeline import execute

if __name__ == '__main__':
    print(json.dumps(asyncio.run(execute()), indent=2))
