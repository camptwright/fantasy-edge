# Mac mini deployment

Supersedes `PROXMOX.md` (CT100/Proxmox is retired as this app's deployment
target; that doc is kept only as historical record of its RAM-budget and
backup-cron lessons). As of 2026-09, this also supersedes this file's own
2026-08-29 reekserver-1 plan below in one respect: the app actually runs on
the **Mac mini** (`192.168.10.10`), not reekserver-1 — confirmed live during
the 2026-09-09/10 homelab security audit. The rest of this file (compose
build steps, NCAAF bootstrap) is host-agnostic and still accurate; the
tunnel/Access section below has changed, and the ntfy section was rewritten
2026-09-13 for the fleet-wide ntfy consolidation (this app no longer runs
its own ntfy container).

Clone this repository, create a mode-0600 `.env` from `.env.example`, then
run `docker compose up -d --build postgres redis litellm migrate api worker
beat dashboard`. This project owns its Postgres and Redis volumes, LiteLLM
key, and model routing, and — unlike the original reekserver-1 plan — runs
its **own dedicated** `cloudflared` container rather than joining a shared
tunnel:

1. The `cloudflared` service in `docker-compose.yml` runs its own
   token-authenticated tunnel (not the reekserver-1 shared one). Its live
   ingress rules route `sports.camptwright.com` → `dashboard:3000`,
   `sports-api.camptwright.com` → `api:8000`, and (unrelated to this app,
   but sharing the same tunnel) `ollama-mac.camptwright.com` → the host's
   native Ollama. Manage ingress in the Cloudflare Zero Trust dashboard
   under this tunnel, not a local `config.yml`.
2. The dashboard is protected by the same shared Cloudflare Access
   application ("chat" in the Zero Trust dashboard) that covers
   dashboard.camptwright.com/fitness.camptwright.com/chat.camptwright.com —
   `sports.camptwright.com` was added as a destination on that app 2026-09.
   `CF_ACCESS_TEAM_DOMAIN`/`CF_ACCESS_AUD` in `.env` must be that app's real
   values (both are hard-required by `docker-compose.yml`'s `:?` guard as of
   2026-09; previously optional, which let the dashboard silently serve
   unauthenticated when unset — see the 2026-09-09/10 audit).
3. **The API is no longer "deliberately unauthenticated."** As of 2026-09,
   every route — including `/props`, `/signals`, `/rankings/{sport}`,
   `/parlays` — requires the `FANTASY_API_TOKEN` bearer token, same as
   `/api/v1/fantasy/*` always did. homelab-dashboard's Fantasy tile
   (`src/tiles/fantasy/client.ts`) sends it via `FANTASY_EDGE_API_TOKEN`,
   which must match this app's `FANTASY_API_TOKEN` — set it in
   homelab-dashboard's `.env` too, or the tile degrades to its normal
   "offline" empty state (a 401 looks like "unreachable" to that client, it
   won't error loudly).

## litellm memory

Do **not** set `mem_limit` on the `litellm` service. Verified live
2026-08-29: both 256m and 512m OOM-killed `ghcr.io/berriai/litellm` in a
continuous restart loop (`docker events --filter container=fantasy-edge-litellm-1`
showed `oom -> die -> start` on a ~1-minute cycle). The other three
reekserver-1 apps run this same image with no memory ceiling at all; match
that rather than re-guessing a number.

## NCAAF bootstrap

`GET /rankings/ncaaf` and `/signals?sport=ncaaf` stay empty until Elo has
something to rate. Live sync populates ratings organically as NCAAF games
finalize (the beat schedule already covers both sports), but a faster start
is `python -m scripts.bootstrap_ratings --seasons 2024 2025` on a host with
network access to ESPN's scoreboard (run inside the `api` container: no new
dependency needed for the NCAAF half). NFL's half of that same script reads
already-ingested `games` rows and needs no extra package for the ingestion
side either, but if `games` is empty, run
`python -m scripts.ingest_history --seasons 2024 2025` first — that one
does need `nflreadpy` (`pip install -e '.[offline]'`), which is
deliberately not part of the serving image.

## ntfy alerting

`src/utils/alerts.py`'s `notify()` silently drops every alert until
`NTFY_BASE_URL`/`NTFY_TOPIC`/`NTFY_TOKEN` are set in `.env` - by default
this app has no working alerting at all, which is how a Sleeper sync could
crash on every single scheduled run without anyone finding out (found live
2026-09-05).

As of 2026-09-14, this app has **no ntfy container of its own** - it
publishes to reekserver-1's shared ntfy instance (the standalone `ntfy`
repo), the same consolidation applied fleet-wide so there's one ntfy
instance instead of three. That instance defaults to
`NTFY_AUTH_DEFAULT_ACCESS: deny-all`; the one-time grant for this app
(`fantasyedge` user, read-write on topic `fantasy-edge-alerts`, an access
token) is already done on the live instance - if setting this up again
from scratch (e.g. a fresh ntfy volume), repeat it from reekserver-1:

```bash
ssh reek@reekserver-1
cd /home/reek/apps/ntfy
docker exec -e NTFY_PASSWORD='choose-a-real-password' ntfy-ntfy-1 \
  ntfy user add --role=user fantasyedge
docker exec ntfy-ntfy-1 ntfy access fantasyedge fantasy-edge-alerts read-write
docker exec ntfy-ntfy-1 ntfy token add fantasyedge
```

**The intended path is the public hostname** (`NTFY_BASE_URL=
https://ntfy.camptwright.com`), routed through reekserver-1's Cloudflare
Tunnel same as every other app there. **As of 2026-09-14 that route 530s**
(Cloudflare error 1033) for reasons unrelated to this consolidation -
confirmed live while cutting this app over, cloudflared itself is healthy
so it's specifically that hostname's route. Until it's fixed, this app
points at the LAN port published for exactly that reason
(`ntfy/docker-compose.yml`, `192.168.20.10:8095`) - verified reachable from
this Mac mini across the 192.168.10.x/192.168.20.x subnet boundary,
contrary to this workspace's older "no route between those subnets"
assumption (see e.g. adjutant's DEPLOYMENT.md, homelab-monitoring's
README - that assumption is stale, at least for this direction). Put the
token in this app's `.env` as `NTFY_TOKEN`, `NTFY_TOPIC=fantasy-edge-alerts`,
and `NTFY_BASE_URL=http://192.168.20.10:8095` (swap to the public hostname
once it's confirmed working again), then `docker compose up -d
--force-recreate --remove-orphans api worker beat` on the Mac mini - the
`--remove-orphans` flag is what actually stops and removes the now-unused
`ntfy` container from before this consolidation, since it's no longer in
this project's compose file. Subscribe from the ntfy phone app at
`http://192.168.20.10:8095` (LAN-only until the tunnel route is fixed),
topic `fantasy-edge-alerts`, logging in as the same `fantasyedge`
user/password - deny-all means an unauthenticated subscribe 403s exactly
like an unauthenticated publish does.

The old `fantasy-edge_ntfydata` volume from before this consolidation has
already been removed (`docker volume rm fantasy-edge_ntfydata`, done
2026-09-14 after verifying the new path end-to-end).

Verify the whole path with a real publish, not just a healthcheck:
```bash
docker exec fantasy-edge-worker-1 python -c "
import asyncio
from src.utils.alerts import notify
asyncio.run(notify('test', title='Fantasy Edge: Test'))
"
curl -u fantasyedge:<password> 'http://192.168.20.10:8095/fantasy-edge-alerts/json?poll=1&since=all'
```

## Verify

```bash
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read())"
```
Expect `{"status":"ok","scope":"nfl+ncaaf"}`. Then `curl` (or hit through
the tunnel once wired up) `/props`, `/signals`, `/rankings/nfl`,
`/rankings/ncaaf` — all return `200` with `[]` on a fresh database; real
rows appear once the scheduler's first `sync-espn-scoreboard`/
`sync-team-markets`/`sync-underdog-props` beat ticks land (every 15-30
minutes per `src/scheduler/celery_app.py`).
