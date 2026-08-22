# Fantasy Edge — Proxmox deployment runbook

## Infrastructure

| | |
|---|---|
| Proxmox host | `192.168.8.109` (`reekserver`), PVE 9.2.5 |
| Container | CT 100 `fantasy-edge`, `192.168.8.140`, Ubuntu 24.04, 3 cores / 4096MB / 40GB |
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

- **RAM budget**: compose `mem_limit`s sum against the container's 4GB (see
  CLAUDE.md) — fine idle, trim before all services run simultaneously under
  load. `docker compose ps` + `docker stats` are the first check if
  something OOMs.
- **Backups**: `/usr/local/bin/fantasy-edge-backup.sh` runs at 05:00 daily
  via cron, `pg_dump`s to `/opt/backups/fantasy-edge/`, keeps 7 days. It does
  NOT back up `/mnt/data/fantasy-edge/models` — those are regenerable via
  `scripts/train_models.py`, not source data.
- **Logs**: `docker compose logs worker -f` is the first move for anything
  Celery-related — constraint #1 violations show up there as asyncio/
  connection errors, not as a crash.
