# College lab payload repair and current NFL evidence

## Completed

The selected college lab previously sent all 981 players despite rendering one team. Added an opt-in compact API display view, selected-team URL navigation, stable player paging (default 50, maximum 100), full team options, and explicit empty-page handling. Texas is the default when present. Unknown requested teams never silently substitute another roster.

The unparameterized `/experiments/college-players` retains its full contract. Coverage, retrospective metrics and prospective summary retain their full-cohort meaning; only displayed players are restricted. Research model code, original reports, captures and qualification policy are unchanged. The separate display service avoids changing the college research recipe simply to paginate its presentation.

## Verified deployment

- Full API: 875,040 bytes / 981 players.
- Default Texas compact API: **21,530 bytes / 15 players**, about **97.5% smaller**, 0.014 seconds in one measured request.
- Alabama limit-two page: 11,876 bytes, correct next offset and 16-player team count.
- Unknown team: empty players, retained aggregate evidence, HTTP 200; limit 101 rejects with HTTP 422.
- Live assertions compared compact player objects exactly to the full report and checked unchanged coverage/metrics.
- Default college HTML: 64,557 bytes, HTTP 200 in 0.122 seconds. Alabama, unknown-team, Fantasy and Best Bets pages also returned HTTP 200. These are individual measurements, not load-test percentiles.
- **713 Python tests passed**, one skipped, 20 live-network tests deselected. **13 dashboard tests passed**. Production build/type checks and `git diff --check` passed.
- Four backend services match **242** source files and pinned dependency versions. Both dashboard deployments match **59** source inputs and **148** build artifacts, build ID `PnrxuboqCOOkjMaA8_dIo`.
- Prior preview retained: `fantasy-edge-grading-preview-before-20260928T123459632275`.

The route still reads the stored full report before projecting a bounded response. This reduces response size/client work; it does not claim fully paged disk storage or reduced model-evaluation work.

## NFL promotion evidence checked this turn

At the reviewed September 28 12:29 UTC snapshot, artifact `4664732de2c2ccfe85518e8877f32db4952006a282619e88f5a2835048d904e9` had 15 frozen forecasts, nine complete-pair captures selected, and eight graded independent games. The protocol still requires 200 independent games; 191 further qualifying captures were needed at this snapshot.

Candidate Brier: **0.22889**, retained baseline: **0.20653**. Candidate log loss: **0.64977**, retained baseline: **0.60418**. Lower is better: the candidate currently trails both, but eight games are too few for a reliable performance conclusion. No promotion, gate override or outcome-based cohort replacement was performed.

## Remaining

Commit/push cleanup, deeper build reproducibility, actual prospective qualification, verified settlement/closing evidence and authenticated remote performance remain open. Existing uncommitted work is preserved. Backup remains deferred as requested.
