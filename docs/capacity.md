# CT100 capacity baseline: flower removal

CT100 (Proxmox LXC 100, reached via `ssh root@192.168.8.109 "pct exec 100 -- <cmd>"`)
runs the Fantasy Edge stack from its current `main`-based deployment. This
records the memory impact of removing the `flower` Celery-monitoring
container, which held a 256 MiB `mem_limit` on an already-swapping host and
provided no value that Uptime Kuma's liveness checks don't already cover.

## Before (2026-08-22, prior to removal)

```
$ ssh root@192.168.8.109 "pct exec 100 -- free -m; pct exec 100 -- docker ps --format '{{.Names}}'"
               total        used        free      shared  buff/cache   available
Mem:            2048        1257         244         100         647         790
Swap:           2048         478        1569
fantasy-edge-dashboard-1
fantasy-edge-worker-1
fantasy-edge-beat-1
fantasy-edge-api-1
fantasy-edge-flower-1
fantasy-edge-postgres-1
fantasy-edge-redis-1
```

Seven containers running. Used: 1257 MiB. Available: 790 MiB. Swap in use:
478 MiB.

(A prior 2026-08-20 reading from the task brief recorded 1140 MiB used, 907
MiB available, 481 MiB swap, seven containers — consistent with this
snapshot within normal fluctuation.)

## Change applied

```
ssh root@192.168.8.109 "pct exec 100 -- docker stop fantasy-edge-flower-1"
ssh root@192.168.8.109 "pct exec 100 -- docker rm fantasy-edge-flower-1"
```

Both commands succeeded, each echoing back the container name
`fantasy-edge-flower-1`.

## After (2026-08-22, following removal)

```
$ ssh root@192.168.8.109 "pct exec 100 -- free -m; pct exec 100 -- docker ps --format '{{.Names}}'"
               total        used        free      shared  buff/cache   available
Mem:            2048        1093         356         100         698         954
Swap:           2048         448        1599
fantasy-edge-dashboard-1
fantasy-edge-worker-1
fantasy-edge-beat-1
fantasy-edge-api-1
fantasy-edge-postgres-1
fantasy-edge-redis-1
```

Six containers running (flower is gone). Used: 1093 MiB. Available: 954
MiB. Swap in use: 448 MiB.

## Result

- **Available memory**: 790 MiB -> 954 MiB, a gain of 164 MiB. This is
  comfortably above the ~400 MiB floor the task specified as the point to
  stop and flag for an owner decision on raising CT100's allocation — no
  such escalation is needed.
- **Swap**: 478 MiB -> 448 MiB, a drop of 30 MiB. Swap use is not expected
  to track memory release 1:1 — Linux leaves pages in swap until they are
  next touched, so an unchanged swap figure immediately after removal would
  have been expected and would not have indicated the change failed. The
  small observed drop here is incidental, not the metric this change was
  judged against; **available memory is the number that matters**, and it
  improved.
- **Containers**: seven -> six. `fantasy-edge-flower-1` no longer exists on
  the host.
