"""Timestamped headline evidence for research snapshots, never live pricing.

RSS headlines are not structured injury or lineup confirmations. They are kept
as immutable context only when a normalized player name appears in the title.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.utils.normalize import normalize_player_name


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def headlines_for_players(archive_dir: Path, players: dict[str, str], as_of: datetime) -> dict[str, list[dict]]:
    """Return bounded pre-capture title evidence, deduplicated by URL/title.

    `observed_at`, rather than an untrusted publisher-date string, is the
    availability timestamp. This prevents a post-capture fetched headline
    from leaking into a pregame snapshot.
    """
    names = {pid: normalize_player_name(name) for pid, name in players.items() if normalize_player_name(name)}
    result = {pid: [] for pid in names}
    seen = set()
    for path in sorted(archive_dir.glob('*.json'), reverse=True)[:48]:
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(payload, list):
            continue
        for row in payload:
            if not isinstance(row, dict):
                continue
            observed = _timestamp(row.get('observed_at'))
            title, url = row.get('title'), row.get('url')
            if observed is None or observed > as_of or not isinstance(title, str) or not isinstance(url, str):
                continue
            key = (title.strip(), url.strip())
            if key in seen:
                continue
            seen.add(key)
            normalized = normalize_player_name(title)
            for player_id, name in names.items():
                if name in normalized and len(result[player_id]) < 5:
                    result[player_id].append({'title': title.strip(), 'url': url.strip(),
                                              'source': str(row.get('source') or ''),
                                              'observed_at': observed.isoformat()})
    return result
