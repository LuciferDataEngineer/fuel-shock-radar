# Warehouse and metric definitions

The executable schema lives in `src/fuel_radar/pipeline.py`. `schema_version` stores version 1; unknown schema versions fail explicitly. This release initializes a new warehouse and does not include a multi-version migration framework.

## Tables

| Object | Key / grain | Fields and purpose |
|---|---|---|
| `price_observations` | `site_id`, `observed_date`, `product` | Reported price fact; `month` is the first date of the calendar month. `price_cpl` is `DECIMAL(6,1)`. Original descriptive fields and source checksum accompany each observation. |
| `source_months` | `month` | Current source assigned to each monthly partition; row count, date bounds, source URL/hash, integer revision, load timestamp and run ID. |
| `pipeline_runs` | `run_id` | Execution attempt, UTC timestamps, analytical as-of date, status, error, counts of changed/skipped months and newly loaded rows. |
| `source_artifacts` | `run_id`, `source_sha256` | Raw source origin, local path, checksum, size, captured timestamp, validated month and row count. |
| `schema_version` | `version` | Initialization/version check. |

`source_artifacts.run_id` has an enforced foreign key. Source/run references in `source_months` are maintained by the loader rather than additional database foreign keys. Fact primary-key uniqueness and the month/date relationship are enforced by DuckDB. Month and product/locality/date indexes support scoped updates and filtering.

## Source mapping

| Source CSV field | Warehouse field | Handling |
|---|---|---|
| `PUBLISH_DATE` | `observed_date`, `month` | Parse DD/MM/YYYY; the source date is a WA calendar date. |
| `TRADING_NAME` | `site_name`, derived `site_id` | Trim display text; identity normalization uppercases and collapses whitespace. |
| `ADDRESS`, `LOCATION`, `POSTCODE` | `address`, `location`, `postcode`, derived `site_id` | Used with trading name to define the reported outlet signature. Postcode remains text. |
| `PRODUCT_DESCRIPTION` | `product` | Uppercase/collapse whitespace; distinct source product labels stay distinct. |
| `PRODUCT_PRICE` | `price_cpl` | Positive finite value, exactly representable to one decimal place, within DECIMAL(6,1). |
| `BRAND_DESCRIPTION` | `brand` | Retained per fact; changing brand alone does not change identity. |
| `AREA_DESCRIPTION`, `REGION_DESCRIPTION` | `area`, `region` | Retained publisher geography labels. |
| Original file bytes | `source_sha256` | SHA-256 lineage to the retained raw file. |

All ten listed source fields are required and nonempty. Extra CSV columns are preserved in raw bytes but not modeled. Duplicate headers, duplicate normalized observation keys, malformed rows, mixed-month files, missing calendar dates, and current/future months are rejected.

## Identity is a modeling choice

`site_id` is SHA-256 of a canonical JSON array containing normalized trading name, address, locality, and postcode. It is a reporting signature, not an externally assigned physical station ID. Including trading name prevents collisions among different offers at identical addresses. Names changing across dates create new identities; matching does not guess whether these are the same business. Eligibility distinctions and co-located businesses need further reference data for reliable consolidation.

## Views

`daily_market_summary` has one row per **date, product, and locality**. It reports `site_count` (observations at that grain), median, 25th and 75th percentiles, and interquartile range. Quantiles use continuous interpolation. They describe the recorded offers and are not weighted by sales.

`matched_site_changes` has one row per current **outlet signature, product, and date** with an exact previous-day match. The self-join requires `previous.observed_date = current.observed_date - 1`. The value is `current_price_cpl - previous_price_cpl`; a missing preceding day gives no row. A date gap is never treated as a one-day change. Matching can cross month boundaries when both months are loaded.

`is_large_move` is true when the absolute change is at least 10 cents per litre. This is an illustrative fixed threshold, not a statistical detection model. Values can be positive or negative; neither implies a cause.

`matched_market_changes` aggregates the matched rows by date, product, and locality, with pair count, median/mean change, and threshold count. Its denominator differs from the distribution view because unmatched records are excluded. An empty group does not mean a zero change.

The earliest loaded date has no preceding-day evidence unless the prior month is also loaded. Coverage queries expose that boundary. A difference between two cross-sectional medians is not equivalent to a median of matched-outlet changes.

## Replacement and history semantics

A source file must contain a single completed calendar month and observations on every date in that month. Coverage does not prove all outlets were included. The loader trusts the specified source to be a full monthly snapshot; a self-consistent file missing one entire retailer can pass.

The current `source_months` checksum is compared with incoming bytes. An identical checksum skips business-table changes. A different checksum causes delete-and-insert for that month within a transaction, increments the partition revision, and leaves other months untouched. Reordered or otherwise byte-different but logically equal input causes a revision; idempotency is byte-based.

This is latest-snapshot partition replacement, not row-level CDC or a bitemporal fact store. Earlier source bytes and audit artifacts remain, but prior fact revisions require replay into a separate directory. If an older full-month source is intentionally supplied later, it can replace a newer correction: source revision ordering is not independently known, and `as_of` does not reconstruct historical truth.

Assessment dates may not move backward relative to the warehouse's latest successful run. This prevents a whole-warehouse summary from displaying a historical as-of date while containing later observations. Loading an older source month remains valid with the current assessment date; historical assessments use a separate data directory.

## Publication boundary

Run audit and source metadata are saved before the transaction. All monthly fact/metadata replacements and load-success status commit together. Failed validation or loading leaves the previous business state intact.

Exports are derived after commit. All four Parquet files and summary JSON go into a new run-specific directory. Only after every file succeeds is `exports/latest.json` atomically replaced. Consumers should read that pointer once and use that generation. An export failure leaves the old pointer intact, records an error on the successful load, and returns a nonzero command exit status; replay safely regenerates exports.
