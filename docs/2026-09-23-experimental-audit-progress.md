# X-01–X-03 implementation progress

Latest closure status: [September 25 follow-up](2026-09-25-experimental-closure-status.md).

This follow-up supplements the release-verification report; it does not close
all three findings or claim that the experimental model beats the market.

## Deployed and verified

- Migration `0019_model_evidence` applied to isolated test and live PostgreSQL.
- Model artifacts now retain their JSON payload in PostgreSQL. Model predictions
  retain immutable original pregame evidence: baseline, market quote binding,
  frozen blend probability, timestamps and available EPA context.
- Existing lab forecast files are imported without reconstructing or refreshing
  historical inputs. Conflicting evidence is rejected rather than overwritten.
- NFL lab grading reads the database cohort. Missing archive files no longer
  remove imported forecasts. Other forecast-grading pipelines are unchanged.
- Promotion diagnostics are appended to `model_review_evidence`, bound to the
  exact artifact version. JSON review archives remain secondary copies.
- `GET /experiments/nfl-predictor/governance` exposes the current artifact's
  durable review. A changed artifact cannot inherit the previous model's review.
- The fixed 75% lab / 25% market research candidate is evaluated against both
  the unblended lab and retained baseline, with market checks in each review.
  Weights are not optimized against prospective outcomes. This is not a fitted
  EPA model, a closing-price comparison, or a serving-model promotion.

Verification: 670 backend tests passed, 1 skipped, 20 deselected. Tests include
archive-loss recovery, repeated capture without duplication, mutation rejection,
and current-version-only review lookup. All four backend services rebuilt and
recreated. Two live registry runs each retained one frozen forecast, captured
zero replacements, and reported zero missing frozen-evidence records.

## Remaining work / gates

- **X-01:** The current artifact has zero graded prospective games. The
  200-independent-game and fixed-window gates remain closed. No deployment
  selector or automatic promotion was added; explicit reviewed promotion and
  rollback integration remains necessary after the evidence qualifies.
- **X-02:** There is no new evidence that either candidate beats the market.
  Continue collecting paired quotes and outcomes. The market blend is research
  only; compare paired performance rather than unrelated historical averages.
- **X-03:** General forecast/grade, shadow-ledger and other experimental
  archives still need durable ingestion and tested recovery. Existing raw-result
  retention remains dry-run only. No archive files were deleted. Database
  persistence does not substitute for backup and restore verification.

Existing lab captures with missing market or EPA data are not retroactively
enriched. Archive writes can still surface filesystem errors even after a review
has committed to PostgreSQL; task retries preserve the committed evidence.

## Follow-up: general forecast durability (September 23 local time)

The general forecast pipeline now commits each new snapshot to PostgreSQL before
publishing its filesystem copy. Scheduled grading imports any remaining archive
history in batches, refuses to grade an incomplete import, and grades a
repeatable-read database cohort. Grading reports commit before secondary archive
publication. `/calibration/live` reads integrity-checked database evidence.

Migrated all 1,681 historical forecast files and 865 historical grading reports;
no originals deleted. A live database-only grading run verified all forecast
hashes and produced 1,126,209 raw records / 25,884 cohort entries: 21,741 graded,
1,453 missing results, 1,501 pending, 28 pushes, 1,159 invalid timing, and two
requiring review. These are grading dispositions, not evidence of profitability.

Full-history verification exposed two issues fixed before completion:

- SQLAlchemy streaming needed an explicit single-snapshot fetch size to avoid
  buffering the entire database history into worker memory.
- JSONB normalized negative zero and broke byte-representation hashes. JSON
  storage now preserves numeric representation. Repaired 249 copies only after
  verifying original content hashes and semantic equality; no forecast values
  were changed. Regression coverage includes negative zero and exponent forms.

Migrations 0020–0022 introduce durable evidence, precision-preserving JSON, and
an indexed newest-report lookup. Recovery utility:
`python -m scripts.forecast_evidence restore /new/recovery-directory --kind forecasts`
It requires a new directory, verifies hashes, and never overwrites live archives.
Use `--kind grading` for reports. This is evidence recovery, not a tested
off-host PostgreSQL disaster-recovery backup.

Verification: 673 backend tests passed, one skipped, 20 deselected. Live health,
grading, and NFL governance endpoints returned HTTP 200. The grading report was
fresh and identified PostgreSQL as its evidence store.

### Closure status (do not mark all findings closed)

- X-01: durable artifact/prediction/review registration implemented; serving
  selection, reviewed promotion and rollback integration still outstanding.
- X-02: fixed blend comparisons are implemented; market superiority remains
  unproven and prospective qualification cannot be manufactured.
- X-03: general forecast/grade database durability and recovery implemented.
  Independent shadow archives, safe executable retention, and off-host database
  restore verification still remain. Raw retention is still dry-run; no files
  deleted. In addition, repeated legacy-directory scanning can be optimized
  after durable import completion is tracked explicitly.
