# Release verification — September 27, 2026 (America/Chicago)

## Completed

- Reviewed the retained 288 operational observations: current heartbeat, no recorded alerts in that retained window. This is sampled monitoring, not proof of continuous error-free operation.
- Added `scripts/release_audit.py`, a read-only repository-versus-container check for API, worker, evaluation worker and beat. It compares SHA-256 fingerprints for supported code/config/migration/script files and exact installed versions against the runtime lock. It reports missing, changed and unexpected files, and exits nonzero for drift or unavailable services. It does not inspect environment files or print raw command failures.
- Before deployment, all application files and pinned installed versions matched; only the recently added runtime lock and audit script were absent from the containers.
- Rebuilt and deployed all four backend services after both Celery workers reported idle. After deployment, **all four matched across 240 files**, with no missing/changed/unexpected files or pinned dependency differences.
- Production schema is `0025_fantasy_input_revision`, the current head. Database/API health passed; capture is current and grading is not stale.
- HTTP 200 smoke checks: Fantasy 0.836s, Best Bets 0.355s, Calibration 1.891s, Experimental 0.137s, Operations 0.037s. These are individual complete-response timings; the calibration page still streams core results before finishing its readiness panel.
- Full isolated test suite: **709 passed, 1 skipped, 20 live-network tests deselected**, 43.03 seconds. New tests cover inventory exclusions, missing/changed/extra files, dependency normalization/version mismatch and standalone remote-probe syntax.

## Repeatable verification

From the repository root:

```sh
.venv/bin/python scripts/release_audit.py --context colima
```

Exit zero means every inspected backend service matched the checked repository files and pinned package versions at inspection time. This is not a signature or trusted build attestation. Supported file extensions are `.py`, `.yaml`, `.yml`, `.json`, `.toml`, `.ini`, and `.lock`; hidden files, symlinks and bytecode caches are excluded. Database migrations are checked as files, not applied by the script.

## Still open

- Frontend build provenance, base-image/OS/build-tool pinning and artifact hashes are not covered by this backend source check.
- The working tree still includes earlier uncommitted audit repairs. This follow-up does not commit or push them, claim clean repository status, or remove other edits.
- Model promotion, fantasy qualification and verified CLV still require the corresponding real prospective/settlement evidence; deployment consistency does not qualify a model.
- Authenticated remote performance and external alert delivery remain separate work. Backup remains deferred as requested.

No model parameters, eligibility gates, provider quotas, wagers or settlement rules changed in this follow-up.
