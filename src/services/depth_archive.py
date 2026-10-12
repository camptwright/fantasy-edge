"""Daily point-in-time archive of Sleeper depth-chart and roster status.

Sleeper publishes only the current depth chart, so the projection depth
variant (projection_depth.py) can be validated only prospectively. One
create-only file per UTC day under raw/sleeper-depth-status/ records what
the catalog said that day; the first fetch of the day wins.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from config.settings import get_settings
from src.services.roster_stat_prospective import publish

FIELDS = ("team", "position", "status", "injury_status", "active",
          "depth_chart_position", "depth_chart_order", "gsis_id", "espn_id")


def snapshot(catalog: dict, observed_at: datetime) -> dict:
    players = {pid: {k: info.get(k) for k in FIELDS} for pid, info in catalog.items()
               if isinstance(info, dict) and info.get("position") in ("QB", "RB", "WR", "TE")}
    return {"source": "sleeper_players_nfl", "observed_at": observed_at.isoformat(), "players": players}


def archive_daily(catalog: dict, observed_at: datetime, root: Path | None = None) -> bool:
    root = Path(root or get_settings().raw_archive_dir) / "sleeper-depth-status"
    return publish(root / f"{observed_at.strftime('%Y%m%d')}.json", snapshot(catalog, observed_at))
