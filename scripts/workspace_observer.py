"""Dedicated diagnostics loop; never starts ingestion or evaluation."""
import asyncio
import json
import sys
import time

from src.services.runtime_history import collect


def once():
    try:
        print(json.dumps(asyncio.run(collect())), flush=True)
        return True
    except Exception:
        # Do not log driver errors which can contain connection credentials.
        print(json.dumps({'status': 'observation_failed'}), flush=True)
        return False


if __name__ == '__main__':
    if '--once' in sys.argv:
        raise SystemExit(0 if once() else 1)
    while True:
        once()
        time.sleep(300)
