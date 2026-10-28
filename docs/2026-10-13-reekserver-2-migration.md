# Moving Fantasy Edge to Reekserver-2 (feasibility, 2026-10-13)

**Verdict: feasible and low risk.** Reekserver-2 has the room (RAM, disk,
Docker, no port clashes) and the repo's compose override already uses its
`/home/reek/apps/fantasy-edge/...` paths. The one real decision is how the
app reaches the local model once the Mac mini is the AI machine: the
router blocks Reekserver-2 → Mac connections today (details below).

## What was measured

| | Mac mini (today) | Reekserver-2 |
|---|---|---|
| Hardware | Apple M4, 16 GB, 460 GB SSD | Intel i5-8400T (6 cores, AVX2), 31 GB, 954 GB NVMe + 1 TB USB HDD |
| OS / runtime | macOS, Colima VM (4 CPU, **8 GB RAM reserved**, 200 GB disk, 105 GB used) | Debian 13, Docker 29.8 + Compose 5.5 (user `reek` is in the `docker` group) |
| Free | 235 GB disk | 463 GB NVMe, 453 GB HDD, 25 GB RAM available, load ~0.3 |
| Already running | this app (14 containers) + native Ollama | 23 containers (media stack, Jellyfin, Open WebUI, Ollama with llama3.2:3b, cloudflared, chisel server, monitoring) |

App footprint to move:

- Postgres data directory 4.1 GB (database ~2.6 GB);
- raw archive volume 36.4 GB (compresses further as the retention job drains);
- Redis 41 MB, models/logs < 1 MB;
- images ~17 GB, rebuilt on the server rather than copied; base images
  (`python:3.12-slim`, `node:22-slim`, `postgres:16-alpine`,
  `redis:7-alpine`) and the pinned LiteLLM digest are all multi-arch
  (amd64 + arm64 verified).

Running memory is ~2.5 GB (Postgres 650 MB, LiteLLM 1.1 GB, workers
~400 MB), with low steady CPU. No published ports conflict: the main stack
publishes none, and the preview's `127.0.0.1:13001` is free on Reekserver-2.

## What the Mac mini gets back

- **8 GB of RAM** that the Colima VM reserves today. With all 16 GB, the M4
  can run a 14B model at 4-bit (~9 GB) with Metal, which a 16 GB machine
  sharing RAM with a Linux VM cannot.
- **~110 GB of disk**: the Colima VM (105 GB), plus the build cache and
  images inside it. Free space goes from 235 GB to ~345 GB.
- 4 CPU cores and the VM's background I/O.

## Speed on the new host

- Background jobs are I/O- or network-bound (ESPN polls ~1 s, nflverse
  ~20 s), so the i5 is fine for them. CPU-heavy research jobs (projection
  engine, 10k-season simulations, trade finder) will run roughly 1.5–2×
  slower per core than on the M4. That is acceptable for scheduled work, but
  worth watching on the 15-minute prospective-capture cadence.
- **Local model:** the parlay parse prompt takes about 14 s on Reekserver-2's
  CPU (llama3.2:3b, 8 tok/s) against 1–5 s on the M4. That is usable as a
  fallback but not as the main AI box, which is why the plan keeps the model
  on the Mac.

## The network catch

Reekserver-2 (192.168.20.137) cannot open connections to the Mac
(192.168.10.10). Ping gets "host unreachable" and TCP gets "connection
refused" on every port, while Mac → Reekserver-2 works. That points to a
router/VLAN rule blocking servers from reaching the Mac's network. Two ways
to let the app reach the Mac's Ollama:

1. **Reverse tunnel from the Mac (no router change).** Reekserver-2 already
   runs `chisel server --reverse` on port 9312. A small launchd job on the Mac
   runs `chisel client reekserver-2:9312 R:11434:localhost:11434` with the
   existing auth. LiteLLM then uses
   `OLLAMA_BASE_URL=http://host.docker.internal:11434` (or the chisel
   container's address). Recommended.
2. **Router rule.** Allow 192.168.20.137 → 192.168.10.10:11434 only. This is
   simpler at runtime, but it is a firewall change the owner must make.

Either way the app degrades safely: the parlay generator already falls back
to its keyword parser when the model is unreachable. LiteLLM could also list
Reekserver-2's own Ollama as a fallback deployment for the `fast` alias.

## Cutover plan (about 45 minutes of downtime, best on a Tuesday or Wednesday)

1. **Prepare (no downtime):** on Reekserver-2, `git clone` the repo to
   `~/apps/fantasy-edge-src`. Copy `.env` over with `scp`, then edit
   `OLLAMA_BASE_URL`. Create `/home/reek/apps/fantasy-edge/{postgres,redis,models,logs}`
   and `chown 1001:1001` models and logs (constraint #18), using a throwaway
   root container since `sudo` needs a password:
   `docker run --rm -v /home/reek/apps/fantasy-edge:/d alpine chown -R 1001:1001 /d/models /d/logs`.
   Run `docker compose build`.
2. **Pre-seed the raw archive (no downtime):** rsync the `fantasy-edge_rawdata`
   volume to Reekserver-2 while the app keeps running. Any tar/rsync from
   macOS must use `COPYFILE_DISABLE=1` (constraint #15).
3. **Stop the Mac stack:** `docker --context colima compose stop beat worker evaluation api dashboard`.
   Keep Postgres up.
4. **Move the database logically.** A physical copy from arm64 to x86_64 is
   not supported by Postgres, so run
   `pg_dump -Fc` (~2.6 GB, a few minutes), copy it, start only `postgres` on
   Reekserver-2, `pg_restore`, then `alembic upgrade head` (constraint #13
   practice) and spot-check row counts against the source.
5. Run a final incremental rsync of the raw archive, then copy
   `models/celerybeat-schedule`, so beat keeps its last-run times.
6. **Start on Reekserver-2:** `docker compose up -d` for the main stack, plus
   `-f docker-compose.workspace.yml`. Move the tunnel by starting the app's
   `cloudflared` container there with the same tunnel token and stopping the
   Mac's. Cloudflare Access stays as is, because the hostname and tunnel are
   unchanged.
7. **Verify:** API health, a workspace overview snapshot refresh within 2
   minutes, beat firing (ESPN poll), prop board refresh, a parlay generation
   through the Mac's model, and Cloudflare Access login.
8. **Keep the Mac stack stopped, not deleted, for a week as rollback.** Then
   run `colima delete` to reclaim the disk and RAM.

**Rollback:** stop Reekserver-2's stack and `cloudflared`, then start the Mac
stack. Anything written on Reekserver-2 after the cutover would be lost unless
dumped back, so decide within the first day.

## Things that would bite

- Postgres data files are architecture-dependent: always dump and restore,
  never copy the directory.
- Bind-mount ownership (#18): healthy containers give no sign of it until the
  first model or log write fails.
- macOS AppleDouble files in any tarball (#15) break alembic's import of
  `alembic/versions/*.py`.
- Two `cloudflared` connectors on one tunnel would split traffic between
  hosts. Stop the Mac's before starting the new one.
- Reekserver-2 also hosts the media stack. Postgres's 1 GB memory cap
  and the workers' limits in the compose file still apply, so the app cannot
  starve Jellyfin.

## Further research (2026-10-18)

All checks were read-only, apart from one throwaway container that was
removed afterwards; the server was left as found.

- **The Mac's AI models are already reachable from the server.** The tunnel
  that option 1 recommended is already running: launchd job
  `com.camptwright.chisel-ollama-tunnel` runs
  `~/.local/chisel/run-client.sh`. On the server's `ai-net` network,
  `http://chisel-server:11434/api/tags` lists the Mac's qwen3.5:9b and
  llama3.2:3b. After the move, LiteLLM joins `ai-net` as an external
  network and uses `OLLAMA_BASE_URL=http://chisel-server:11434`. No router
  change is needed.
  - The server's own `ollama` container (llama3.2:3b, also on `ai-net`) can
    serve as LiteLLM's fallback when the Mac is asleep or off.
- **Host.** Debian 13, x86_64, 6 cores, 31 GB RAM (25 GB available), 462 GB
  disk free. Load average 0.4 across 23 containers; qbittorrent is the
  largest at 4.9 GB.
- **Sizes today.** Database 2.9 GB, raw archive 15 GB (it was about 13 GB
  on 10-13), models directory 0.5 MB.
- **Transfer speed.** The Mac sends to the server at about 110 MB/s
  (gigabit; 1,000 MB in 9 s over ssh).
  - The raw archive pre-seed takes about 2.5 minutes and runs before the
    downtime.
  - The dump copy takes under a minute.
  - So `pg_dump`/`pg_restore` sets the downtime; the 45-minute estimate
    stands.
- **Postgres memory.** It uses 762 MiB of its 1 GiB cap on the Mac. Raise
  the cap to 2 GiB on the server, which has room.
- **Same numbers on the new chip.** The four largest v2 fits were captured
  on the Mac (arm64), recomputed on the server (x86_64, numpy 2.5.3 in a
  removed `python:3.12-slim` container) and compared:
  - largest coefficient difference 6e-13, largest prediction difference
    6e-13;
  - records round to 4 decimals and v2's version id doesn't depend on the
    chip, so the move doesn't break its record;
  - the decision cohort's identity covers Python and package versions, not
    the chip, so it carries over as long as the image is the same.
- **Still to confirm during prep.** The pinned LiteLLM digest has an amd64
  image (`docker compose build`/`pull` on the server will show it).
- **Credential.** The chisel server's auth string was printed once in this
  session's local tool output while being inspected. It never left the
  machine, but rotating it costs little: update the server's `--auth` and
  `~/.local/chisel/run-client.sh` together.
- **Owner decisions still open.** Only the date now. Recommended: Wednesday
  2026-10-28, after week 7's grading and before Thursday's captures.

## Status check (2026-10-26)

Read-only again; the one temporary image pulled on Reekserver-2 for a curl
check was removed.

- **The Mac stack is healthy.** It restarted on its own after the Mac
  rebooted (about 11 hours earlier). In the last 12 hours there were 1,581
  job runs, all succeeded or deferred, none failed. The database is now
  3.7 GB and the raw archive 19.9 GB.
- **Reekserver-2 is still the right host.**
  - Free disk is 358 GB, down from 463 GB on 10-18 (media growth), with
    26 GB RAM available and load 0.3.
  - Ports, Docker 29.8 and Compose 5.5 are unchanged.
  - `/home/reek/apps/fantasy-edge` does not exist yet.
- **Reekserver-1 is not a fit for the main stack.** It has an Intel N95
  (4 cores) with 7.6 GB RAM, about 4 GB of it available, and already runs
  21 containers (monitoring, ntfy, adjutant, marketdesk). The app's memory
  caps total about 7 GB, and its real use is about 2.5 GB. Reekserver-1
  keeps its current role: ntfy, uptime monitoring and Grafana for this app.
- **The LiteLLM digest is multi-arch.** The pinned index includes
  linux/amd64 (checked against the ghcr registry), so the 10-18 open item is
  closed.
- **The tunnel to the Mac's models still works.** On `ai-net`,
  `chisel-server:11434` lists the Mac's `qwen3.5:9b` and `llama3.2:3b`.
  Reekserver-2 → Mac is still blocked directly, as expected.
- **ntfy stays reachable.** Reekserver-2 can reach `192.168.20.10:8095`,
  so `NTFY_BASE_URL` needs no change.
- **New catch 1: Reekserver-2 cannot pull the repo from GitHub.** It has no
  GitHub host key and no deploy key. Instead, copy the code from the Mac
  (`git bundle create` then `scp`, or rsync of a `git archive` with
  `COPYFILE_DISABLE=1`, constraint #15). No new credential is needed.
- **New catch 2: the tunnel also carries `ollama-mac.camptwright.com`.**
  Per DEPLOYMENT.md, the same Cloudflare tunnel routes that hostname to the
  Mac's native Ollama. Moving the app's `cloudflared` to Reekserver-2 would
  break that route, and running a connector on both hosts would split
  traffic. Before cutover, the owner picks one:
  1. In Zero Trust, repoint `ollama-mac` to `http://chisel-server:11434`
     and join the new `cloudflared` to `ai-net`. One tunnel, but it depends
     on the chisel client on the Mac.
  2. Move `ollama-mac` to a separate small tunnel that stays on the Mac.

## Cutover done (2026-10-27)

The app now runs on Reekserver-2 from `~/apps/fantasy-edge-src`. The
server's `.env` sets `COMPOSE_FILE` to load `docker-compose.reekserver-2.yml`
after the base and override files, so plain `docker compose up -d` works
there. Downtime ran from 21:14 to 21:25 CDT, about 11 minutes, much shorter
than the 45-minute estimate.

- **Data.**
  - `pg_dump -Fc` came to 1.1 GB and was piped straight to the server in
    2 minutes.
  - `pg_restore -j 4` took 4.5 minutes. It has to read from a file inside the
    container, because parallel restore can't read stdin.
  - Exact counts matched for games, players, prop lines, ingestion runs,
    recommendation snapshots and leagues. Alembic is at `0031_never_drop`.
  - Redis was copied as files (22 keys, including the Odds API quota and SGO
    spend counters), so paid budgets carried over.
  - The raw archive was pre-seeded on 10-26, then topped up with files changed
    since. Files the Mac's retention job deleted after the pre-seed (1,721)
    are still on the server until retention reaches them there.
- **Tunnel.** compose now runs `cloudflared` with the token from `.env`
  (`CLOUDFLARE_TUNNEL_TOKEN`), so it is no longer on a command line. The
  Mac's hand-run connector is stopped.
- **Two catches.**
  1. **Bind-mount ownership (#18) again.** Extracting a tar of the Mac's
     models directory reset the target directory to root, and beat died with
     `Permission denied: .../celerybeat-schedule`. The fix was
     `chown -R 1001:1001` after the copy. Beat now uses the models bind
     mount like the other services; on the Mac it used the `modeldata`
     volume.
  2. **The Mac's Ollama 403s non-local Host headers.** After the Mac
     rebooted, Ollama listened on 127.0.0.1 only, and in that mode it
     rejects `Host: chisel-server:11434`; it accepts localhost, `*.local` and
     `*.internal`. LiteLLM therefore reaches it as `mac-ollama.internal`, an
     `external_links` alias for `chisel-server`.
     - For the same reason, the `ollama-mac.camptwright.com` route needs
       its HTTP Host Header set to `localhost:11434` in Zero Trust.
- **Verified:**
  - `/health`, and the NFL and NBA prop boards (200).
  - 168 job runs succeeded in the first 20 minutes, none failed.
  - The tunnel registered four connections.
  - `sports.camptwright.com` redirects to the Access login.
  - `sports-api.camptwright.com/health` returns 200.
  - A `fast` model call through LiteLLM to the Mac took 2.9 s.
  - An ntfy alert was delivered.
  - The workspace preview answers on the server's `127.0.0.1:13001`.
- **Not moved.** The Mac-only grading preview (`127.0.0.1:13000`) is
  stopped.
- **Rollback until 2026-11-03.** The Mac stack is stopped, not removed. To go
  back, stop the server's stack and `cloudflared`, then start the Mac's
  containers. After that date, `colima delete` frees the Mac's RAM and disk.
