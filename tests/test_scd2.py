from datetime import date

import duckdb

from fuel_shock.scd2 import SCD2_SQL, fold_scd2, versions_as_keys


def _snapshots():
    rows = []
    for day in range(1, 6):
        rows.append(
            {
                "station_key": "ampol|perth|6000",
                "publish_date": date(2026, 10, day),
                "brand": "Ampol",
                "address": "1 St",
                "suburb": "PERTH",
                "postcode": "6000",
                "area": "Central",
                "region": "Metro",
            }
        )
    for day in range(6, 9):
        rows.append(
            {
                "station_key": "ampol|perth|6000",
                "publish_date": date(2026, 10, day),
                "brand": "BP",
                "address": "1 St",
                "suburb": "PERTH",
                "postcode": "6000",
                "area": "Central",
                "region": "Metro",
            }
        )
    return rows


def test_fold_closes_the_old_brand_and_opens_a_new_version():
    versions = fold_scd2(_snapshots())
    assert len(versions) == 2
    closed = versions[0]
    current = versions[1]
    assert closed["brand"] == "Ampol"
    assert closed["is_current"] is False
    assert closed["effective_to"] == date(2026, 10, 6)
    assert current["brand"] == "BP"
    assert current["is_current"] is True
    assert current["effective_to"] is None
    assert current["effective_from"] == date(2026, 10, 6)


def test_sql_rebuild_matches_the_incremental_fold():
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE station_day (
          station_key VARCHAR, publish_date DATE, brand VARCHAR, address VARCHAR,
          suburb VARCHAR, postcode VARCHAR, area VARCHAR, region VARCHAR
        )
        """
    )
    for row in _snapshots():
        con.execute(
            """
            INSERT INTO station_day VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                row["station_key"],
                row["publish_date"],
                row["brand"],
                row["address"],
                row["suburb"],
                row["postcode"],
                row["area"],
                row["region"],
            ],
        )
    cursor = con.execute(SCD2_SQL)
    columns = [item[0] for item in cursor.description]
    sql_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    assert versions_as_keys(sql_rows) == versions_as_keys(fold_scd2(_snapshots()))
