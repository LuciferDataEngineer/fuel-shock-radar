"""Offline batch build of the serving tables and the dashboard JSON.

This is the path CI runs. It does not start Postgres, Redpanda, Spark, or Airflow.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

from fuel_shock.config import (
    CURATED,
    DASHBOARD_JSON,
    LINEAGE_DIR,
    QUALITY_DOCS,
    SERVING,
)
from fuel_shock.ingest import curated_ready, ingest
from fuel_shock.lineage import emit_batch
from fuel_shock.metrics import (
    average_between,
    brent_change,
    regional_gap,
    retail_margin,
    weekly_cycle,
    weekly_pass_through,
)
from fuel_shock.narrative import build_copy, cents, dollars, money
from fuel_shock.quality import validate
from fuel_shock.scd2 import SCD2_SQL

WEEKDAY_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _parquet(curated: Path, name: str) -> str:
    return (curated / name).as_posix()


def _load(con: duckdb.DuckDBPyConnection, curated: Path) -> None:
    con.execute(f"CREATE VIEW retail AS SELECT * FROM read_parquet('{_parquet(curated, 'retail.parquet')}')")
    con.execute(
        f"CREATE VIEW wholesale AS SELECT * FROM read_parquet('{_parquet(curated, 'wholesale.parquet')}')"
    )
    con.execute(f"CREATE VIEW brent AS SELECT * FROM read_parquet('{_parquet(curated, 'brent.parquet')}')")
    con.execute(
        f"CREATE VIEW daily_feed AS SELECT * FROM read_parquet('{_parquet(curated, 'daily_feed.parquet')}')"
    )


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def _quality_frames(con: duckdb.DuckDBPyConnection) -> dict:
    import pandas as pd

    retail = pd.DataFrame(
        _rows(
            con,
            """
            SELECT CAST(publish_date AS VARCHAR) AS publish_date,
                   station_key, price_cpl, product, region
            FROM retail
            """,
        ),
        columns=["publish_date", "station_key", "price_cpl", "product", "region"],
    )
    wholesale = pd.DataFrame(
        _rows(
            con,
            """
            SELECT CAST(publish_date AS VARCHAR) AS publish_date,
                   terminal, price_cpl, product
            FROM wholesale
            """,
        ),
        columns=["publish_date", "terminal", "price_cpl", "product"],
    )
    crude = pd.DataFrame(
        _rows(con, "SELECT CAST(observe_date AS VARCHAR) AS observe_date, brent_usd FROM brent"),
        columns=["observe_date", "brent_usd"],
    )
    return {"retail": retail, "wholesale": wholesale, "brent": crude}


def _scd2(con: duckdb.DuckDBPyConnection) -> dict:
    con.execute(
        """
        CREATE OR REPLACE TABLE station_day AS
        SELECT station_key, publish_date, brand, address, suburb, postcode, area, region
        FROM (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY station_key, publish_date ORDER BY product
                 ) AS rn
          FROM retail
        )
        WHERE rn = 1
        """
    )
    con.execute(f"CREATE OR REPLACE TABLE station_dim AS {SCD2_SQL}")
    stations, versions, changed = con.execute(
        """
        SELECT
          count(DISTINCT station_key),
          count(*),
          count(*) FILTER (WHERE NOT is_current)
        FROM station_dim
        """
    ).fetchone()
    return {
        "stations": int(stations),
        "versions": int(versions),
        "closed_versions": int(changed),
    }


def _tomorrow(con: duckdb.DuckDBPyConnection, manifest: dict) -> tuple[float | None, str | None]:
    row = con.execute(
        """
        WITH metro AS (
          SELECT upper(suburb) AS suburb
          FROM retail
          WHERE region = 'Metro' AND product = 'ULP'
          GROUP BY 1
        )
        SELECT avg(price_tomorrow_cpl)
        FROM daily_feed AS feed
        JOIN metro ON upper(feed.suburb) = metro.suburb
        WHERE price_tomorrow_cpl IS NOT NULL
        """
    ).fetchone()
    if not row or row[0] is None or "daily_feed_tomorrow" not in manifest:
        return None, None
    tomorrow = date.fromisoformat(manifest["daily_feed_tomorrow"])
    label = f"{tomorrow.strftime('%A')} {tomorrow.day} {tomorrow.strftime('%B')}"
    return float(row[0]), label


def _year_change(daily: list[tuple[date, float]], end: date) -> float | None:
    this_start = end.replace(day=1)
    try:
        prior_end = end.replace(year=end.year - 1)
        prior_start = this_start.replace(year=this_start.year - 1)
    except ValueError:
        return None
    current = average_between(daily, this_start, end)
    prior = average_between(daily, prior_start, prior_end)
    if current is None or prior is None or prior == 0:
        return None
    return (current / prior - 1.0) * 100.0


def _payload(copy: dict, cycle, margin, regions, passed, brent, manifest, scd, counts) -> dict:
    week_points = []
    for row in cycle.by_day:
        role = "mid"
        if row["day"] == cycle.cheapest_day:
            role = "cheap"
        elif row["day"] == cycle.peak_day:
            role = "peak"
        week_points.append(
            {
                "day": row["day"],
                "label": WEEKDAY_SHORT[WEEKDAYS_INDEX[row["day"]]],
                "price_aud": dollars(row["price_cpl"]),
                "cents": cents(row["price_cpl"]),
                "role": role,
            }
        )
    wholesale_points = [
        {
            "week": point["week"].isoformat(),
            "pump_aud": dollars(point["retail_cpl"]),
            "wholesale_aud": dollars(point["wholesale_cpl"]),
        }
        for point in margin.weekly
    ]
    region_points = [
        {
            "region": row["region"],
            "price_aud": dollars(row["price_cpl"]),
            "kind": "metro" if row["region"] == "Metro" else "regional",
        }
        for row in regions.by_region
    ]
    return {
        "schema_version": 1,
        "as_of": manifest.get("retail_max"),
        "product": "Unleaded",
        "kicker": copy["kicker"],
        "headline": copy["headline"],
        "dek": copy["dek"],
        "cards": copy["cards"],
        "charts": {
            "week": {
                "title": "The Perth week",
                "lead": copy["chart_leads"]["week"],
                "points": week_points,
            },
            "wholesale": {
                "title": "Pump price and wholesale",
                "lead": copy["chart_leads"]["wholesale"],
                "points": wholesale_points,
            },
            "regions": {
                "title": "City and country",
                "lead": copy["chart_leads"]["regions"],
                "points": region_points,
            },
        },
        "footer": {
            "as_of": manifest.get("retail_max"),
            "attribution": (
                "Pump and terminal prices from FuelWatch, Government of Western Australia, "
                "licensed CC BY 4.0. Brent crude is FRED series DCOILBRENTEU. "
                "The 8.7% transport figure is the Australian Bureau of Statistics consumer "
                "price index for September 2026. Figures are unleaded. Each station is counted equally."
            ),
            "methods_url": "https://github.com/LuciferDataEngineer/fuel-shock-radar",
            "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        },
        "audit": {
            "cycle_window": [cycle.window_start.isoformat(), cycle.window_end.isoformat()],
            "spread_cpl": cents(cycle.spread_cpl),
            "savings_aud": round(cycle.savings_aud, 2),
            "margin_current_cpl": cents(margin.current_cpl),
            "margin_median_cpl": cents(margin.median_cpl),
            "pass_through": {
                "judgement": passed.judgement,
                "up_ratio": None if passed.up_ratio is None else round(passed.up_ratio, 3),
                "down_ratio": None if passed.down_ratio is None else round(passed.down_ratio, 3),
                "up_weeks": passed.up_weeks,
                "down_weeks": passed.down_weeks,
            },
            "regional_gap_cpl": cents(regions.gap_cpl),
            "brent_usd": round(brent["latest_usd"], 2),
            "brent_change_pct": round(brent["change_pct"], 1),
            "scd2": scd,
            "rows": counts,
            "tank_savings_display": money(round(cycle.savings_aud, 2)),
        },
    }


WEEKDAYS_INDEX = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def run(
    curated_dir: Path = CURATED,
    dashboard_path: Path = DASHBOARD_JSON,
    serving_path: Path | None = None,
    lineage_dir: Path = LINEAGE_DIR,
    docs_dir: Path = QUALITY_DOCS,
    offline: bool = False,
    run_quality: bool = True,
) -> dict:
    if not curated_ready(curated_dir):
        if offline:
            raise SystemExit(f"Curated data is missing in {curated_dir}. Run make data.")
        ingest(curated_dir)
    manifest_path = curated_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    serving_path = serving_path or (SERVING / "fuel_shock.duckdb")
    serving_path.parent.mkdir(parents=True, exist_ok=True)
    if serving_path.exists():
        serving_path.unlink()

    con = duckdb.connect(str(serving_path))
    _load(con, curated_dir)
    if run_quality:
        quality = validate(_quality_frames(con), docs_dir)
        if not quality["success"]:
            con.close()
            raise SystemExit(f"Data quality checks failed: {json.dumps(quality['suites'])}")
    else:
        quality = {"success": True, "skipped": True}

    daily = [(day, float(price)) for day, price in _rows(
        con,
        """
        SELECT publish_date, avg(price_cpl)
        FROM retail
        WHERE product = 'ULP' AND region = 'Metro'
        GROUP BY 1
        ORDER BY 1
        """,
    )]
    paired = [
        (day, float(retail), float(wholesale))
        for day, retail, wholesale in _rows(
            con,
            """
            WITH metro AS (
              SELECT publish_date, avg(price_cpl) AS retail
              FROM retail
              WHERE product = 'ULP' AND region = 'Metro'
              GROUP BY 1
            ),
            tgp AS (
              SELECT publish_date, avg(price_cpl) AS wholesale
              FROM wholesale
              WHERE product = 'ULP'
                AND (upper(location) LIKE '%KWINANA%' OR upper(location) LIKE '%KEWDALE%')
              GROUP BY 1
            )
            SELECT metro.publish_date, metro.retail, tgp.wholesale
            FROM metro
            JOIN tgp USING (publish_date)
            ORDER BY 1
            """,
        )
    ]
    station_days = [
        (day, region, float(price))
        for day, region, price in _rows(
            con,
            """
            SELECT publish_date, region, price_cpl
            FROM retail
            WHERE product = 'ULP'
            """,
        )
    ]
    crude = [
        (day, float(price))
        for day, price in _rows(con, "SELECT observe_date, brent_usd FROM brent ORDER BY 1")
    ]
    counts = {
        "retail": int(_rows(con, "SELECT count(*) FROM retail")[0][0]),
        "wholesale": int(_rows(con, "SELECT count(*) FROM wholesale")[0][0]),
        "brent": len(crude),
        "daily_feed": int(_rows(con, "SELECT count(*) FROM daily_feed")[0][0]),
    }
    cycle = weekly_cycle(daily)
    margin = retail_margin(paired)
    regions = regional_gap(station_days, end=daily[-1][0])
    passed = weekly_pass_through(
        [(point["week"], point["retail_cpl"], point["wholesale_cpl"]) for point in margin.weekly]
    )
    crude_change = brent_change(crude)
    year_change = _year_change(daily, daily[-1][0])
    tomorrow_cpl, tomorrow_label = _tomorrow(con, manifest)
    scd = _scd2(con)
    con.execute(
        """
        CREATE OR REPLACE TABLE mart_daily_metro AS
        SELECT publish_date, avg(price_cpl) AS price_cpl, count(*) AS stations
        FROM retail
        WHERE product = 'ULP' AND region = 'Metro'
        GROUP BY 1
        ORDER BY 1
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE mart_margin_daily AS
        WITH metro AS (
          SELECT publish_date, avg(price_cpl) AS retail_cpl
          FROM retail
          WHERE product = 'ULP' AND region = 'Metro'
          GROUP BY 1
        ),
        tgp AS (
          SELECT publish_date, avg(price_cpl) AS wholesale_cpl
          FROM wholesale
          WHERE product = 'ULP'
            AND (upper(location) LIKE '%KWINANA%' OR upper(location) LIKE '%KEWDALE%')
          GROUP BY 1
        )
        SELECT metro.publish_date, metro.retail_cpl, tgp.wholesale_cpl,
               metro.retail_cpl - tgp.wholesale_cpl AS gap_cpl
        FROM metro
        JOIN tgp USING (publish_date)
        ORDER BY 1
        """
    )
    con.close()

    copy = build_copy(
        cycle, margin, regions, passed, crude_change, year_change, tomorrow_cpl, tomorrow_label
    )
    payload = _payload(copy, cycle, margin, regions, passed, crude_change, manifest, scd, counts)
    payload["audit"]["quality"] = {"success": quality["success"]}
    payload["audit"]["built_at_note"] = "Numbers come only from the curated extract named in manifest."
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(json.dumps(payload, indent=2) + "\n")
    emit_batch(lineage_dir)
    return payload


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build the Fuel Shock Radar dashboard data")
    parser.add_argument("--offline", action="store_true", help="Do not download; use curated files")
    parser.add_argument("--skip-quality", action="store_true")
    args = parser.parse_args()
    payload = run(offline=args.offline, run_quality=not args.skip_quality)
    print(
        json.dumps(
            {
                "headline": payload["headline"],
                "cards": [
                    {"title": card["title"], "value": card["value"], "status": card["status"]}
                    for card in payload["cards"]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
