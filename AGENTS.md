# fantasy-edge Agent Instructions

## What this repo is

A self-hosted sports betting value engine and fantasy optimizer: it prices bets
by comparing model win probabilities (ELO + Dixon-Coles Poisson + XGBoost/
LightGBM ensemble) against vig-removed sportsbook odds, sizes them with
quarter-Kelly, and runs a DFS lineup optimizer (PuLP) plus season-long
start/sit and waiver tools. It runs as a 7-container Docker Compose stack
(postgres, redis, api, worker, beat, flower, dashboard) on Proxmox LXC CT 100,
and is consumed read-only over the network by homelab-dashboard's Fantasy tile
and Adjutant's `fantasy` sub-agent via `/props`, `/games`, `/rankings`, etc. —
nothing here needs to change for them, but a response-shape change affects both.

## Hard rules for agents

1. **Celery tasks never share a pooled DB engine or cached Redis client
   across `asyncio.run()` calls.** Every task in `src/scheduler/tasks.py`
   opens its own `get_worker_db()` (NullPool, `src/data/cache/db_client.py`)
   and, if it needs Redis, `get_worker_redis()`
   (`src/data/cache/redis_client.py`) — never the API-only `get_db()`/
   `get_redis()`. A cached asyncpg engine or `redis.asyncio.Redis` client is
   bound to whichever event loop first touched it; reusing it in a second
   `asyncio.run()` (a task's second execution) throws `RuntimeError:
   ... attached to a different loop`. This only surfaces on the task's
   SECOND run, so a one-shot smoke test cannot catch it.

2. **Never change `src/algorithms/*.py` (elo, poisson, ensemble, kelly,
   ev_calculator, clv, dfs_optimizer, projections, value_over_replacement)
   or `src/utils/odds_math.py` without the `algorithms-correctness-reviewer`
   agent reviewing the diff.** This code sizes and prices real-money bets —
   a sign error or unit mismatch doesn't crash, it silently recommends a
   losing bet as +EV.

3. **New pytest coverage for `src/algorithms/*.py`/`src/agents/*.py` runs
   offline** (unit tests, mocked DB) — that's what the `test-writer` agent
   is for. DB-dependent integration tests against the real Postgres on
   CT 100 stay the maintainer's job, run by hand.

4. Filters on `games.game_time` (nullable by design — providers publish
   fixtures before a kickoff time exists) must be `or_(col.is_(None), ...)`,
   not a bare comparison, or those rows silently vanish from results.

5. **Odds API calls must stay inside the season-aware quota guard.** Free
   tier is 500 requests/month; polling is gated by `season_months`, a
   per-sport interval, and a Redis `odds_api:quota_exhausted` flag read from
   `x-requests-remaining`. Route new calls through `OddsMonitor`, don't add
   a path that bypasses it.

6. Props dedup is a Postgres `INSERT ... WHERE NOT EXISTS` plus the
   `uq_prop_daily` unique index — never a Redis marker key (that shape
   existed once, the keys never expired, and it froze the pipeline).

7. Nginx runs on the LXC host via `apt`, not in Docker Compose — a
   containerized nginx fights the host for port 80 and one loses
   non-deterministically.

8. Always apply a new Alembic migration to a real Postgres before trusting
   it. `alembic upgrade head --sql` (offline mode) only proves the migration
   *code* runs, not that Postgres accepts the DDL — e.g. `date(timestamptz)`
   is STABLE, not IMMUTABLE, and Postgres rejects it in an index expression
   only at apply time.

## Agents must not

- Scrape PrizePicks for player props (it sits behind PerimeterX) — Underdog
  Fantasy's public API is the source.
- Assume `/props/best`, `/rankings/*`, or `/signals` returning empty is a
  bug. There is no trained projection pipeline running yet, so these are
  legitimately empty for most sports today; NCAAF additionally has no
  team-identity crosswalk (`config/team_aliases/`) yet at all.
- `tar` this repo from macOS without `COPYFILE_DISABLE=1` — AppleDouble
  `._*` sidecars break Alembic's `alembic/versions/*.py` glob import.
- Rename an agent class without updating its import site exactly (e.g.
  `from src.agents.props_agent import PropsAgent`) — smoke-test with
  `python -c "from ... import ..."` before committing.
- Use `ON CONFLICT ON CONSTRAINT` for an expression-based unique index like
  `uq_prop_daily` — it only resolves against `pg_constraint` and fails even
  though the index exists. Use `on_conflict_do_nothing(index_elements=[...])`.
