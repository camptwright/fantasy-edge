# Replacement backend foundation acceptance — October 6

Scope: the personal-use replacement backend, not production cutover, frontend
parity or prediction qualification. Keep fantasy-tool/UI implementation paused
until the checks below are satisfied. Existing source changes remain uncommitted.

## Implemented acceptance controls

| Control | Evidence |
| --- | --- |
| Separate deployment | Explicit workspace Compose project; legacy API/workers untouched |
| Authentication | Standalone shared dependency, constant-time token comparison; readiness, metrics and runtime history authenticated |
| Read-only serving | Real PostgreSQL rejects attempted write, including a zero-row DELETE |
| Bounded DB work | Pool 2, no overflow, pool/connect timeout 2s, statement timeout 2s; real slow-query cancellation and post-rollback recovery tested twice |
| Dependency failure | Pool/driver errors return redacted no-store HTTP 503 with Retry-After; missing data remains distinct from unavailable service |
| Checkpoint integrity | Digest, recipe, revision binding, league/shared invalidation, expiry, malformed/naive timestamps and invalid data shape tested; no model-build fallback |
| Concurrency | Per-process trade admission rejects before DB work; cancelled requests retain admission slot until calculation ends |
| Stable model identities | Prior prediction/capture/evaluator separation retained; no model recipe/math edits in this slice |
| Readiness | Authenticated DB check used by container healthcheck; observer starts after preview readiness |
| Diagnostics | Five-minute bounded cross-service history; 288 observations retained in one dedicated derived checkpoint |
| Deployment evidence | Release auditor supports explicit --workspace target, compares source and pinned packages for both backend containers |

## Diagnostics behavior and limitations

The new `workspace-observer` is a separate process, not another ingestion worker.
It uses fresh NullPool DB sessions and fresh Redis clients on every observation.
It polls only the two internal API metrics endpoints, preview DB readiness,
queue LLEN values for the configured default priority buckets, and aggregated
pg_stat_activity counts. It does not consume/dispatch tasks, fetch providers,
run evaluations or alter prediction evidence. Only `workspace-runtime-history`
in derived_checkpoints is written; that namespace does not invalidate fantasy
inputs. No schema migration or Docker socket access is needed.

Measurements: API reachability/process IDs/current RSS where supported/peak RSS,
rolling route p95 and 5xx counts; queued work in celery/evaluation; database
connection/active/lock-wait/idle-in-transaction counts. SQL text, task payloads,
credentials and query-string values are not stored. Redis/database faults are
unknown/unreachable, never zero. Observer freshness is separate from service
health. A missing/stale/corrupt history is not a healthy status.

This is not continuous tracing, browser timing, worker CPU/RSS sampling, or proof
that workers are alive when their queues are empty. Production API currently
does not expose current RSS; it stays null, not substituted with peak RSS.
Observation failures during DB outages cannot be persisted to the unavailable
DB; the previous observation ages to stale and a redacted failure reaches logs.
No external notifications are configured. Long-duration history must accumulate
naturally; short acceptance checks do not establish a long-term performance SLO.

## Verification recorded

- Full non-live regression run: 837 passed, 1 skipped, 20 live-provider tests
  deselected, before adding one release-target selection test.
- Foundation repeat: 82 passed. Release-audit tests: 5 passed. Ruff and diff check
  passed. Real read-only and statement-timeout enforcement run twice.
- Live smoke: all three leagues returned current snapshots with 9/11/9 starters;
  nine overview requests 57–74 ms. Readiness succeeded and observer history was
  current. First observation had zero waiting jobs and zero DB lock waiters;
  these are only point samples.
- Mixed load: 40.54 seconds, concurrency capped at six; 120/120 overview reads
  HTTP 200, p95 254.94 ms, max 288.10 ms. Thirty admitted trade reads returned
  HTTP 200 with model result withheld; p95 259.83 ms. Sixty overload requests
  returned HTTP 429, p95 4.75 ms. No transport errors or 5xx. Research admission
  and speed do not imply model qualification.
- Final full regression after all source changes: **838 passed, 1 skipped,
  20 live-provider tests deselected**. Both deployed backend containers matched
  all **259** inventoried source/config files and pinned dependency versions,
  with no missing, unexpected or changed files. Dashboard was not rebuilt.

The bounded replacement-backend foundation is accepted for continuing fantasy
workflow implementation. This does not accept production cutover or establish
sustained browser/resource performance; those boundaries are listed below.

## Operating and rollback commands

```sh
docker --context colima compose -f docker-compose.workspace.yml up -d --no-deps --build workspace-api workspace-observer
python scripts/release_audit.py --context colima --workspace
docker --context colima compose -f docker-compose.workspace.yml exec -T -e PYTHONPATH=/app workspace-api python scripts/workspace_smoke.py
docker --context colima compose -f docker-compose.workspace.yml logs --tail 20 workspace-observer
```

Read history via authenticated `GET /api/v2/operations/runtime`. It contains a
freshness status, latest observation and bounded history. The API serves only
saved observations; reading it does not probe providers or trigger calculations.

Stop only the observer to disable collection without interrupting the preview:

```sh
docker --context colima compose -f docker-compose.workspace.yml stop workspace-observer
```

To withdraw the entire preview, stop workspace-api, workspace-dashboard and
workspace-observer in that same explicit Compose project. Retain the history and
shared database. Do not use `down -v`. Production port 13000 remains available.

## Outside foundation acceptance

Browser/mobile/accessibility acceptance, reference-driven visual rebuild, full
legacy workflow parity, correlated model qualification, and final coordinated
production cutover remain later workstreams. They must not be called complete
on the basis of this backend acceptance.
