import json
from datetime import date, timedelta

import duckdb

from fuel_shock.batch import run


def _write(con: duckdb.DuckDBPyConnection, frame_sql: str, path) -> None:
    con.execute(f"COPY ({frame_sql}) TO '{path.as_posix()}' (FORMAT PARQUET)")


def test_batch_builds_four_cards_and_three_charts(tmp_path):
    curated = tmp_path / "curated"
    curated.mkdir()
    con = duckdb.connect()
    start = date(2026, 10, 5)
    retail_rows = []
    for offset in range(21):
        day = start + timedelta(days=offset)
        week = offset // 7
        shift = (0, 12, 5)[week]
        metro = {0: 200, 1: 190, 2: 220, 3: 210, 4: 205, 5: 202, 6: 201}[day.weekday()] + shift
        brand = "Ampol" if offset < 10 else "BP"
        retail_rows.append(
            (day, "Metro Fuel", brand, "ULP", metro, "1 St", "PERTH", "6000", "Central", "Metro", "metro fuel|perth|6000")
        )
        retail_rows.append(
            (day, "Peel Fuel", "BP", "ULP", metro + 30, "2 St", "MANDURAH", "6210", "Mandurah", "Peel", "peel fuel|mandurah|6210")
        )
    con.execute(
        """
        CREATE TABLE retail (
          publish_date DATE, trading_name VARCHAR, brand VARCHAR, product VARCHAR,
          price_cpl DOUBLE, address VARCHAR, suburb VARCHAR, postcode VARCHAR,
          area VARCHAR, region VARCHAR, station_key VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO retail VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", retail_rows)
    _write(con, "SELECT * FROM retail", curated / "retail.parquet")
    con.execute(
        """
        CREATE TABLE wholesale AS
        SELECT publish_date, 'Ampol Kwinana' AS terminal, 'Ampol' AS brand, 'ULP' AS product,
               150 + CASE WHEN publish_date < DATE '2026-10-12' THEN 0
                          WHEN publish_date < DATE '2026-10-19' THEN 12 ELSE 5 END AS price_cpl,
               'Beach Rd' AS address, 'KWINANA BEACH' AS location, '6167' AS postcode
        FROM (SELECT DISTINCT publish_date FROM retail)
        """
    )
    _write(con, "SELECT * FROM wholesale", curated / "wholesale.parquet")
    con.execute(
        """
        CREATE TABLE brent AS
        SELECT * FROM (VALUES
          (DATE '2025-10-27', 65.0),
          (DATE '2026-10-27', 120.0)
        ) AS t(observe_date, brent_usd)
        """
    )
    _write(con, "SELECT * FROM brent", curated / "brent.parquet")
    con.execute(
        """
        CREATE TABLE daily_feed AS
        SELECT 1 AS site_id, 'Metro Fuel' AS trading_name, 'AMP' AS brand_code,
               'PERTH' AS suburb, '6000' AS postcode, '1 St' AS address,
               -31.9 AS latitude, 115.8 AS longitude, 'ULP' AS product,
               200.0 AS price_today_cpl, 198.0 AS price_tomorrow_cpl
        """
    )
    _write(con, "SELECT * FROM daily_feed", curated / "daily_feed.parquet")
    (curated / "manifest.json").write_text(
        json.dumps(
            {
                "retail_min": "2026-10-05",
                "retail_max": "2026-10-25",
                "daily_feed_today": "2026-10-26",
                "daily_feed_tomorrow": "2026-10-27",
            }
        )
    )
    payload = run(
        curated_dir=curated,
        dashboard_path=tmp_path / "dashboard.json",
        serving_path=tmp_path / "fuel.duckdb",
        lineage_dir=tmp_path / "lineage",
        docs_dir=tmp_path / "docs",
        offline=True,
    )
    assert payload["headline"].startswith("Tuesday")
    assert len(payload["cards"]) == 4
    assert len(payload["charts"]) == 3
    assert {card["status"] for card in payload["cards"]} <= {"calm", "elevated", "high"}
    assert payload["audit"]["scd2"]["closed_versions"] >= 1
    assert (tmp_path / "lineage" / "serve_dashboard.json").exists()
    assert (tmp_path / "docs" / "index.html").exists()
    saved = json.loads((tmp_path / "dashboard.json").read_text())
    assert saved["cards"][0]["value"] == "Tuesday"
