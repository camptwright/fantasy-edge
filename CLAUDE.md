# CLAUDE.md — Fantasy Edge

## What this is

An NFL sports betting value engine foundation.

**Current scope**: NFL only. Player props (Underdog Fantasy), game outcomes (ESPN).

Historical multi-sport application (Eight-sport best-bets engine + DFS fantasy optimizer) removed 2026-08-20 per `/docs/PRESERVED.md`. The rebuild focuses on establishing data ingestion and odds-math primitives for a production NFL pipeline, with five artifacts preserved encoding real production incidents and live-verified facts.

## Stack

Python 3.12 · PostgreSQL 16 · Docker Compose.

## Hard-won constraints — violating these caused production bugs

> Constraint numbers are historical and deliberately non-contiguous. Gaps mark
> constraints retired with the eight-sport application; the surviving numbers
> keep their original identity so that git history and code comments
> referencing them stay accurate.

1. **Celery DB access.** Every task opens its own `get_worker_db()` NullPool
   session created *inside* the task. Never share a pooled asyncpg engine
   across forked processes — the child inherits live sockets the parent still
   thinks it owns. All tasks use `asyncio.run()`, never a manually managed
   loop. See `src/data/cache/db_client.py`.
2. **Nullable columns in filters.** Any `WHERE` on a nullable column
   (`games.game_time`) must be `or_(col.is_(None), ...)` or those rows silently
   vanish. This once made an entire endpoint return one source only.
6. **Props dedup lives in Postgres**, as `INSERT ... WHERE NOT EXISTS` on
   (player_name, stat_type, source, line, date) plus the `uq_prop_daily` unique
   index as a backstop. Never dedup with Redis marker keys — they never expired
   and froze the pipeline.
7. **Props list endpoints must use `DISTINCT ON (player_name, stat_type,
   source) ORDER BY captured_at DESC`** or the UI shows hundreds of duplicates.
8. **Normalize `stat_type` at ingest time** (`pts`→`points`, `reb`→`rebounds`,
   `"1h points"`→`1h_points`) so cross-source joins line up.

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
18. **The `/mnt/data/fantasy-edge/{models,logs}` bind mounts must be
    `chown 1001:1001` on the host, not just `mkdir`.** The Dockerfile's
    `chown -R fantasy:fantasy` runs at image-build time and only affects the
    image's own filesystem layer; a host bind mount over that same path at
    container start shadows it with the HOST directory's ownership. A plain
    `sudo mkdir -p /mnt/data/fantasy-edge/{...}` leaves those directories
    root-owned, and the container (which drops to uid 1001 per the
    Dockerfile) then gets `PermissionError: [Errno 13] Permission denied`
    the first time it tries to save a model or write a log - a working
    `docker compose build` and healthy containers give no hint of this until
    something actually writes. `scripts/proxmox_bootstrap.sh` (Phase 6) must
    `chown -R 1001:1001` after creating these directories, not just `mkdir`.
22. **CONSTRAINT #1 GENERALISES TO REDIS, NOT JUST THE DB ENGINE - and this
    one only breaks the SECOND time a task runs, not the first.** A
    `redis.asyncio.Redis` client's connections are bound to whichever
    asyncio event loop was active when it first connected. `get_redis()`'s
    module-level cache is safe for the API process (uvicorn keeps one loop
    for its whole life) but every Celery task's `asyncio.run()` creates a
    fresh loop and destroys it on completion; reusing `get_redis()`'s
    cached client across two different `asyncio.run()` calls hands the
    second one a client still holding sockets from the FIRST (now-closed)
    loop. First symptom: `RuntimeError: Task ... got Future ... attached to
    a different loop`; that failure's own cleanup path then raises
    `RuntimeError: Event loop is closed` trying to close the stale
    connection. Caught empirically on CT 100 running the REAL worker +
    beat containers, not a `docker compose run` one-off: `odds_tick`
    succeeded on its first scheduled execution and threw exactly that
    traceback on its second - a bug that direct-agent smoke tests (Phase
    2-4's `docker compose run --rm api python -`, which only ever
    exercises ONE `asyncio.run()` per invocation) structurally cannot
    catch, because it takes a second, later invocation reusing the same
    process to surface at all. Fixed with `get_worker_redis()` (an async
    context manager, same NullPool-per-task shape as `get_worker_db()`)
    in `redis_client.py`, and rewired every call site that runs inside a
    Celery task - `odds_monitor.py`, `alert_agent.py`, `value_agent.py`
    (`_publish_and_alert`), `tasks.py`'s `odds_tick` - off the shared
    `get_redis()`. The quota-guard functions (`is_quota_exhausted`,
    `set_quota_exhausted`, `clear_quota_exhausted`) now take an explicit
    `redis` client parameter instead of reaching for the global, so the
    same functions work correctly from both contexts. Re-verified by
    queuing `odds_tick` twice in a row (the exact failure sequence) after
    the fix - both succeeded cleanly - and confirmed the real beat
    scheduler firing ticks autonomously with zero errors afterward.
    `get_redis()` itself is still correct and still used - by
    `api/routers/health.py` and `api/main.py`'s lifespan shutdown - because
    the API process's one persistent event loop is exactly the case it was
    designed for.
24. **FIXED (2026-08-06). Historical seed data and live-synced data used to
    not share Team identity.** `scripts/seed_historical.py`'s NFL loader
    created `Team` rows from `nfl_data_py`'s abbreviations (`"KC"`,
    `"DET"`, ...) with no `espn_id`; `GameSyncAgent` resolved teams for
    live ESPN-synced games by `espn_id` first, then exact `Team.name`
    match against ESPN's full display names (`"Kansas City Chiefs"`).
    Neither path matched the other, so a live game's `home_team_id`/
    `away_team_id` stayed `NULL` even after historical seeding, and
    `/rankings/{sport}` stayed empty. Fixed with
    `src/data/team_resolution.py`'s `resolve_team()`, now the one place
    either `seed_historical.py` (`create=True`) or `GameSyncAgent`
    (`create=False`, unchanged read-only behavior) looks a team up -
    both run it through `config/team_aliases/<sport>.yaml` first, so
    whichever path runs first creates the canonical (ESPN name +
    espn_id) row and the second attaches to it. `alembic/versions/0002`
    backfills any Team row already sitting under the old raw name onto
    its canonical identity (in place if it's the only row for that team,
    re-pointing every Game/PowerRanking/Player FK first if a genuine
    duplicate exists). Verified live against real Postgres on CT100:
    560/561 seeded NFL games now resolve both `home_team_id`/
    `away_team_id` (the one holdout is a pre-2024-relocation `"LA"` game
    predating the current abbreviation convention).

    Both `config/team_aliases/*.yaml` files and the ESPN-side data they
    map to were fetched live (site.api.espn.com, plus
    baseball-reference.com directly for MLB's actual abbreviation
    scheme) on 2026-08-06, not written from memory. Two real bugs found
    in the process, both now fixed:
    - `nhl_loader.py` read a `home.get("name")`/`away.get("name")` field
      that doesn't exist anywhere in the real NHL API v1 schema (verified
      live against a real `club-schedule-season` response) - every NHL
      historical game was silently dropped before `_seed_games` even ran
      (`if not g.get("home_team_name"): continue`). Fixed to read the
      real `abbrev` field instead.
    - An unquoted `NO` (New Orleans Saints) key in `nfl.yaml` parsed as
      the Python bool `False` under PyYAML's YAML-1.1 `safe_load`, not
      the string `"NO"` - the classic "Norway problem." A structural
      dict-shape test didn't catch it (still 32 entries, 32 unique
      espn_ids); the backfill migration's real SQL bind against a
      varchar column is what actually rejected it
      (`UndefinedFunction: operator does not exist: character varying =
      boolean`), live, on the first real run. `tests/test_team_aliases.py`
      now asserts every alias key is an actual `str` for exactly this
      reason.

## Layout

```
config/settings.py     pydantic-settings from .env
config/team_aliases/   nfl.yaml — team identifier -> ESPN canonical name/espn_id (constraint #24)
src/data/providers/    underdog_api.py (props), espn_api.py (games)
src/utils/             odds_math.py (vig removal), normalize.py (stat type alignment)
alembic/versions/      migrations (empty, pending Task 2)
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
.venv/bin/python -m pytest tests/test_preserved.py -v
.venv/bin/python -c "import src.utils.odds_math, src.utils.normalize; print('imports ok')"
.venv/bin/ruff check src config tests
```

## Status

**Task 1 (2026-08-20): NFL-only clean slate.** Eight-sport application and
daily-fantasy product surface removed. Five artifacts preserved encoding
production incidents and live-verified facts:

- `src/utils/odds_math.py` — vig removal and probability conversion
- `src/utils/normalize.py` — stat-type normalization for cross-source joins
- `src/data/providers/underdog_api.py` — Underdog Fantasy props provider (constraint #17 shape verified 2026-08-02)
- `config/team_aliases/nfl.yaml` — ESPN team identities (constraint #24, live-fetched 2026-08-06, includes quoted `"NO"` safeguard)
- `CLAUDE.md` — preserved constraints #1, #2, #6, #7, #8, #13, #14, #15, #16, #17, #18, #22, #24

`tests/test_preserved.py` is the tripwire protecting these.

Remaining tasks: Task 2 (schema bootstrap), Task 3–8 (data ingestion pipeline, algorithms, API scaffolding).

## Notes for future phases

This is a foundation rebuild, not yet a complete application. Tasks 2–8 will
re-introduce ingestion, algorithms, and API layers as focused NFL-only systems,
without the multi-sport configuration complexity of the previous build.

Constraint #1 (Celery DB access pattern) and constraint #22 (Redis event-loop
isolation) will be re-introduced in Task 4 onwards; they remain documented here
because they encode hard-won production incidents that any new scheduler/task
runner implementation must respect to avoid regression.
