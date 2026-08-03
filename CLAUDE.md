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
19. **FastAPI only auto-combines multiple body parameters into one JSON
    object when each parameter is a scalar/single model keyed by name.** A
    route with two bare `list[...]`/`dict[...]` parameters
    (`start_sit(roster: list[X], starters_by_position: dict)`) expects a
    request body shaped `{"roster": [...], "starters_by_position": {...}}`,
    NOT a raw JSON array for "the roster" - sending a bare array 422s with
    `"roster": "Field required"` even though a body was clearly sent, because
    FastAPI can't tell which bare-list body maps to which parameter. Fix:
    one `BaseModel` wrapping every field, one body parameter. Hit this on
    both `/fantasy/start-sit` and `/fantasy/waivers`; both took a single
    `StartSitRequest`/`WaiversRequest` model instead.
20. **`next/navigation`'s `redirect()` (the App Router runtime helper) is
    built for RSC client-side transitions, not a plain HTTP redirect.**
    Called from `app/page.tsx` to bounce `/` -> `/signals`, it produced a
    307 response with `Vary: RSC, Next-Router-State-Tree, ...` headers and
    an HTML body, but **no `Location` header at all** - verified with
    `curl -I`, not assumed. Only the Next.js client router (interpreting
    the RSC payload) knows how to follow that; a real browser doing a
    fresh page load, or curl, gets a 307 that goes nowhere. Fix: a plain
    `redirects()` entry in `next.config.js` instead (`{ source: "/",
    destination: "/signals", permanent: false }`), which resolves before
    the App Router matches a page and emits a normal `Location` header -
    confirmed with `curl -I` afterward. There is no `app/page.tsx`
    anymore; the config redirect handles `/` entirely.
21. **`npm audit` on Next.js 14.2.x reports two "high" findings that
    don't apply here, verified against the actual advisory text rather
    than just the severity label.** GHSA-p9j2-gv94-2wf4 (SSRF via
    `rewrites()`) only fires when a rewrite's destination *hostname* is
    built from request-controlled input (a `:param` in the host, or a
    captured `has` query value) - this app's one rewrite
    (`/api/:path*` -> `${API_INTERNAL_URL}/:path*`) has a fixed hostname
    from an env var and only templates the path suffix, which the
    advisory explicitly calls out as the non-vulnerable shape. The other
    finding is a transitive PostCSS build-tool vuln (XSS/path traversal
    in *processing CSS source*, not anything served at runtime) with no
    fix short of a Next 16 major-version jump, which would break this
    app's Next 14 pin for no runtime benefit on a LAN-only host with no
    external exposure. Bumped to the latest 14.x patch (14.2.35) for
    whatever it does cover; did not force the major upgrade.

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
- **Phase 3 (algorithms) — done.** `elo.py`, `poisson.py` (Dixon-Coles),
  `ensemble.py` (XGBoost+LightGBM stacked, TimeSeriesSplit, versioned
  pickle), `kelly.py` (full/fractional/portfolio), `ev_calculator.py`
  (vig removal, tiers, divergence-based confidence), `clv.py`,
  `dfs_optimizer.py` (PuLP, DK/FD NBA+NFL roster rules), `projections.py`,
  `value_over_replacement.py`, `scripts/train_models.py`,
  `scripts/backtest.py`. Unit-tested locally (elo, poisson, kelly, ev, clv,
  VOR, projections, DFS optimizer with lock/exclude/team-cap all pass);
  `ensemble.py` and the DB-backed `train_models.py`/`backtest.py` needed
  CT 100 (LightGBM needs `libomp`, present in the container via
  `apt install libgomp1`, absent on this Mac). Full walk-forward demo run
  against 120 synthetic seeded games on real Postgres: ensemble trained
  (72% OOF accuracy on a deliberately-baked-in signal), model saved and
  reloaded byte-identical, `backtest.py` correctly reported win
  rate/Brier for all 120 games and ROI/CLV for only the 20 games with
  synthetic `odds_snapshots` - proving the "no market odds available"
  coverage-counting logic works, not just the happy path.
- **Phase 4 (agents, scheduler, API) — done.** `value_agent.py` (full
  pipeline: persisted-ELO state advanced incrementally rather than replayed
  from scratch every run, on-the-fly Poisson attack/defense from recent
  scoring, ensemble loaded if trained/gracefully skipped with proportional
  blend-weight redistribution if not, best-price-per-side EV eval, signal
  persistence, publish+alert), `alert_agent.py` (tiered Discord embeds,
  Redis `SET NX` cooldown keyed on signal identity not row id),
  `clv_tracker.py` (backfills CLV once a signal's game goes final),
  `celery_app.py` + `tasks.py` (constraint #1 NullPool-per-task; season-
  aware Odds API polling done as a fixed-interval tick that self-gates per
  sport rather than a dynamic beat schedule). FastAPI routers: games
  (constraint #9 default window, constraint #2 NULL-safe game_time), odds
  (latest + best-price), signals (EV-sorted with game context), props
  (constraint #7 DISTINCT ON dedup, /best cross-source spread, /compare),
  parlays (constraint #12: reads only `player_prop_lines`, never
  `bet_signals`), fantasy (DFS optimize, lightweight projections from live
  Underdog lines, start-sit/waivers - all three accept their player
  pool/roster in the request body since no salary-feed or season-long-
  roster provider exists in this system), rankings, health.

  Smoke-tested on CT 100: every read endpoint curls clean against real
  data (`/games` returns the live NFL fixture from Phase 2,
  `/props` returns live WNBA lines, `/props/best` correctly returns `[]`
  since Underdog is our only source so no pair has 2+ sources to diff -
  not a bug); `/parlays/generate` returns a clean 503 on the missing
  `OPENAI_API_KEY` rather than a 500, and `_candidate_props` was verified
  directly to find 20 real WNBA props while never touching `bet_signals`
  (0 rows in that table at the time); `/fantasy/dfs/optimize` solved a
  synthetic 8-player NBA pool correctly. The core smoke test - seed a
  synthetic scheduled game with generous h2h odds, run
  `ValueAgent.evaluate_game` for real - produced 2 persisted `bet_signals`
  rows with sane blended probabilities (0.554/0.446) derived from 3 real
  ESPN-synced WNBA games already in the DB.
- **Phase 5 (Next.js dashboard) — done.** Next.js 14.2.35 (App Router,
  `output: 'standalone'`, constraint #10), Tailwind dark theme, SWR for
  data fetching against relative `/api/...` paths. Pages: Signals
  (EV-sorted cards, sport/min-EV filters, 30s auto-refresh), Games
  (upcoming only - trusts the backend's constraint #9 default rather than
  re-filtering), Props (Best Value + All Props tabs, source filter,
  DISTINCT ON dedup rendered straight from the API), Parlays (generate +
  list, surfaces the 503 from a missing `OPENAI_API_KEY` as a real error
  rather than hiding it), Fantasy (DFS builder with an editable player
  pool + lock/exclude checkboxes since no salary-feed provider exists,
  Projections from live Underdog lines, Start/Sit and Waivers with
  manual roster entry against the VOR algorithm), Rankings.

  `docker compose build --no-cache dashboard` succeeds on CT 100; a real
  container was started and curled, not just built. Found and fixed two
  bugs via the actual HTTP responses, not by inspection: (1) `npm audit`
  flagged Next.js SSRF/PostCSS findings - verified against the real
  advisory text that the SSRF one doesn't apply to this app's rewrite
  shape (see constraint #21), bumped to the latest safe 14.x patch
  instead of forcing a breaking major upgrade; (2) the root `/` redirect
  had no `Location` header at all (`curl -I` proved it, App Router's
  `redirect()` is for client-side RSC transitions - constraint #20),
  fixed with a `next.config.js` `redirects()` entry, then re-verified
  `curl -I` shows `location: /signals` and `curl -L` reaches a real 200
  with `<title>Fantasy Edge</title>`.
- Phase 6 (deploy) — not started.

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
