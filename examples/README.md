# Dated execution evidence

- `live-summary-2026-10-30.json`: observed result of downloading and loading the September 2026 archive.
- `live-source-manifest-2026-10-30.json`: actual archive endpoint, checksum, size, capture timestamp, and attribution.
- `sql-results-2026-10-30.json`: aggregate, coverage, lineage, and audit outputs for the six queries in `sql/analysis.sql`, after identical-source replay.
- `validation.json`: tests, package execution, full-row replay comparison, and four live Parquet reconciliations.
- `synthetic-summary.json`: deliberately fictional August/September fixtures from `tests/fixtures/`.

Source attribution: Government of Western Australia, FuelWatch Historic Fuel Prices, CC BY 4.0. Normalization, derived identities, and aggregation are performed by this project. See [SOURCES.md](../docs/SOURCES.md) for the archive discovery chain and its verification limits.

Raw downloaded CSV files, local databases, and generated Parquet files are retained locally and excluded from Git. Current server responses may differ after upstream corrections. Exact replay requires the same retained bytes and assessment date.
