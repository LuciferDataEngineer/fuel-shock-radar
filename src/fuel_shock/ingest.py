"""Download FuelWatch and FRED extracts. No API keys.

Historic retail and terminal-gate files are the CC BY 4.0 extracts published
by FuelWatch. The daily feed is the public site JSON. Brent is the FRED
series DCOILBRENTEU.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

import duckdb

from fuel_shock.config import (
    CURATED,
    DAILY_FEED_URL,
    FRED_BRENT_URL,
    PRODUCTS,
    RAW,
    RETAIL_BLOB,
    RETAIL_END,
    RETAIL_START,
    USER_AGENT,
    WHOLESALE_BLOB,
    WHOLESALE_YEARS,
)


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    year, month = start
    out: list[tuple[int, int]] = []
    while (year, month) <= end:
        out.append((year, month))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return out


def _fetch(url: str, dest: Path | None = None) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(request, timeout=120) as response:
        payload = response.read()
    if dest is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
    return payload


def download_sources(raw_dir: Path = RAW) -> dict[str, list[Path]]:
    """Save the source files used to build the curated extract."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    retail: list[Path] = []
    for year, month in _months(RETAIL_START, RETAIL_END):
        dest = raw_dir / f"FuelWatchRetail-{month:02d}-{year}.csv"
        if not dest.exists() or dest.stat().st_size < 1000:
            _fetch(RETAIL_BLOB.format(year=year, month=month), dest)
        retail.append(dest)
    wholesale: list[Path] = []
    for year in WHOLESALE_YEARS:
        dest = raw_dir / f"FuelWatchWholesale-{year}.csv"
        if not dest.exists() or dest.stat().st_size < 1000:
            _fetch(WHOLESALE_BLOB.format(year=year), dest)
        wholesale.append(dest)
    brent = raw_dir / "DCOILBRENTEU.csv"
    if not brent.exists() or brent.stat().st_size < 100:
        _fetch(FRED_BRENT_URL, brent)
    daily = raw_dir / "daily-ulp.json"
    if not daily.exists() or daily.stat().st_size < 100:
        _fetch(DAILY_FEED_URL, daily)
    return {"retail": retail, "wholesale": wholesale, "brent": [brent], "daily": [daily]}


def _csv_relation(paths: list[Path]) -> str:
    listed = ", ".join("'" + path.as_posix().replace("'", "''") + "'" for path in paths)
    return f"[{listed}]"


def build_curated(raw: dict[str, list[Path]], curated_dir: Path = CURATED) -> dict[str, int]:
    """Filter source files down to the columns the rest of the project uses."""
    curated_dir.mkdir(parents=True, exist_ok=True)
    products = ", ".join(f"'{name}'" for name in PRODUCTS)
    con = duckdb.connect()
    retail_out = curated_dir / "retail.parquet"
    wholesale_out = curated_dir / "wholesale.parquet"
    brent_out = curated_dir / "brent.parquet"
    daily_out = curated_dir / "daily_feed.parquet"
    con.execute(
        f"""
        COPY (
          SELECT
            CAST(strptime(PUBLISH_DATE, '%d/%m/%Y') AS DATE) AS publish_date,
            trim(TRADING_NAME) AS trading_name,
            trim(BRAND_DESCRIPTION) AS brand,
            trim(PRODUCT_DESCRIPTION) AS product,
            TRY_CAST(PRODUCT_PRICE AS DOUBLE) AS price_cpl,
            trim(ADDRESS) AS address,
            trim(LOCATION) AS suburb,
            trim(CAST(POSTCODE AS VARCHAR)) AS postcode,
            trim(AREA_DESCRIPTION) AS area,
            trim(REGION_DESCRIPTION) AS region,
            lower(trim(TRADING_NAME)) || '|' || lower(trim(LOCATION)) || '|'
              || trim(CAST(POSTCODE AS VARCHAR)) AS station_key
          FROM read_csv(
            {_csv_relation(raw['retail'])},
            header = true,
            union_by_name = true,
            all_varchar = true
          )
          WHERE PRODUCT_DESCRIPTION IN ({products})
            AND TRY_CAST(PRODUCT_PRICE AS DOUBLE) IS NOT NULL
            AND TRY_CAST(PRODUCT_PRICE AS DOUBLE) > 0
        ) TO '{retail_out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT
            CAST(strptime(PUBLISH_DATE, '%d/%m/%Y') AS DATE) AS publish_date,
            trim(TERMINAL_GATE) AS terminal,
            trim(BRAND) AS brand,
            trim(PRODUCT) AS product,
            TRY_CAST(PRODUCT_PRICE AS DOUBLE) AS price_cpl,
            trim(ADDRESS) AS address,
            trim(LOCATION) AS location,
            trim(CAST(POSTCODE AS VARCHAR)) AS postcode
          FROM read_csv(
            {_csv_relation(raw['wholesale'])},
            header = true,
            union_by_name = true,
            all_varchar = true
          )
          WHERE PRODUCT IN ({products})
            AND TRY_CAST(PRODUCT_PRICE AS DOUBLE) IS NOT NULL
            AND TRY_CAST(PRODUCT_PRICE AS DOUBLE) > 0
        ) TO '{wholesale_out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    brent_path = raw["brent"][0].as_posix()
    con.execute(
        f"""
        COPY (
          SELECT
            CAST(observation_date AS DATE) AS observe_date,
            TRY_CAST(DCOILBRENTEU AS DOUBLE) AS brent_usd
          FROM read_csv('{brent_path}', header = true, nullstr = '.')
          WHERE TRY_CAST(DCOILBRENTEU AS DOUBLE) IS NOT NULL
        ) TO '{brent_out.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    _write_daily_feed(raw["daily"][0], daily_out, con)
    counts = {
        "retail": con.execute(f"SELECT count(*) FROM '{retail_out.as_posix()}'").fetchone()[0],
        "wholesale": con.execute(
            f"SELECT count(*) FROM '{wholesale_out.as_posix()}'"
        ).fetchone()[0],
        "brent": con.execute(f"SELECT count(*) FROM '{brent_out.as_posix()}'").fetchone()[0],
        "daily_feed": con.execute(f"SELECT count(*) FROM '{daily_out.as_posix()}'").fetchone()[0],
    }
    retail_min, retail_max = con.execute(
        f"SELECT min(publish_date), max(publish_date) FROM '{retail_out.as_posix()}'"
    ).fetchone()
    con.close()
    captured = datetime.now(ZoneInfo("Australia/Perth")).date()
    manifest = {
        "retail_min": retail_min.isoformat(),
        "retail_max": retail_max.isoformat(),
        "daily_feed_today": captured.isoformat(),
        "daily_feed_tomorrow": (captured + timedelta(days=1)).isoformat(),
        "products": list(PRODUCTS),
        "note": (
            "price_today_cpl on the daily feed is the FuelWatch board for "
            "daily_feed_today. price_tomorrow_cpl is the locked-in next-day price."
        ),
    }
    (curated_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return counts


def _write_daily_feed(path: Path, dest: Path, con: duckdb.DuckDBPyConnection) -> None:
    rows = []
    payload = json.loads(path.read_text())
    for site in payload:
        product = site.get("product") or {}
        address = site.get("address") or {}
        rows.append(
            {
                "site_id": site.get("id"),
                "trading_name": site.get("siteName"),
                "brand_code": site.get("brandName"),
                "suburb": (address.get("location") or "").strip(),
                "postcode": str(address.get("postCode") or ""),
                "address": address.get("line1"),
                "latitude": address.get("latitude"),
                "longitude": address.get("longitude"),
                "product": site.get("productFuelType") or "ULP",
                "price_today_cpl": product.get("priceToday"),
                "price_tomorrow_cpl": product.get("priceTomorrow"),
            }
        )
    frame = json.dumps(rows)
    buffer_path = dest.parent / "_daily_rows.json"
    buffer_path.write_text(frame)
    con.execute(
        f"""
        COPY (
          SELECT * FROM read_json_auto('{buffer_path.as_posix()}')
        ) TO '{dest.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    buffer_path.unlink(missing_ok=True)


def curated_ready(curated_dir: Path = CURATED) -> bool:
    needed = ("retail.parquet", "wholesale.parquet", "brent.parquet", "daily_feed.parquet")
    return all((curated_dir / name).exists() for name in needed)


def ingest(curated_dir: Path = CURATED, raw_dir: Path = RAW) -> dict[str, int]:
    raw = download_sources(raw_dir)
    return build_curated(raw, curated_dir)


def main() -> None:
    counts = ingest()
    print(json.dumps({"curated": {key: int(value) for key, value in counts.items()}}))


if __name__ == "__main__":
    main()
