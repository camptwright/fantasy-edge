# Dashboard build provenance — September 28, 2026

## Implemented and deployed

The dashboard image now captures a source fingerprint inventory before `next build`, then seals a manifest of the assembled standalone application and its Next build ID. The manifest remains internal to the container; no public unauthenticated endpoint or environment dump was added.

`scripts/dashboard_release_audit.py` compares local dashboard source with the embedded inventory and verifies the deployed `.next`, public assets, server entry point and package metadata against build-time hashes. It checks both the Compose dashboard and `fantasy-edge-grading-preview`. Missing manifests, missing/changed/extra artifacts, or source differences fail the check. Runtime caches and `node_modules` are excluded. Symlinks in inventoried trees fail closed.

Both deployed dashboards matched **59 source files and 148 artifacts**, build ID `39P7-0WTtLhmjrcC-zQa8`. Backend containers were rebuilt with the new audit script after workers reported idle; all four matched **241 source files** and pinned runtime dependencies. The previous local preview is retained as `fantasy-edge-grading-preview-before-20260928T121335264442`.

## Verification

- Dashboard production compilation and type checks passed.
- Dashboard tests: **13 passed**, including six provenance/integrity tests. An initial invocation from the repository root failed an existing cwd-dependent test; rerunning from `dashboard/`, its expected working directory, passed all tests.
- Full isolated Python suite: **709 passed, 1 skipped, 20 live-network tests deselected**, 40.05 seconds.
- `git diff --check` passed.
- Fantasy, Best Bets, Calibration, Experimental and Operations returned HTTP 200. Initial complete-response timings were 0.508s, 0.262s, 2.454s, 0.156s and 0.030s respectively. A subsequent streaming calibration check delivered live results in **0.169s**, completing its readiness panel at **1.095s**. These are individual observations, not load-test percentiles; the expensive readiness computation still exists.

Run from the repository root:

```sh
.venv/bin/python scripts/dashboard_release_audit.py --context colima
.venv/bin/python scripts/release_audit.py --context colima
```

## Scope and remaining work

This closes the basic frontend source/build drift gap. It is not signed provenance, reproducible-build certification, or protection against an attacker replacing both artifacts and manifests. Runtime `node_modules`, OS packages, base images and build-tool artifacts are not covered by this frontend hash inventory. The package lock is fingerprinted as a source input.

Commit/push cleanup remains open; the existing uncommitted repairs are preserved. Model parameters, promotion/eligibility gates and settlement rules were not changed. Real prospective and exact settlement evidence remain separate requirements, and backup work remains deferred as requested.
