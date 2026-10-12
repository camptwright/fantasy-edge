# Historical player-result source investigation

Latest live report (October 1 02:09 UTC / September 30 local) has no final-platform-snapshot waits. Weekly counts: 15 graded, 16 missing player points, 7 awaiting finals. Provider counts: 715 graded, 219 missing/conflicting, 55 awaiting finals. No lineup simulation metrics qualified.

Bounded read-only ESPN probes used the existing configured league credentials without logging them. A targeted player-ID request combined with mSettings returned HTTP 400. The existing supported kona_player_info request with FREEAGENT/WAIVERS, limit 300 and scoringPeriodId=2 returned HTTP 200; 281 of 300 players had actual stat records explicitly bound to season 2026 and week 2. The payload omitted a top-level scoringPeriodId. This proves source availability, not reconciliation or forecast eligibility.

Added a strict parser in fantasy_player_results.py. It selects requested provider IDs, accepts only exact-season/exact-week actuals, preserves zero and negative totals, and rejects absent, invalid or conflicting records. Eleven parser/provider tests passed.

Not yet wired into production grading: collection needs a separate rule-bound result archive, finality checks, daily pacing and reconciliation against known roster totals before using missing-player scores. Historical free-agent membership may differ from current membership and a 300-player feed is not exhaustive. Do not inject these results into roster ownership, silently count missing players as zero, or claim complete coverage. The parser is source work only and was not deployed this turn.
