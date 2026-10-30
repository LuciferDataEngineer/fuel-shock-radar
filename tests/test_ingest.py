import json
from datetime import date

import duckdb

from fuel_shock.ingest import _months, build_curated


def test_month_window_includes_the_shock_year():
    months = _months((2025, 10), (2026, 10))
    assert months[0] == (2025, 10)
    assert months[-1] == (2026, 10)
    assert len(months) == 13


def test_build_curated_parses_australian_dates(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    retail = raw / "retail.csv"
    retail.write_text(
        "PUBLISH_DATE,TRADING_NAME,BRAND_DESCRIPTION,PRODUCT_DESCRIPTION,PRODUCT_PRICE,"
        "ADDRESS,LOCATION,POSTCODE,AREA_DESCRIPTION,REGION_DESCRIPTION\n"
        "01/10/2026,Site,Ampol,ULP,210.50,1 St,PERTH,6000,Central,Metro\n"
        "01/10/2026,Site,Ampol,98 RON,230.00,1 St,PERTH,6000,Central,Metro\n"
    )
    wholesale = raw / "wholesale.csv"
    wholesale.write_text(
        "PUBLISH_DATE,TERMINAL_GATE,BRAND,PRODUCT,PRODUCT_PRICE,ADDRESS,LOCATION,POSTCODE\n"
        "01/10/2026,Ampol Kwinana,Ampol,ULP,180.25,Beach Rd,KWINANA BEACH,6167\n"
    )
    brent = raw / "brent.csv"
    brent.write_text("observation_date,DCOILBRENTEU\n2026-10-01,100.5\n2026-10-02,.\n")
    daily = raw / "daily.json"
    daily.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "siteName": "Site",
                    "brandName": "AMP",
                    "address": {
                        "line1": "1 St",
                        "location": "PERTH",
                        "postCode": 6000,
                        "latitude": -31.9,
                        "longitude": 115.8,
                    },
                    "product": {"priceToday": 211.0, "priceTomorrow": 205.0},
                    "productFuelType": "ULP",
                }
            ]
        )
    )
    curated = tmp_path / "curated"
    counts = build_curated(
        {"retail": [retail], "wholesale": [wholesale], "brent": [brent], "daily": [daily]},
        curated,
    )
    assert counts["retail"] == 1
    assert counts["brent"] == 1
    assert counts["daily_feed"] == 1
    con = duckdb.connect()
    row = con.execute(f"SELECT publish_date, price_cpl, station_key FROM '{curated / 'retail.parquet'}'").fetchone()
    assert row[0] == date(2026, 10, 1)
    assert row[1] == 210.5
    assert row[2] == "site|perth|6000"
    manifest = json.loads((curated / "manifest.json").read_text())
    assert manifest["retail_max"] == "2026-10-01"
