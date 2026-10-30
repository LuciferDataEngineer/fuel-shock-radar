"""Slowly changing station history.

A station keeps its key (trading name, suburb, postcode). Brand, address,
area, and region are tracked as versions. The batch path rebuilds the whole
history in DuckDB. The Spark job applies the same rule incrementally with
MERGE into a Delta table.
"""

from __future__ import annotations

from datetime import date


def attribute_hash(row: dict) -> str:
    parts = [
        row.get("brand") or "",
        row.get("address") or "",
        row.get("suburb") or "",
        row.get("area") or "",
        row.get("region") or "",
    ]
    return "|".join(parts)


def fold_scd2(snapshots: list[dict]) -> list[dict]:
    """Collapse daily snapshots into effective-dated versions.

    ``effective_to`` is the first day of the next version, or None while the
    version is current. Snapshots must include station_key and publish_date.
    """
    ordered = sorted(snapshots, key=lambda row: (row["station_key"], row["publish_date"]))
    versions: list[dict] = []
    current: dict[str, dict] = {}
    for row in ordered:
        key = row["station_key"]
        digest = attribute_hash(row)
        open_row = current.get(key)
        if open_row is None or open_row["attr_hash"] != digest:
            if open_row is not None:
                open_row["is_current"] = False
                open_row["effective_to"] = row["publish_date"]
            version = {
                "station_key": key,
                "brand": row.get("brand"),
                "address": row.get("address"),
                "suburb": row.get("suburb"),
                "postcode": row.get("postcode"),
                "area": row.get("area"),
                "region": row.get("region"),
                "attr_hash": digest,
                "effective_from": row["publish_date"],
                "effective_to": None,
                "last_seen": row["publish_date"],
                "is_current": True,
            }
            versions.append(version)
            current[key] = version
        else:
            open_row["last_seen"] = row["publish_date"]
    return versions


SCD2_SQL = """
WITH snap AS (
  SELECT station_key, publish_date, brand, address, suburb, postcode, area, region,
         concat_ws('|',
           coalesce(brand, ''), coalesce(address, ''), coalesce(suburb, ''),
           coalesce(area, ''), coalesce(region, '')) AS attr_hash
  FROM station_day
),
ordered AS (
  SELECT *, lag(attr_hash) OVER (PARTITION BY station_key ORDER BY publish_date) AS prev_hash
  FROM snap
),
flagged AS (
  SELECT *,
         CASE WHEN prev_hash IS NULL OR prev_hash <> attr_hash THEN 1 ELSE 0 END AS is_new
  FROM ordered
),
versioned AS (
  SELECT *, sum(is_new) OVER (PARTITION BY station_key ORDER BY publish_date) AS version_id
  FROM flagged
),
collapsed AS (
  SELECT station_key, version_id,
         any_value(brand) AS brand,
         any_value(address) AS address,
         any_value(suburb) AS suburb,
         any_value(postcode) AS postcode,
         any_value(area) AS area,
         any_value(region) AS region,
         any_value(attr_hash) AS attr_hash,
         min(publish_date) AS effective_from,
         max(publish_date) AS last_seen
  FROM versioned
  GROUP BY station_key, version_id
)
SELECT station_key, brand, address, suburb, postcode, area, region, attr_hash,
       effective_from, last_seen,
       lead(effective_from) OVER (PARTITION BY station_key ORDER BY effective_from) AS effective_to,
       lead(effective_from) OVER (PARTITION BY station_key ORDER BY effective_from) IS NULL AS is_current
FROM collapsed
"""


def versions_as_keys(versions: list[dict]) -> set[tuple]:
    return {
        (
            row["station_key"],
            row["attr_hash"],
            _iso(row["effective_from"]),
            _iso(row["effective_to"]),
            bool(row["is_current"]),
        )
        for row in versions
    }


def _iso(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
