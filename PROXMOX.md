> **Superseded 2026-08-29, deployment target corrected 2026-09-10.**
> Proxmox and CT100 are fully decommissioned. Deployment briefly moved to
> reekserver-1 per `DEPLOYMENT.md`, but as of the 2026-09-10 homelab audit
> actually runs via plain `docker compose` directly on the Mac mini
> (192.168.10.10) — `DEPLOYMENT.md`'s reekserver-1-specific steps (shared
> tunnel, `/home/reek/apps/...` path) are themselves now stale; see that
> file's own note. This file is kept only as the historical record of the
> RAM-budget and backup-cron lessons learned on CT100; none of the
> `pct exec`/Proxmox-specific steps below apply anymore.

# Fantasy Edge — Proxmox deployment runbook

## Infrastructure

| | |
|---|---|
| Proxmox host | `192.168.8.109` (`reekserver`), PVE 9.2.5 |
| Container | CT 100 `fantasy-edge`, `192.168.8.140`, Ubuntu 24.04, 3 cores / 2048MB / 40GB (verified live via `pct config 100`, 2026-08-22 - see `docs/capacity.md`; an earlier 4096MB figure here was stale/wrong) |
| Access | through Proxmox — `ssh root@192.168.8.109 "pct exec 100 -- ..."` |
| Code | `/opt/fantasy-edge` |
| Data | `/mnt/data/fantasy-edge/{postgres,redis,models,logs}` (bind-mounted, survives container rebuilds) |

Created with `nesting=1,keyctl=1` (Docker-in-LXC), `net0 ip6=auto` (never
`ip6=dhcp` — see the homelab repo's CLAUDE.md for what that breaks).

## First-time setup

1. Create/verify the LXC exists with the settings above.
2. Deploy code (from a Mac, `COPYFILE_DISABLE=1` per constraint #15):
   ```bash
   cd fantasy-edge
   COPYFILE_DISABLE=1 tar czf - \
     --exclude='.venv' --exclude='.git' --exclude='__pycache__' \
     --exclude='dashboard/node_modules' --exclude='dashboard/.next' \
     --exclude='.env' --exclude='._*' . \
     | ssh root@192.168.8.109 "pct exec 100 -- bash -c 'mkdir -p /opt/fantasy-edge && cd /opt/fantasy-edge && tar xzf -'"
   ```
3. Bootstrap the host (Docker, Node, nginx, systemd unit, backup cron):
   ```bash
   ssh root@192.168.8.109 "pct exec 100 -- bash -s" < scripts/proxmox_bootstrap.sh
   ```
4. Create `.env` on the LXC from `.env.example` (never on the Mac — see the
   homelab repo's secrets-handling rule, which applies here too). At minimum
   set `POSTGRES_PASSWORD`. `LITELLM_BASE_URL` and `LITELLM_API_KEY` point
   parlay generation at CT110's shared gateway (`FANTASY_MODEL_ALIAS=worker`);
   `ODDS_API_KEY`, `DISCORD_WEBHOOK_URL`, `CFBD_API_KEY` are optional at first boot — their
   absence degrades specific features cleanly (see CLAUDE.md "Known gaps"),
   it doesn't crash the stack.
5. Bring the stack up and migrate:
   ```bash
   pct exec 100 -- bash -c 'cd /opt/fantasy-edge && docker compose up -d && \
     docker compose run --rm -T api alembic upgrade head'
   ```
6. Seed historical data and train initial models per sport (optional
   dependency group — `pip install .[historical]` inside the container, or
   run seeding for sports whose loaders need no extra package):
   ```bash
   docker compose run --rm -T api python -m scripts.seed_historical --sport nfl --seasons 2023 2024
   docker compose run --rm -T api python -m scripts.train_models --sport nfl --seasons 2023 2024
   ```
7. Verify: `curl http://192.168.8.140/api/health`, `curl http://192.168.8.140/`
   (dashboard).

## Redeploying after a code change

Same tar-over-ssh push as step 2, then:
```bash
pct exec 100 -- bash -c 'cd /opt/fantasy-edge && docker compose build && docker compose up -d'
```
Migrations don't auto-run on `up -d` — re-run step 5's `alembic upgrade head`
line after any schema change.

## Operational notes

- **RAM budget**: compose `mem_limit`s currently sum to ~4,480 MiB
  (postgres 1024 + redis 384 + api 768 + worker 1536 + beat 256 + dashboard
  512) against CT100's actual **2048 MiB** allocation (verified live via
  `pct config 100` and `free -m`, 2026-08-22 — see `docs/capacity.md`; this
  doc previously and incorrectly said "the container's 4GB"). `mem_limit`
  is a per-container ceiling, not a reservation, so services don't all hit
  their cap simultaneously in practice — but budgeted capacity is now
  documented as over 2x the box's real RAM, not comfortably under it as
  this note used to claim. `docker compose ps` + `docker stats` are the
  first check if something OOMs; `docs/capacity.md`'s own `free -m`
  readings already show CT100 actively swapping, so this is not a
  theoretical concern.
- **Backups**: `/usr/local/bin/fantasy-edge-backup.sh` runs at 05:00 daily
  via cron, `pg_dump`s to `/opt/backups/fantasy-edge/`, keeps 7 days. It does
  NOT back up `/mnt/data/fantasy-edge/models` — those are regenerable via
  `scripts/train_models.py`, not source data.
- **Logs**: `docker compose logs worker -f` is the first move for anything
  Celery-related — constraint #1 violations show up there as asyncio/
  connection errors, not as a crash.
