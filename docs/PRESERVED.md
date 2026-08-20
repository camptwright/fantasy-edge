# Preserved through the NFL rebuild

Five artifacts survived the 2026-08-20 clean slate. Each encodes either a
production incident or a fact verified against a live source.

| Artifact | What it encodes |
|---|---|
| `CLAUDE.md` constraints | Production incidents, chiefly #1 and #22 (forked-process asyncpg and Redis event-loop sharing). #22 surfaced only on a task's *second* scheduled run, which single-invocation smoke tests cannot reach. |
| `src/utils/odds_math.py` | American/decimal/implied conversion and proportional vig removal. |
| `src/utils/normalize.py` | Statistic-type normalization at ingest (constraint #8), which is what makes cross-source joins align. |
| `src/data/providers/underdog_api.py` | Constraint #17: the five-sibling-array response shape, verified against 3,841 live lines on 2026-08-02. |
| `config/team_aliases/nfl.yaml` | Constraint #24: fetched live from ESPN 2026-08-06, including the quoted `"NO"` entry that otherwise parses as boolean `False`. |

`tests/test_preserved.py` is the tripwire protecting these.
