# Provider result diagnostics

Inspected all 206 forecasts marked missing-or-conflicting platform points: all were absent player IDs, not conflicting numeric scores. 195 were week three; 11 were week two. This is a coverage gap between the projection pool and league matchup result payloads, not evidence of zero points or nonparticipation.

Provider grading now retains its compatible status while adding result_blocker (absent player, nonfinite score, conflicting score), exact player/game/week identifiers, observed timestamp and matching-row count. Duplicate equal totals remain valid; null, boolean, NaN and conflicting totals do not grade. No numeric prediction logic, capture identity or eligibility threshold changes.

26 focused tests passed; backend images rebuilt and deployed. Remaining work: obtain exact league-scored official historical results for forecasted players absent from matchup feeds. Do not substitute current projections, assumed zeroes, or differently scored component totals. Week-three snapshot freshness remains subject to the existing finality delay.
