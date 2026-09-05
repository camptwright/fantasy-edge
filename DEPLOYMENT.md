# reekserver-1 deployment

Supersedes `PROXMOX.md` (CT100/Proxmox is retired as this app's deployment
target; that doc is kept only as historical record of its RAM-budget and
backup-cron lessons).

Clone this repository to `/home/reek/apps/fantasy-edge` (no sudo — `reek`
has no `/opt`/`/srv` access on this host, unlike the old CT100 LXC), create
a mode-0600 `.env` from `.env.example`, then run
`docker compose up -d --build postgres redis litellm migrate api worker beat dashboard`.
This project owns its Postgres and Redis volumes, LiteLLM key, and model
routing — it has no `cloudflared` service of its own. Public routing goes
through reekserver-1's shared Cloudflare Tunnel (id
`af0c35fc-ec30-407e-8f9c-56c76e4e8e22`, the same one serving OpenWebUI at
chat.camptwright.com):

1. `docker network connect fantasy-edge_fantasy cloudflared` so the shared
   tunnel container can reach this stack.
2. In the Zero Trust dashboard, add Public Hostname routes on that tunnel
   pointing at `http://fantasy-edge-api-1:8000` (the sportsbook/Sleeper API)
   and `http://fantasy-edge-dashboard-1:3000` (the dashboard) — container
   names, not compose service aliases, since they're reachable only because
   step 1 put `cloudflared` on the same Docker network.
3. Protect the dashboard hostname with an Access application (it has no
   login page of its own). The API's `/props`, `/signals`, `/rankings/
   {sport}`, `/parlays` routes are deliberately unauthenticated — that's the
   contract homelab-dashboard's Fantasy tile already expects
   (`src/tiles/fantasy/client.ts` there) — while `/api/v1/fantasy/*` stays
   gated behind `FANTASY_API_TOKEN` regardless of any Access layer on the
   hostname.

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
2026-09-05). The `ntfy` service in `docker-compose.yml` is self-hosted
(not ntfy.sh) and defaults to `NTFY_AUTH_DEFAULT_ACCESS: deny-all`, so a
fresh `ntfydata` volume has no users and every request 403s until this
one-time setup runs:

```bash
docker compose up -d ntfy
docker exec -e NTFY_PASSWORD='choose-a-real-password' fantasy-edge-ntfy-1 \
  ntfy user add --role=user fantasyedge
docker exec fantasy-edge-ntfy-1 ntfy access fantasyedge fantasy-edge-alerts read-write
docker exec fantasy-edge-ntfy-1 ntfy token add fantasyedge
```

Put the printed token in `.env` as `NTFY_TOKEN`, `NTFY_TOPIC=fantasy-edge-alerts`,
and `NTFY_BASE_URL=http://ntfy:80` (the container's internal address - the
app publishes over the compose network, never through the host-published
port), then `docker compose up -d --force-recreate api worker beat` so the
new env vars actually load (they're read at container start, not
hot-reloaded). Subscribe from the ntfy phone app at
`http://<this-host's-LAN-IP>:8090` (the port `docker-compose.yml`'s `ntfy`
service publishes), topic `fantasy-edge-alerts`, logging in as the same
`fantasyedge` user/password - deny-all means an unauthenticated subscribe
403s exactly like an unauthenticated publish does. This only reaches the
phone on the same LAN/VPN as the host; reaching it from elsewhere needs a
real Cloudflare Tunnel hostname (or similar) pointed at this port, which is
a separate, not-yet-done step.

Verify the whole path with a real publish, not just a healthcheck:
```bash
docker exec fantasy-edge-worker-1 python -c "
import asyncio
from src.utils.alerts import notify
asyncio.run(notify('test', title='Fantasy Edge: Test'))
"
curl -u fantasyedge:<password> 'http://localhost:8090/fantasy-edge-alerts/json?poll=1&since=all'
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
