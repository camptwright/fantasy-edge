# Storage review: Postgres, the raw archive, and the alternatives (2026-10-13)

Question: would S3-compatible object storage (RustFS, MinIO), DuckDB, SQLite or
another engine serve this app better than Postgres + files on disk?

Short answer: no engine change. The size and growth problems are write
amplification (full cumulative copies written every run) and a stalled
compressor, not the choice of database. Fix those; add off-host backups.

## What is stored (measured)

**Postgres — 4.2 GB**

| Table | Size | Notes |
|---|---|---|
| forecast_archives | 3.1 GB | `archive_index` 1.55 GB (1,332 full copies of a file-signature cache, only the newest read), `forecasts` 804 MB, `grading` 533 MB |
| player_game_stats | 782 MB | 3.48 M rows (stat per player-game); both indexes heavily used (25.6 M / 435 k scans) |
| everything else | < 0.3 GB | |

**Raw archive — 57 GB of JSON on the VM disk (73 of 197 GB used)**

| Directory | Size | Files |
|---|---|---|
| result-observations | 23.4 GB | 54,112 (17,086 gzipped) |
| fantasy-prospective | 6.4 GB | 21,043 |
| roster-evidence | 6.2 GB | 69 (~90 MB each, none gzipped) |
| grading | 4.6 GB | 1,683 |
| forecasts | 3.8 GB | 3,204 |

gzip measured 16–27× on these files. The hourly compressor that should have
done it was one of the jobs reset by every redeploy (beat schedule fix,
2026-10-12); it now drains about 2 GB an hour.

**Hot reads are small.** The 30-minute grading job's biggest scan (2,721
Sleeper projection files) takes 0.06 s in Python and 0.13 s in DuckDB.

## Options

- **Postgres (keep).** The app relies on what it gives: unique-index dedup
  and `ON CONFLICT` (constraints #6, #7, #16), expression indexes (#13),
  advisory locks, and several Celery workers plus the API writing at once.
- **SQLite (no).** One writer at a time; concurrent workers would serialize
  or fail. Fine for a per-process cache, not the system of record.
- **DuckDB (not for serving; optional for research).** Excellent for
  scanning Parquet/JSON in research scripts, but our measured scans are
  already sub-second. Revisit if a backtest or report scan grows past
  seconds.
- **S3-compatible object storage (RustFS 1.0 GA Sept 2026, MinIO, Garage).**
  On the same disk it adds a service without adding durability. Our
  create-only writes need `If-None-Match: *` (MinIO documents it; RustFS
  does not yet). The real value is **off-host durability**: back up the raw
  archive and nightly `pg_dump`s to object storage on another machine or a
  provider (restic/rclone to B2, R2, or a RustFS/MinIO box).
- **Parquet for cold archives (later).** Converting old JSON to Parquet
  would allow column scans, but gzip already gives similar size; not worth
  a migration now.

## Fixes made and recommended

1. **Done:** the archive file-signature index is one updatable row per
   directory (it was a full copy appended every run).
2. **Done:** beat schedule persists, so the compressor and daily jobs run.
3. **Pending your approval:** delete the 1,332 old `archive_index` copies in
   `forecast_archives` (≈1.55 GB; only the newest was ever read, and it is
   now copied into the new index row), then `VACUUM FULL forecast_archives`
   (brief table lock) to return the space.
4. **Recommended:** write deltas instead of full cumulative reports for
   `grading`, `forecasts` and `roster-evidence` (each run currently rewrites
   everything; e.g. the last 200 grading files are 739 MB). This changes the
   evidence format, so it is an owner decision.
5. **Recommended:** off-host backups (see above). Today everything lives on
   one VM disk.

## Sources

- RustFS 1.0 GA: https://linuxiac.com/rustfs-1-0-s3-compatible-object-storage-reaches-ga/
- RustFS pre-GA assessment: https://sealos.io/blog/what-is-rustfs/
- S3 conditional writes: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html
- MinIO conditional writes: https://www.min.io/blog/leading-the-way-minios-conditional-write-feature-for-modern-data-workloads
- DuckDB JSON reader: https://duckdb.org/2023/03/03/json.html
- DuckDB alongside Postgres: https://motherduck.com/learn/duckdb-vs-postgres-embedded-analytics.md
