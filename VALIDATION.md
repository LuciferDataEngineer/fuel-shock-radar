# Executed validation

Validated **30 October 2026** with **Python 3.14.7** and **DuckDB 2.0.0**. See [machine-readable evidence](examples/validation.json). These are observed results, not performance or production-readiness claims.

## Offline acceptance

```bash
python -W error::ResourceWarning -m unittest discover -s tests -v
```

**18 tests passed** with resource warnings treated as errors. Tests cover decimal prices, nonfinite/nonpositive/inexact values, duplicate identities, missing required fields, full calendar coverage, current/future-month rejection, mixed-month files, and URL/month mismatch.

They also verify byte-identical replay, scoped corrected-month replacement, name/brand identity semantics, changing sample composition, and exact previous-day matching across missing observations. Backward assessment dates fail without changing trusted data; older-month backfills at the current assessment date remain valid.

An injected failure during the second month verifies that the first month's writes also roll back. A fault during Parquet export verifies the previous `latest.json` pointer remains unchanged, the committed load records an export error, and a retry safely publishes a complete generation.

## Live download and ingestion

```bash
python -m fuel_radar fetch --month 2026-09 --as-of 2026-10-30 --data-dir data/verified
```

| Observed property | Value |
|---|---:|
| Source month | September 2026 |
| Source observations | 101,303 |
| Calendar dates represented | 30 |
| Derived reported outlet identities | 998 |
| Fuel product labels | 7 |
| Exact consecutive outlet/product pairs | 97,893 |

The CLI fetched the configured archive and loaded it successfully. [Summary](examples/live-summary-2026-10-30.json) and [manifest](examples/live-source-manifest-2026-10-30.json) preserve the response's source URL, hash, size, capture time, and attribution. The source-link discovery limitation is explained in [SOURCES.md](docs/SOURCES.md); a successful download alone does not independently establish storage ownership.

## Replay and exports

The retained live September file was replayed into the same warehouse with the same assessment date. It reported **0 loaded months and 1 skipped month**. Ordered full-row digests of `price_observations` and `source_months` were identical before and after. Execution/source audit rows and a new export generation were expected to be added.

All four live Parquet datasets were compared with their corresponding warehouse table/view in both directions using `EXCEPT ALL`. **Zero mismatched rows** were found:

| Export | Rows |
|---|---:|
| `price_observations` | 101,303 |
| `daily_market_summary` | 57,542 |
| `matched_site_changes` | 97,893 |
| `matched_market_changes` | 55,610 |

All six statements in [analysis.sql](sql/analysis.sql) executed successfully. [Recorded query results](examples/sql-results-2026-10-30.json) use the verified warehouse and preserve each query's denominator and date context.

## Packaging and example

The package was built into a wheel, installed without editable mode in a virtual environment, and its offline CLI executed successfully. The two fictional fixtures produce **67 observations** across August and September, **4 reporting identities**, and **62 exact consecutive pairs**. See [synthetic summary](examples/synthetic-summary.json). These are demonstration values, not public fuel prices.

## CI and limits

The [workflow](.github/workflows/ci.yml) installs the package and runs the offline suite on Python 3.11 and 3.14. The README badge and Actions page show remote CI results independently from local evidence.

No concurrent-writer test, production load benchmark, current-month mode, streaming infrastructure, hosted dashboard, or wholesale/crude attribution analysis is claimed. Coverage checks cannot establish that every retailer submitted every product/day. Historical source revisions must be deliberately selected for replay.
