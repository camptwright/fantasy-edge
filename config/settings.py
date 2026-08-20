"""Central configuration. Everything comes from the environment via .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).parent
REPO_ROOT = CONFIG_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- database ----
    postgres_user: str = "fantasy"
    postgres_password: str = "changeme"
    postgres_db: str = "fantasy_edge"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # ---- redis ----
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # ---- providers ----
    odds_api_key: str = ""
    # Free tier is 500 requests/month. The guard in constraint #4 keys off this.
    odds_api_quota_floor: int = 50
    # All application LLM traffic goes through the shared LiteLLM gateway.
    # The gateway owns the routing order: gaming-PC Hermes/Ollama, Mac mini
    # Ollama, then the configured cloud provider. Keeping this boundary here
    # means the sports app never needs provider-specific credentials.
    litellm_base_url: str = ""
    litellm_api_key: str = ""
    fantasy_model_alias: str = "worker"
    discord_webhook_url: str = ""
    cfbd_api_key: str = ""

    # ---- polling cadence (seconds) ----
    poll_interval_in_season: int = 300
    poll_interval_off_season: int = 21600
    props_poll_interval: int = 300

    # ---- modelling ----
    model_dir: Path = Path("/mnt/data/fantasy-edge/models")
    kelly_fraction: float = 0.25  # quarter-Kelly
    log_level: str = "INFO"

    environment: str = Field(default="production")

    @property
    def database_url(self) -> str:
        """asyncpg DSN used by both the API pool and the Celery NullPool engine."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Alembic runs synchronously, so it needs a sync driver.

        The +psycopg suffix is required: a bare postgresql:// URL makes
        SQLAlchemy reach for psycopg2, which is not installed (psycopg3 is).
        """
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------- sports ----


@lru_cache
def _raw_sports_config() -> dict[str, Any]:
    with (CONFIG_DIR / "sports.yaml").open() as fh:
        return yaml.safe_load(fh)


@lru_cache
def get_sport_config(sport: str) -> dict[str, Any]:
    """Sport config with `defaults` merged underneath the per-sport block."""
    raw = _raw_sports_config()
    if sport not in raw["sports"]:
        raise KeyError(f"unknown sport: {sport}")
    merged = {**raw.get("defaults", {}), **raw["sports"][sport]}
    return merged


def all_sports() -> list[str]:
    return list(_raw_sports_config()["sports"].keys())


def is_in_season(sport: str, month: int) -> bool:
    """Constraint #4a: only poll sports whose current month is in season."""
    return month in get_sport_config(sport)["season_months"]


# --------------------------------------------------------- team aliases ----


@lru_cache
def get_team_aliases(sport: str) -> dict[str, dict[str, str]]:
    """Historical-loader team identifier -> {espn_name, espn_id} for this
    sport, or {} if no crosswalk file exists yet. See
    src/data/team_resolution.py for how this is used - an empty/missing
    entry means "treat the raw name as already canonical," which is
    correct for sports whose historical loader already emits ESPN-
    compatible full names (verified live for nba/wnba; not yet built for
    ncaaf given its much larger, more volatile roster of ~130 schools)."""
    path = CONFIG_DIR / "team_aliases" / f"{sport}.yaml"
    if not path.exists():
        return {}
    with path.open() as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("aliases", {})
