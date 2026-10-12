# Matchup coverage and provenance repair

Implemented and deployed locally (September 28 Chicago / September 29 UTC).

- Preserve unresolved starter slots instead of silently omitting them.
- Keep missing official scores null; actual zero remains zero.
- Expose available/total starter estimate coverage; incomplete totals remain null.
- Display provider versus conditional-on-participation history estimates instead of the legacy `model n/a` label.
- Use the selected league's platform rather than hardcoded Sleeper branding.

Validation: 17 focused fantasy/parlay tests passed, TypeScript check passed, production dashboard build passed. Live browser confirmed the first Sleeper matchup and history provenance on its bench. Authenticated API checks returned 200 for all three leagues: both sides covered 9/9, 11/11, and 9/9 starters respectively. Sequential post-deploy API times were 1.318s, 1.484s, and 0.852s; these are spot checks, not a latency distribution or proof that site-wide lag is resolved.

No prediction math, probability qualification, betting eligibility, or promotion gates changed. Complete starter estimates are not validated matchup win probabilities. Missing history elsewhere, broader navigation profiling, table consolidation, and model refinement remain separate work.
