"""Validated monthly replacement ETL and composition-aware price analytics.

One source must contain a complete closed month of the publisher's observations.
Date coverage is verified; coverage of every physical station cannot be inferred.
Source prices are cents/litre. Derived identities include trading name because
the official archive contains different reporting businesses at identical addresses.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import re
import shutil
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb

SOURCE_TEMPLATE = "https://warsydprdstafuelwatch.blob.core.windows.net/historical-reports/FuelWatchRetail-{month:02d}-{year:04d}.csv"
MAX_SOURCE_BYTES = 75 * 1024 * 1024
MAX_SOURCE_ROWS = 1_000_000
SCHEMA_VERSION = 1
SOURCE_FIELDS = (
    "PUBLISH_DATE", "TRADING_NAME", "BRAND_DESCRIPTION", "PRODUCT_DESCRIPTION", "PRODUCT_PRICE",
    "ADDRESS", "LOCATION", "POSTCODE", "AREA_DESCRIPTION", "REGION_DESCRIPTION",
)
FACT_FIELDS = (
    "month", "site_id", "observed_date", "product", "price_cpl", "site_name", "brand",
    "address", "location", "postcode", "area", "region", "source_sha256",
)

SCHEMA = """
CREATE TABLE pipeline_runs (
    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP NOT NULL, finished_at TIMESTAMP,
    as_of DATE NOT NULL, status VARCHAR NOT NULL CHECK(status IN ('running','success','failed')),
    error VARCHAR, loaded_months INTEGER, skipped_months INTEGER, loaded_rows BIGINT
);
CREATE TABLE source_artifacts (
    run_id VARCHAR NOT NULL REFERENCES pipeline_runs(run_id), source_sha256 VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL, raw_path VARCHAR NOT NULL, byte_size BIGINT NOT NULL,
    retrieved_at TIMESTAMP NOT NULL, month DATE, row_count BIGINT,
    PRIMARY KEY(run_id, source_sha256)
);
CREATE TABLE source_months (
    month DATE PRIMARY KEY, source_sha256 VARCHAR NOT NULL, source_url VARCHAR NOT NULL,
    row_count BIGINT NOT NULL, min_date DATE NOT NULL, max_date DATE NOT NULL,
    revision INTEGER NOT NULL, loaded_at TIMESTAMP NOT NULL, run_id VARCHAR NOT NULL
);
CREATE TABLE price_observations (
    month DATE NOT NULL, site_id VARCHAR NOT NULL, observed_date DATE NOT NULL,
    product VARCHAR NOT NULL, price_cpl DECIMAL(6,1) NOT NULL CHECK(price_cpl>0),
    site_name VARCHAR NOT NULL, brand VARCHAR NOT NULL, address VARCHAR NOT NULL,
    location VARCHAR NOT NULL, postcode VARCHAR NOT NULL, area VARCHAR NOT NULL,
    region VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL,
    PRIMARY KEY(site_id, observed_date, product),
    CHECK(month=date_trunc('month',observed_date)::DATE)
);
CREATE INDEX idx_prices_month ON price_observations(month);
CREATE INDEX idx_prices_product_location_date ON price_observations(product,location,observed_date);
CREATE VIEW daily_market_summary AS
SELECT observed_date, product, location, COUNT(*) AS site_count,
       quantile_cont(price_cpl::DOUBLE,0.5) AS median_cpl,
       quantile_cont(price_cpl::DOUBLE,0.25) AS p25_cpl,
       quantile_cont(price_cpl::DOUBLE,0.75) AS p75_cpl,
       quantile_cont(price_cpl::DOUBLE,0.75)-quantile_cont(price_cpl::DOUBLE,0.25) AS iqr_cpl
FROM price_observations GROUP BY observed_date,product,location;
CREATE VIEW matched_site_changes AS
SELECT c.site_id, c.observed_date, p.observed_date AS previous_date, c.product, c.location,
       c.site_name, c.brand, p.price_cpl AS previous_price_cpl, c.price_cpl AS current_price_cpl,
       c.price_cpl-p.price_cpl AS change_cpl,
       ABS(c.price_cpl-p.price_cpl)>=10.0 AS is_large_move
FROM price_observations c JOIN price_observations p
  ON c.site_id=p.site_id AND c.product=p.product AND p.observed_date=c.observed_date-1;
CREATE VIEW matched_market_changes AS
SELECT observed_date,product,location,COUNT(*) AS paired_site_count,
       quantile_cont(change_cpl::DOUBLE,0.5) AS median_change_cpl,
       AVG(change_cpl::DOUBLE) AS mean_change_cpl,
       COUNT(*) FILTER(WHERE is_large_move) AS large_move_count
FROM matched_site_changes GROUP BY observed_date,product,location;
"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_of(value: str | date | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        result = date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("as_of must be YYYY-MM-DD") from exc
    if result.isoformat() != value:
        raise ValueError("as_of must be YYYY-MM-DD")
    return result


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY)")
    versions = connection.execute("SELECT version FROM schema_version").fetchall()
    if versions and versions != [(SCHEMA_VERSION,)]:
        connection.close()
        raise RuntimeError(f"Unsupported warehouse schema: {versions}")
    if not versions:
        connection.execute("BEGIN TRANSACTION")
        try:
            connection.execute(SCHEMA)
            connection.execute("INSERT INTO schema_version VALUES(?)", [SCHEMA_VERSION])
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            connection.close()
            raise
    return connection


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(value: str) -> str:
    return " ".join(value.strip().upper().split())


def _site_id(row: dict[str, str]) -> str:
    identity = [_normalize(row[key]) for key in ("TRADING_NAME", "ADDRESS", "LOCATION", "POSTCODE")]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _parse_month_file(path: Path, staging: Path, digest: str, as_of: date) -> dict:
    """Validate the full source before exposing normalized rows to DuckDB."""
    seen, days = set(), set()
    source_month = None
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as source, staging.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Missing or duplicate source CSV headers")
        missing = set(SOURCE_FIELDS)-set(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing source columns: {', '.join(sorted(missing))}")
        writer = csv.DictWriter(target, fieldnames=FACT_FIELDS)
        writer.writeheader()
        for count, row in enumerate(reader, start=1):
            if count > MAX_SOURCE_ROWS:
                raise ValueError("Source exceeds the bounded row limit")
            if None in row or any(not isinstance(row.get(field), str) or not row[field].strip() for field in SOURCE_FIELDS):
                raise ValueError(f"Missing or malformed source value at row {count}")
            try:
                observed = datetime.strptime(row["PUBLISH_DATE"].strip(), "%d/%m/%Y").date()
            except ValueError as exc:
                raise ValueError(f"Invalid PUBLISH_DATE at row {count}; expected DD/MM/YYYY") from exc
            month = observed.replace(day=1)
            if month >= as_of.replace(day=1):
                raise ValueError("Only completed calendar months are accepted; current-month archives are incomplete")
            if source_month is not None and month != source_month:
                raise ValueError("Each source CSV must contain exactly one calendar month")
            source_month = month
            try:
                price = Decimal(row["PRODUCT_PRICE"].strip())
                if not price.is_finite() or not Decimal("0") < price <= Decimal("99999.9") or price != price.quantize(Decimal("0.1")):
                    raise ValueError("outside positive DECIMAL(6,1) domain")
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"Invalid PRODUCT_PRICE at row {count}; expected positive cents/litre with at most one meaningful decimal") from exc
            site = _site_id(row)
            product = _normalize(row["PRODUCT_DESCRIPTION"])
            key = (site, observed, product)
            if key in seen:
                raise ValueError(f"Duplicate site/date/product source key at row {count}")
            seen.add(key)
            days.add(observed)
            writer.writerow({"month": month.isoformat(), "site_id": site, "observed_date": observed.isoformat(),
                             "product": product, "price_cpl": str(price.quantize(Decimal("0.1"))),
                             "site_name": row["TRADING_NAME"].strip(), "brand": row["BRAND_DESCRIPTION"].strip(),
                             "address": row["ADDRESS"].strip(), "location": _normalize(row["LOCATION"]),
                             "postcode": row["POSTCODE"].strip(), "area": row["AREA_DESCRIPTION"].strip(),
                             "region": row["REGION_DESCRIPTION"].strip(), "source_sha256": digest})
    if not count or source_month is None:
        raise ValueError("Source CSV contains no observations")
    expected_days = {source_month+timedelta(days=index) for index in range(calendar.monthrange(source_month.year,source_month.month)[1])}
    if days != expected_days:
        missing_days = ", ".join(day.isoformat() for day in sorted(expected_days-days))
        raise ValueError(f"Incomplete calendar-day coverage for {source_month:%Y-%m}; missing {missing_days}")
    return {"month": source_month, "row_count": count, "min_date": min(days), "max_date": max(days), "staging": staging}


def _replace_month(connection: duckdb.DuckDBPyConnection, snapshot: dict, run_id: str) -> bool:
    """Replace one validated monthly partition inside the caller's transaction."""
    prior = connection.execute("SELECT source_sha256,revision FROM source_months WHERE month=?", [snapshot["month"]]).fetchone()
    if prior and prior[0] == snapshot["source_sha256"]:
        return False
    connection.execute("DELETE FROM price_observations WHERE month=?", [snapshot["month"]])
    connection.execute("""INSERT INTO price_observations
        SELECT month::DATE,site_id,observed_date::DATE,product,price_cpl::DECIMAL(6,1),site_name,brand,
               address,location,postcode,area,region,source_sha256
        FROM read_csv(?,header=true,all_varchar=true)""", [str(snapshot["staging"])])
    connection.execute("DELETE FROM source_months WHERE month=?", [snapshot["month"]])
    connection.execute("INSERT INTO source_months VALUES(?,?,?,?,?,?,?,?,?)", [snapshot["month"],snapshot["source_sha256"],
        snapshot["source_url"],snapshot["row_count"],snapshot["min_date"],snapshot["max_date"],
        prior[1]+1 if prior else 1,_now(),run_id])
    return True


def _summary(connection: duckdb.DuckDBPyConnection, run_id: str) -> dict:
    run = connection.execute("SELECT as_of,status,loaded_months,skipped_months,loaded_rows FROM pipeline_runs WHERE run_id=?", [run_id]).fetchone()
    totals = connection.execute("SELECT COUNT(*),COUNT(DISTINCT site_id),COUNT(DISTINCT product),MIN(observed_date),MAX(observed_date) FROM price_observations").fetchone()
    movements = connection.execute("SELECT COUNT(*),COUNT(*) FILTER(WHERE is_large_move) FROM matched_site_changes").fetchone()
    months = connection.execute("SELECT month,row_count,revision,source_sha256 FROM source_months ORDER BY month").fetchall()
    return {"run_id": run_id, "as_of": run[0].isoformat(), "status": run[1], "loaded_months": run[2],
            "skipped_months": run[3], "loaded_rows": run[4], "observations": totals[0],
            "reported_outlets": totals[1], "products": totals[2], "first_date": totals[3].isoformat(),
            "last_date": totals[4].isoformat(), "consecutive_site_pairs": movements[0], "large_move_pairs": movements[1],
            "months": [{"month": month.strftime("%Y-%m"), "row_count": rows, "revision": revision, "sha256": digest}
                       for month,rows,revision,digest in months],
            "units": "Australian cents per litre", "large_move_threshold_cpl": 10.0,
            "caveats": ["Large moves are descriptive absolute changes of at least 10 cents/litre, not evidence of a causal market shock.",
                        "Matched changes compare the same derived reporting identity and product on exact consecutive dates.",
                        "Trading-name changes create new identities; counts are reporting identities, not verified physical station counts.",
                        "All calendar days must be present, but complete coverage of every station cannot be independently proven."]}


def _export(connection: duckdb.DuckDBPyConnection, directory: Path, summary: dict) -> None:
    """Publish one coherent export generation via a single atomic pointer file."""
    generation = directory / summary["run_id"]
    generation.mkdir(parents=True, exist_ok=True)
    for name, order in (("price_observations","observed_date,product,location,site_id"),
                        ("daily_market_summary","observed_date,product,location"),
                        ("matched_site_changes","observed_date,product,location,site_id"),
                        ("matched_market_changes","observed_date,product,location")):
        path = generation / f"{name}.parquet"
        # All SQL identifiers here are fixed constants; the filesystem path is quoted separately.
        quoted = str(path).replace("'", "''")
        connection.execute(f"COPY (SELECT * FROM {name} ORDER BY {order}) TO '{quoted}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    (generation / "summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    pointer = {"run_id": summary["run_id"], "directory": summary["run_id"], "summary": f"{summary['run_id']}/summary.json"}
    temporary = directory / f".latest-{summary['run_id']}.tmp"
    temporary.write_text(json.dumps(pointer,indent=2)+"\n",encoding="utf-8")
    temporary.replace(directory / "latest.json")


def run_pipeline(data_dir: str | Path, *, files: list[str | Path], source_urls: list[str] | None = None,
                 as_of: str | date | None = None) -> dict:
    """Atomically ingest one or more trusted complete closed-month source CSVs.

    Failed validation/loads leave business tables unchanged and retain raw/audit
    evidence. Exports are derived after commit; an export error is recorded on
    the successful load and rerunning the sources regenerates them safely.
    """
    assessment = _as_of(as_of)
    if not files:
        raise ValueError("At least one monthly source file is required")
    if source_urls is not None and len(source_urls) != len(files):
        raise ValueError("source_urls must have exactly one entry per source file")
    root = Path(data_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    connection = _connect(root / "warehouse.duckdb")
    run_id, loaded = uuid.uuid4().hex, False
    staging_paths = []
    try:
        connection.execute("INSERT INTO pipeline_runs(run_id,started_at,as_of,status) VALUES(?,?,?,'running')", [run_id,_now(),assessment])
        latest_assessment = connection.execute("SELECT MAX(as_of) FROM pipeline_runs WHERE status='success'").fetchone()[0]
        if latest_assessment is not None and assessment < latest_assessment:
            raise ValueError("Assessment date cannot move backwards; replay historical analyses in a separate data directory")
        snapshots, seen_months = [], set()
        raw_directory = root / "raw" / run_id
        raw_directory.mkdir(parents=True)
        for index, source in enumerate(files):
            path = Path(source).resolve()
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise ValueError("Source exceeds the bounded download size")
            raw = raw_directory / f"source-{index+1:02d}.csv"
            shutil.copyfile(path,raw)
            digest = _sha256(raw)
            location = source_urls[index] if source_urls is not None else path.as_uri()
            artifact = {"run_id": run_id,"source_sha256":digest,"source_url":location,
                        "raw_path":str(raw),"byte_size":raw.stat().st_size,"retrieved_at":_now().isoformat()+"Z"}
            (raw_directory / f"source-{index+1:02d}.manifest.json").write_text(json.dumps(artifact,indent=2)+"\n",encoding="utf-8")
            # Identical repeated input files fail explicitly before violating the audit key.
            if any(item["source_sha256"] == digest for item in snapshots):
                raise ValueError("Duplicate source snapshot in one run")
            connection.execute("INSERT INTO source_artifacts(run_id,source_sha256,source_url,raw_path,byte_size,retrieved_at) VALUES(?,?,?,?,?,?)",
                               [run_id,digest,location,str(raw),raw.stat().st_size,_now()])
            staging = raw_directory / f".normalized-{index+1:02d}.csv"
            staging_paths.append(staging)
            validated = _parse_month_file(raw,staging,digest,assessment)
            named_month = re.fullmatch(r"FuelWatchRetail-(\d{2})-(\d{4})\.csv", Path(urllib.parse.urlparse(location).path).name)
            if named_month and (validated["month"].month,validated["month"].year) != (int(named_month[1]),int(named_month[2])):
                raise ValueError("Source URL month does not match the CSV observation month")
            if validated["month"] in seen_months:
                raise ValueError("Multiple source files for the same month in one run are ambiguous")
            seen_months.add(validated["month"])
            snapshot = {**validated,"source_sha256":digest,"source_url":location}
            snapshots.append(snapshot)
            connection.execute("UPDATE source_artifacts SET month=?,row_count=? WHERE run_id=? AND source_sha256=?",
                               [validated["month"],validated["row_count"],run_id,digest])
        connection.execute("BEGIN TRANSACTION")
        try:
            changed = [_replace_month(connection,snapshot,run_id) for snapshot in snapshots]
            loaded_rows = sum(snapshot["row_count"] for snapshot,did_change in zip(snapshots,changed) if did_change)
            connection.execute("UPDATE pipeline_runs SET status='success',finished_at=?,loaded_months=?,skipped_months=?,loaded_rows=? WHERE run_id=?",
                               [_now(),sum(changed),len(changed)-sum(changed),loaded_rows,run_id])
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        loaded = True
        summary = _summary(connection,run_id)
        _export(connection,root / "exports",summary)
        return summary
    except Exception as exc:
        if loaded:
            connection.execute("UPDATE pipeline_runs SET error=? WHERE run_id=?", [f"Load succeeded; derived export failed: {exc}"[:2000],run_id])
        else:
            connection.execute("UPDATE pipeline_runs SET status='failed',finished_at=?,error=? WHERE run_id=?", [_now(),str(exc)[:2000],run_id])
        raise
    finally:
        for path in staging_paths:
            path.unlink(missing_ok=True)
        connection.close()


def fetch_month(data_dir: str | Path, *, month: str | None = None, as_of: str | date | None = None) -> dict:
    """Download one official historical archive, checking transport completeness."""
    assessment = _as_of(as_of)
    if month is None:
        requested = assessment.replace(day=1)-timedelta(days=1)
        requested = requested.replace(day=1)
    else:
        try:
            requested = date.fromisoformat(month+"-01")
            if requested.strftime("%Y-%m") != month:
                raise ValueError("invalid month")
        except (ValueError,TypeError) as exc:
            raise ValueError("month must use YYYY-MM") from exc
    if requested >= assessment.replace(day=1):
        raise ValueError("fetch accepts only completed calendar months")
    url = SOURCE_TEMPLATE.format(year=requested.year,month=requested.month)
    downloads = Path(data_dir).resolve() / "downloads"
    downloads.mkdir(parents=True,exist_ok=True)
    destination = downloads / f"FuelWatchRetail-{requested.month:02d}-{requested.year:04d}-{uuid.uuid4().hex[:8]}.csv"
    request = urllib.request.Request(url,headers={"User-Agent":"FuelRadar/1.0 public-data-etl"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=45) as response,destination.open("wb") as output:
                expected = response.headers.get("Content-Length")
                count = 0
                while chunk := response.read(1024*1024):
                    count += len(chunk)
                    if count > MAX_SOURCE_BYTES:
                        raise ValueError("Downloaded source exceeds the size limit")
                    output.write(chunk)
                if expected is not None and count != int(expected):
                    raise RuntimeError("Incomplete source download: Content-Length mismatch")
            break
        except urllib.error.HTTPError as exc:
            if attempt == 2 or (exc.code != 429 and exc.code < 500):
                raise RuntimeError(f"Publisher archive HTTP {exc.code}: {url}") from exc
            time.sleep(2**attempt)
        except (urllib.error.URLError,TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Publisher archive unavailable: {url}: {exc}") from exc
            time.sleep(2**attempt)
    return run_pipeline(data_dir,files=[destination],source_urls=[url],as_of=assessment)
