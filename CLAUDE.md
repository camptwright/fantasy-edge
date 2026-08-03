# CLAUDE.md — Fantasy Edge

## What this is

A self-hosted live sports betting value engine and fantasy optimizer.

1. **Best bets** — surface positive-EV wagers by comparing model win
   probabilities (ELO + Dixon-Coles Poisson + XGBoost/LightGBM ensemble)
   against vig-removed sportsbook implied probabilities. Rank by EV%, size with
   quarter-Kelly, track closing line value (CLV) as the honest model scoreboard.
2. **Fantasy value** — DFS lineup optimization (PuLP linear program against
   DraftKings/FanDuel salary caps), player-prop edges from cross-source line
   discrepancies, and season-long start/sit + waiver tools driven by value over
   replacement.

Sports: NFL, NCAAF, NBA, WNBA, NCAAM, NHL, MLB, College Baseball. All
sport-specific behaviour lives in `config/sports.yaml`, so adding eSports /
soccer / F1 later is a config change rather than a code change.

## Stack

Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · Celery · Next.js 14
(standalone output) · **system Nginx on the LXC host, never containerized** ·
Docker Compose.

## Hard-won constraints — violating these caused production bugs

1. **Celery DB access.** Every task opens its own `get_worker_db()` NullPool
   session created *inside* the task. Never share a pooled asyncpg engine
   across forked processes — the child inherits live sockets the parent still
   thinks it owns. All tasks use `asyncio.run()`, never a manually managed
   loop. See `src/data/cache/db_client.py`.
2. **Nullable columns in filters.** Any `WHERE` on a nullable column
   (`games.game_time`) must be `or_(col.is_(None), ...)` or those rows silently
   vanish. This once made an entire endpoint return one source only.
3. **Class names must match imports exactly.** The props agent is `PropsAgent`,
   imported as `from src.agents.props_agent import PropsAgent`. Smoke-test every
   agent import with `python -c` before committing.
4. **Odds API free tier is 500 requests/month.** Three defences, all from day
   one: (a) season-aware polling driven by `season_months`; (b) 300s in-season
   / 21600s off-season intervals; (c) quota guard reading
   `x-requests-remaining` — below 50, set Redis `odds_api:quota_exhausted`
   (TTL 24h) and skip all polls while set.
5. **Player props are not on the Odds API free tier — do not call them.**
   PrizePicks sits behind PerimeterX; do not scrape it. Underdog Fantasy's
   public API is the primary props source.
6. **Props dedup lives in Postgres**, as `INSERT ... WHERE NOT EXISTS` on
   (player_name, stat_type, source, line, date) plus the `uq_prop_daily` unique
   index as a backstop. Never dedup with Redis marker keys — they never expired
   and froze the pipeline.
7. **Props list endpoints must use `DISTINCT ON (player_name, stat_type,
   source) ORDER BY captured_at DESC`** or the UI shows hundreds of duplicates.
8. **Normalize `stat_type` at ingest time** (`pts`→`points`, `reb`→`rebounds`,
   `"1h points"`→`1h_points`) so cross-source joins line up.
9. **Games API defaults**: `status=scheduled`, `game_date >= NOW()` strictly
   future, 7-day forward window. Never default to dumping history.
10. **Dashboard Dockerfile**: `output:'standalone'` in next.config.js; create
    `dashboard/public/` even if empty; `COPY` with the `/app/public*` wildcard;
    `npm ci --legacy-peer-deps`; compose maps `3000:3000`.
11. **Nginx runs on the LXC host via apt, not in compose.** A containerized
    nginx fights the host for port 80 and one loses non-deterministically.
12. **Parlay generation** uses OpenAI (`gpt-4o`) and must work from prop edges
    alone — never require `bet_signals` to be non-empty, since signals only
    exist after odds polling has succeeded.

### Added while building

13. **`date(timestamptz)` is STABLE, not IMMUTABLE**, so Postgres refuses it in
    an index expression and the whole migration rolls back. The `uq_prop_daily`
    index pins the zone: `((captured_at AT TIME ZONE 'UTC')::date)`. Alembic's
    `--sql` offline mode will not catch this — it only proves the migration
    *code* runs, not that Postgres accepts the DDL. Always apply a migration to
    a real Postgres before trusting it.
14. **Alembic needs a sync driver.** It cannot use asyncpg. A bare
    `postgresql://` URL makes SQLAlchemy reach for psycopg2, which is not a
    dependency — `alembic upgrade head` then dies with
    `ModuleNotFoundError: psycopg2`. `sync_database_url` uses
    `postgresql+psycopg://` and psycopg3 is pinned in pyproject.
15. **Never `tar` this repo from macOS without `COPYFILE_DISABLE=1`.** macOS
    packs extended attributes as `._*` AppleDouble sidecars. They are binary,
    and alembic globs `alembic/versions/*.py` — so it tries to import
    `._0001_initial_schema.py` and dies with
    `SyntaxError: source code string cannot contain null bytes`. `.dockerignore`
    excludes `._*` as a second line of defence.
16. **`ON CONFLICT ON CONSTRAINT` needs a real Postgres constraint, not just a
    unique index.** `uq_prop_daily` has to be a plain `Index(unique=True)`
    rather than a `UniqueConstraint` because one of its keys is an expression
    (`((captured_at AT TIME ZONE 'UTC')::date)` — see #13) and Postgres does
    not support expression-based `UNIQUE` table constraints. But
    `ON CONFLICT ON CONSTRAINT uq_prop_daily` only resolves names against
    `pg_constraint`, so it fails with
    `UndefinedObjectError: constraint "uq_prop_daily" ... does not exist`
    even though the unique index by that name genuinely exists. Fix: target
    the same columns/expression with `on_conflict_do_nothing(index_elements=[...])`
    instead of `constraint=`. Plain `UniqueConstraint`-backed dedup (Team,
    Game) can keep using `constraint=` — this only bites expression indexes.
17. **Underdog Fantasy's `/beta/v6/over_under_lines` response is not
    self-contained per line.** It's one document with five sibling arrays -
    `over_under_lines`, `appearances`, `players`, `games`, `solo_games`. A
    line names its player only via
    `line.over_under.appearance_stat.appearance_id` → `appearances[].player_id`
    → `players[].id`; there is no top-level `player_id` on the line or its
    `appearance_stat`, and no `teams` array at all, so a player's team name
    is not resolvable from this endpoint. `player.sport_id` uses Underdog's
    own codes, not ours — notably `CFB` for college football, not `NCAAF`.
    Verified 2026-08-02 against the live endpoint (3841 lines, 0 unresolvable
    appearance_ids in-sample).

## Layout

```
config/settings.py     pydantic-settings from .env; sports.yaml loader helpers
config/sports.yaml     8 sports: season_months, ELO params, blend weights,
                       markets, ev_threshold_pct
src/data/cache/        db_client.py — the two-engine rule (constraint #1)
src/models/orm.py      11 tables, UUID PKs, UTC timestamps
src/data/providers/    theodds_api.py (games only), espn_api.py (free backbone)
src/agents/            props_agent, odds_monitor, game_sync_agent, value_agent,
                       alert_agent, clv_tracker
src/algorithms/        elo, poisson, ensemble, kelly, ev_calculator,
                       dfs_optimizer, projections, value_over_replacement
src/scheduler/         celery_app.py (season-aware beat), tasks.py
src/api/routers/       games, odds, signals, props, parlays, fantasy, rankings
alembic/versions/      migrations
```

## Data model notes

- `odds_snapshots` is **immutable and append-only**. Line-movement detection
  and CLV both depend on an accurate history; updating a row destroys the only
  record of what the market did.
- `games.game_time` is nullable on purpose — providers publish fixtures before
  a kickoff time exists. See constraint #2.
- `power_rankings.as_of` lets backtests read ratings at a point in time, which
  is what keeps `scripts/backtest.py` free of lookahead bias.

## Dev commands

```bash
docker compose up -d postgres redis
alembic upgrade head
docker compose up -d              # full stack
docker compose logs worker -f     # watch for asyncio loop errors
```

## Status

- **Phase 1 (foundation) — done.** Scaffold, settings, sports config, compose
  stack, ORM, initial migration. Migration verified against real Postgres 16:
  12 tables, 76 indexes, and the props dedup index empirically rejects a
  duplicate insert.
- **Phase 2 (data ingestion) — done.** `theodds_api.py` (quota-guarded,
  h2h/spreads/totals only), `espn_api.py` (free backbone, all 8 sports),
  `underdog_api.py` (props, see constraint #17 for the real payload shape),
  `PropsAgent`, `OddsMonitor`, `GameSyncAgent`, historical loaders
  (nfl_data_py, cfbd, NBA Stats API, NHL API v1, pybaseball — all deferred
  imports, optional-dependency only), `scripts/seed_historical.py`.
  Smoke-tested against real infrastructure on CT 100:
  - `PropsAgent` fetched 1975 live Underdog lines, inserted 1974 (1 dup
    within the same batch), 140 of them WNBA. A second run inserted 0 -
    the `uq_prop_daily` dedup backstop confirmed working end-to-end.
  - `GameSyncAgent` synced nfl/wnba/mlb from live ESPN and produced a
    `status=scheduled` future game (NFL, 2026-08-07).
  - All three agent classes import cleanly (`PropsAgent`, `OddsMonitor`,
    `GameSyncAgent`).
  - `OddsMonitor` was exercised against the real (empty) `ODDS_API_KEY` and
    correctly raises `ProviderError` rather than silently returning zero -
    see "Known gaps" below.
- Phase 3 (algorithms), 4 (agents/API), 5 (dashboard), 6 (deploy) — not
  started.

## Known gaps

- **`ODDS_API_KEY`, `OPENAI_API_KEY`, `DISCORD_WEBHOOK_URL`, `CFBD_API_KEY`
  are all empty in `.env` on CT 100.** Mirrors the homelab repo's
  `ANTHROPIC_API_KEY` gap. Consequences: `OddsMonitor` cannot poll odds
  (fails loudly with `ProviderError`, by design - not a quota-exhaustion
  silent skip); Phase 4's parlay generation (constraint #12) cannot call
  OpenAI; Discord alerts cannot fire; the CFBD historical loader cannot run.
  `PropsAgent` (Underdog) and `GameSyncAgent` (ESPN) need no key and are
  unaffected.

## Deployment — actual infrastructure

The build spec's `192.168.1.200` does not exist. Reality:

| | |
|---|---|
| Proxmox host | `10.51.24.34` (`reekserver`), PVE 9.2.0 |
| Host hardware | **Intel N95, 4 cores, 7,720 MB RAM** — *not* the 16GB the spec assumes |
| Fantasy Edge | **CT 100 `fantasy-edge`, `10.51.24.80`**, 3 cores / 4096 MB / 40GB, Ubuntu 24.04 |
| Access | no direct SSH — `ssh root@10.51.24.34 "pct exec 100 -- ..."` |
| Code lives at | `/opt/fantasy-edge` |

The host has only 7.5GB physical, so the spec's 6GB allocation was not
possible. CT 110 (docker-core) had been allocated 12GB on that 7.5GB box; it
was right-sized to 3GB (actual usage ~1.7GB) to make room. Combined limits are
now ~7GB against 7.5GB physical rather than 15GB.

`net0` uses `ip6=auto`, never `ip6=dhcp`: with no DHCPv6 server on this LAN,
`ifup` blocks on Solicit, `networking.service` times out, and the container
comes up with **no IPv4 either**. That took the whole docker-core stack offline
for 35 hours once.

Compose `mem_limit`s currently sum to ~4.7GB against the container's 4GB, which
is fine while services idle but needs trimming before all seven run under load.
