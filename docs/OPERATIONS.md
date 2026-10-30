# Runbook

Install the package with `python -m pip install .` in an activated virtual environment. All commands run from the repository root. DuckDB 2.0.0 is the only runtime dependency.

## Offline example

```bash
python -m fuel_radar ingest --data-dir demo-data --as-of 2026-10-30 \
  --file tests/fixtures/august_2026.csv \
  --file tests/fixtures/september_2026.csv
python -W error::ResourceWarning -m unittest discover -s tests -v
```

Fixtures are synthetic and have complete date coverage. The resulting values demonstrate behavior, not actual retail prices.

## Live archive download

```bash
python -m fuel_radar fetch --month 2026-09 --as-of 2026-10-30 --data-dir data
```

Omitting `--month` chooses the previous completed month relative to `--as-of`; omitting `--as-of` uses the current UTC date. Source observations retain their own WA calendar date. `--as-of` controls month eligibility and audit metadata, not which historical file revision is returned by the server.

The configured archive endpoint, its discovery chain, and the primary catalog's license evidence are in [SOURCES.md](SOURCES.md). Source availability is not guaranteed. Current-month ingestion is unsupported, even when a partial file is available.

Downloads have a 45-second socket timeout, up to three attempts for transient network failures/HTTP 429/server errors, and bounded backoff. The maximum response is 75 MiB; an advertised Content-Length is reconciled with received bytes. Parsing is capped at one million rows. These controls do not set a total wall-clock deadline. An unexpected response fails validation rather than becoming a fabricated sample.

## Replay retained evidence

```bash
python -m fuel_radar ingest --data-dir replay-data --as-of 2026-10-30 \
  --file data/raw/RUN_ID/source-01.csv \
  --source-url https://warsydprdstafuelwatch.blob.core.windows.net/historical-reports/FuelWatchRetail-09-2026.csv
```

Replace `RUN_ID` with the selected run's identifier. For multiple files, repeat `--source-url` in the same order as `--file`. Omit source URLs for ordinary local fixtures; the tool records their local URI accurately. A recognized archive filename in the supplied URL must agree with the file's observed month.

Use a separate data directory to inspect old revisions without replacing the current warehouse's corrected state. There is no automatic ordering between different source revisions of the same month.

The assessment date cannot precede the latest successful run's assessment date in the same warehouse. Use a fresh directory when reproducing an earlier analytical date.

## Files and consumption

| Path | Purpose |
|---|---|
| `data/downloads/` | Downloaded archive responses |
| `data/raw/<run_id>/` | Retained raw inputs and manifests |
| `data/warehouse.duckdb` | Warehouse, source metadata and audit records |
| `data/exports/latest.json` | Pointer to the last fully published generation |
| `data/exports/<run_id>/` | Four Parquet datasets and summary JSON |

Read `latest.json` once to choose a coherent output generation. Do not pick each file independently from whichever directory is newest. Raw manifests/database source records can contain local paths; they are excluded from Git. No credentials or private input data are needed.

Query the warehouse using Python:

```python
import duckdb

with duckdb.connect("data/warehouse.duckdb", read_only=True) as connection:
    print(connection.execute("SELECT * FROM daily_market_summary LIMIT 10").fetchall())
```

The statements in [analysis.sql](../sql/analysis.sql) can also be run in a DuckDB SQL client. [DATA_MODEL.md](DATA_MODEL.md) defines the metrics and denominator differences.

## Failures and recovery

1. A download failure returns a nonzero exit status before an ingestion audit row exists. Inspect the command error and partial download file; the warehouse is untouched.
2. An ingestion validation/load failure records a failed run. Raw inputs and artifacts remain; business changes roll back.
3. If the error says the load succeeded but export failed, inspect `pipeline_runs.error`. The database is committed, but the old published export pointer remains authoritative.
4. Correct the source or filesystem condition, then replay. An identical source will skip business replacement while creating a new export generation.
5. An abrupt process termination can leave a `running` record or an orphan export directory. Check for an active process before investigating. There is no automatic abandoned-run cleanup.

Run one writer per data directory. DuckDB's file locking is not a substitute for multi-worker orchestration. A backup should be taken while the writer is stopped, retaining the database and raw source directories together. Retention is explicit; this code does not automatically delete earlier evidence.

## Extension choices

Potential next steps include a scheduled refresh with alerts, reviewed source identity mappings, an object-store raw layer, a BI dashboard, and a database service for concurrent writers. A current-month mode would need explicit partial-snapshot semantics and correction/retraction rules. Wholesale/crude joins would require separately licensed evidence and a defensible comparison method. None of these extensions is claimed as deployed.
