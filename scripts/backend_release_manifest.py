"""Seal or verify backend release content without reading env files."""
import argparse
import json
import sys
from pathlib import Path

# Permit direct invocation during Docker build, without an installed source tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.release_manifest import build, status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('seal', 'verify'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.mode == 'seal':
        manifest = build(args.root)
        (args.root / 'release-manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        print(json.dumps({'status': 'sealed', 'release_id': manifest['release_id']}))
        return 0
    report = status(args.root)
    print(json.dumps(report, sort_keys=True))
    return int(report['status'] != 'matched')


if __name__ == '__main__':
    raise SystemExit(main())
