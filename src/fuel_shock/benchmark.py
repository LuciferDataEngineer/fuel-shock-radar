"""Compare DuckDB and pandas for the serving queries behind the dashboard.

The write-up in the README uses ``benchmarks/latest.json``. ``--quick`` is the
CI smoke test: one query, one measured run.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import duckdb
import pandas as pd

from fuel_shock.config import CURATED, ROOT

RETAIL = CURATED / "retail.parquet"
OUT = ROOT / "benchmarks" / "latest.json"


def _time(fn, repeats: int) -> float:
    fn()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def run(repeats: int = 7) -> dict:
    if not RETAIL.exists():
        raise SystemExit("Curated retail extract is missing. Run make data.")
    con = duckdb.connect()
    path = RETAIL.as_posix()

    def duck_weekday():
        con.execute(
            f"""
            SELECT dayname(publish_date) AS day, avg(price_cpl) AS price, count(*) AS n
            FROM read_parquet('{path}')
            WHERE product = 'ULP' AND region = 'Metro'
            GROUP BY 1
            """
        ).fetchall()

    def duck_margin():
        con.execute(
            f"""
            WITH retail AS (
              SELECT publish_date, avg(price_cpl) AS retail
              FROM read_parquet('{path}')
              WHERE product = 'ULP' AND region = 'Metro'
              GROUP BY 1
            )
            SELECT publish_date, retail FROM retail
            """
        ).fetchall()

    frame = con.execute(
        f"""
        SELECT publish_date, price_cpl, product, region
        FROM read_parquet('{path}')
        """
    ).fetchdf()
    load_ms = None

    def _load():
        nonlocal load_ms
        start = time.perf_counter()
        con.execute(
            f"SELECT publish_date, price_cpl, product, region FROM read_parquet('{path}')"
        ).fetchdf()
        load_ms = (time.perf_counter() - start) * 1000

    _load()

    metro = frame[(frame["product"] == "ULP") & (frame["region"] == "Metro")].copy()
    metro["day"] = pd.to_datetime(metro["publish_date"]).dt.day_name()

    def pandas_weekday():
        metro.groupby("day", as_index=False)["price_cpl"].mean()

    def pandas_daily():
        metro.groupby("publish_date", as_index=False)["price_cpl"].mean()

    rows = int(con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0])
    result = {
        "rows": rows,
        "repeats": repeats,
        "method": "median milliseconds after one warmup",
        "duckdb_weekday_from_parquet_ms": round(_time(duck_weekday, repeats), 2),
        "duckdb_daily_metro_from_parquet_ms": round(_time(duck_margin, repeats), 2),
        "pandas_weekday_in_memory_ms": round(_time(pandas_weekday, repeats), 2),
        "pandas_daily_metro_in_memory_ms": round(_time(pandas_daily, repeats), 2),
        "pandas_load_via_duckdb_ms": round(load_ms or 0, 2),
        "note": (
            "DuckDB times include reading the parquet extract. Pandas times are the "
            "aggregation only, after the extract was loaded once. The load time is listed separately."
        ),
    }
    con.close()
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    result = run(repeats=1 if args.quick else 7)
    if not args.quick:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=2) + "\n")
        print(OUT)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
