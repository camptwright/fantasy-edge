"""Application settings.

CONSTRAINT #14: Alembic runs synchronously and cannot use asyncpg. A bare
postgresql:// URL makes SQLAlchemy reach for psycopg2, which is not a
dependency, and `alembic upgrade head` dies with ModuleNotFoundError.
sync_database_url therefore forces psycopg3 explicitly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # User-authorized experimental override, 2026-09-05. False restores Elo.
    ncaaf_moneyline_calibration_enabled: bool = True
    ncaaf_spread_calibration_enabled: bool = True
    ncaaf_prop_calibration_enabled: bool = True

    postgres_user: str = "fantasy"
    postgres_password: str = "changeme"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "fantasy_edge"

    redis_url: str = "redis://redis:6379/0"

    # Sports supported end-to-end (ingestion, API, scheduler). NCAAF has no
    # Sleeper product at all, so Sleeper sync stays scoped to whichever of
    # these sports Sleeper itself actually supports (NFL, NBA, MLB, and NHL
    # as of the nhl addition - see src/ingest/sleeper.py) - not every entry
    # here implies a Sleeper integration.
    supported_sports: tuple[str, ...] = ("nfl", "ncaaf", "nba", "mlb", "nhl")

    espn_base_urls: dict[str, str] = {
        "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl",
        "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football",
        "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba",
    }
    # Subset of supported_sports whose schedule/scores come from ESPN
    # (src/scheduler/tasks.py's sync_espn loops this, not supported_sports
    # directly) - MLB and NHL deliberately excluded: each has its own
    # official API as its primary source (src/ingest/mlb.py,
    # src/ingest/nhl.py), which the free-source research rates well above
    # ESPN's undocumented scoreboard for reliability, so ESPN is not run
    # redundantly alongside either.
    espn_sports: tuple[str, ...] = ("nfl", "ncaaf", "nba")

    # statsapi.mlb.com - official, unauthenticated, no documented rate
    # limit. MLB's primary schedule/score source (see espn_sports above).
    mlb_stats_api_base_url: str = "https://statsapi.mlb.com/api/v1"
    # api-web.nhle.com - official, unauthenticated, no documented rate
    # limit. NHL's primary schedule/score source (see espn_sports above).
    nhl_api_base_url: str = "https://api-web.nhle.com/v1"

    odds_api_key: str = ""
    sportsgameodds_api_key: str = ""
    parlay_api_key: str = ""
    aggregate_props_enabled: bool = True
    # Conservative free-tier ceilings, independent of The Odds API quota.
    parlay_daily_credits: int = 24
    sportsgameodds_daily_objects: int = 60
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    # nba/mlb/nhl keys are The Odds API's documented sport keys, not
    # independently verified live like the scraped sources below (no
    # ODDS_API_KEY is configured in dev to test against) - taken from their
    # public API reference, which is a stable contract unlike an
    # undocumented endpoint.
    odds_api_sport_keys: dict[str, str] = {
        "nfl": "americanfootball_nfl",
        "ncaaf": "americanfootball_ncaaf",
        "nba": "basketball_nba",
        "mlb": "baseball_mlb",
        "nhl": "icehockey_nhl",
    }
    odds_api_quota_floor: int = 50
    odds_api_nfl_props_priority: bool = False
    odds_api_poll_seconds: dict[str, int] = {sport: 86400 for sport in ('nfl', 'ncaaf', 'nba', 'mlb', 'nhl')}
    odds_api_season_months: dict[str, list[int]] = {
        'nfl': [1, 2, 8, 9, 10, 11, 12], 'ncaaf': [1, 8, 9, 10, 11, 12],
        'mlb': list(range(3, 12)), 'nba': [1, 2, 3, 4, 5, 6, 10, 11, 12],
        'nhl': [1, 2, 3, 4, 5, 6, 10, 11, 12]}

    # guest.api.arcadia.pinnacle.com - the public site's own consumer API,
    # not Pinnacle's (now-closed-to-the-public, per its own docs since
    # 2025-07-23) official paid suite. This X-API-Key is a widely-known
    # guest/community key, not a real account secret - verified live
    # 2026-09-03. Override only if it ever rotates.
    pinnacle_api_key: str = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
    pinnacle_base_url: str = "https://guest.api.arcadia.pinnacle.com/0.1"
    # Sport -> Pinnacle league id. Verified live 2026-09-03 via
    # /0.1/sports/15/leagues (15 = Pinnacle's own "Football" sport id) for
    # nfl/ncaaf, 2026-09-04 via /0.1/sports/4/leagues (4 = "Basketball") for
    # nba, /0.1/sports/3/leagues (3 = "Baseball") for mlb, and
    # /0.1/sports/19/leagues (19 = "Hockey") for nhl. Only add an entry
    # here once it has actually been looked up live - guessing a
    # plausible-looking id is exactly the kind of unverified fact this
    # codebase's CLAUDE.md constraints warn against.
    pinnacle_league_ids: dict[str, int] = {
        "nfl": 889, "ncaaf": 880, "nba": 487, "mlb": 246, "nhl": 1456,
    }

    # www.bovada.lv's public coupon JSON - offshore book, no state
    # geofencing (unlike DraftKings/FanDuel/BetMGM, which are legal-state-
    # only and therefore unreachable from a non-legal-state IP - see
    # DEPLOYMENT.md's scraping notes).
    bovada_base_url: str = "https://www.bovada.lv/services/sports/event/coupon/events/A/description"
    bovada_sport_paths: dict[str, str] = {
        "nfl": "football/nfl", "ncaaf": "football/college-football",
        "nba": "basketball/nba", "mlb": "baseball/mlb", "nhl": "hockey/nhl",
    }

    prizepicks_base_url: str = "https://partner-api.prizepicks.com/projections"
    # PrizePicks league NAME (its own included[].attributes.name string,
    # e.g. "CFB" for college football - unrelated to Pinnacle's numeric
    # league/sport ids above, different provider's own scheme entirely) ->
    # our sport code. Mirrors underdog_api.py's _SPORT_ID_MAP shape/coverage
    # (verified live 2026-09-03 against a real /projections response) so a
    # later supported_sports addition (NBA/MLB/NHL) needs no code change
    # here, same as Underdog already doesn't.
    prizepicks_league_sports: dict[str, str] = {
        "NFL": "nfl", "CFB": "ncaaf", "NBA": "nba", "MLB": "mlb", "NHL": "nhl",
    }
    underdog_base_url: str = "https://api.underdogfantasy.com"
    sleeper_username: str = ""
    sleeper_base_url: str = "https://api.sleeper.app/v1"
    # Subset of supported_sports Sleeper actually has a fantasy product for
    # - NCAAF has none at all, so it's excluded even though it's a
    # supported_sports entry. Verified live 2026-09-04 that /state/{sport},
    # /players/{sport}, and /projections/{sport}/{season}/{week} all mirror
    # the /nfl shape sync_sleeper_account already used, for nba, mlb, and
    # nhl alike (mlb's and nhl's /projections responses were empty but
    # well-formed - not every sport publishes that feed, and the sync
    # already tolerates an empty snapshot rather than requiring one).
    sleeper_sports: tuple[str, ...] = ("nfl", "nba", "mlb", "nhl")
    # Optional licensed weekly fantasy-projection feed. This is deliberately
    # separate from Sleeper: the public Sleeper projection payload is often
    # empty before kickoff even while its consumer app shows preview values.
    fantasy_api_token: str = ""

    # Canary/anomaly alerting - the homelab's own self-hosted ntfy instance
    # (see the ntfy project's DEPLOYMENT.md), not ntfy.sh. Empty base URL or
    # topic means alerts are logged only, never sent - see src/utils/alerts.py.
    ntfy_base_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: str = ""

    # Raw HTTP response archive for direct-to-source scrapers (src/data/
    # scrapers/). A Docker named volume mounted here, not a host bind mount -
    # unlike the old Proxmox /mnt/data bind-mount setup (CLAUDE.md constraint
    # #18), a named volume inherits the image's chowned directory on first
    # creation, so no separate host-side chown step is needed.
    raw_archive_dir: str = "/mnt/data/fantasy-edge/raw"

    litellm_base_url: str = "http://litellm:4000/v1"
    litellm_api_key: str = ""
    fantasy_model_alias: str = "worker"
    fantasy_news_rss_urls: str = ""

    # ESPN Fantasy Football has no public API and no account-wide "list my
    # leagues" call the way Sleeper does - private-league access requires
    # the two cookie values (espn_s2, SWID) from an already-logged-in
    # browser session, and each league to sync must be listed explicitly
    # by id. Comma-separated to match fantasy_news_rss_urls' own convention
    # (split at the point of use in src/ingest/espn_fantasy.py, not here).
    espn_league_ids: str = ""
    espn_s2: str = ""
    espn_swid: str = ""
    espn_fantasy_season: int = 2026
    # lm-api-reads.fantasy.espn.com, NOT fantasy.espn.com - verified live
    # 2026-09-09: the real cookies/league both check out fine against the
    # read-API host (a plain curl with the same espn_s2/SWID returned a
    # real 200 JSON payload), but the same request against
    # fantasy.espn.com (that host is the web app frontend, not an API)
    # 302-redirects to the generic https://www.espn.com/fantasy/ page
    # regardless of credentials - it isn't an auth failure, it's the
    # wrong host. Confirmed against the cwendt94/espn-api community
    # package's own request layer (espn_api/requests/constant.py), which
    # uses this exact host.
    espn_fantasy_base_url: str = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

    # Fractional-Kelly multiplier applied to /signals' full-Kelly stake
    # suggestion - standard bankroll-risk reduction, not a fitted value.
    kelly_fraction_cap: float = 0.25

    # homelab-dashboard's /api/ingest/articles - same bearer-token ingest
    # path OpenClaw/Adjutant already use, see src/utils/dashboard_ingest.py.
    # dashboard_ingest_token must match homelab-dashboard's own
    # ARTICLE_INGEST_TOKEN or every push gets a 403 (that route bypasses
    # Cloudflare Access in favor of this token, same as ARTICLE_INGEST_TOKEN
    # everywhere else in the homelab).
    dashboard_ingest_url: str = ""
    dashboard_ingest_token: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
