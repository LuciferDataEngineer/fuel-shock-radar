"""PySpark Structured Streaming job: Kafka to Delta with MERGE and SCD2.

The batch build does not need Spark. This module is the CDC path:
Debezium writes station and price changes to Redpanda, and foreachBatch
merges them into Delta tables. Station attributes use the same effective-date
rule as ``fuel_shock.scd2``.
"""

from __future__ import annotations

import os

PRICE_MERGE_SQL = """
MERGE INTO delta.`{price_path}` AS target
USING price_updates AS source
ON target.station_key = source.station_key
 AND target.product = source.product
 AND target.publish_date = source.publish_date
WHEN MATCHED AND target.price_cpl <> source.price_cpl THEN UPDATE SET
  price_cpl = source.price_cpl,
  updated_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (
  station_key, product, publish_date, price_cpl, trading_name, suburb, region, updated_at
) VALUES (
  source.station_key, source.product, source.publish_date, source.price_cpl,
  source.trading_name, source.suburb, source.region, current_timestamp()
)
"""

# Close the open version when brand, address, area, or region changes.
SCD2_CLOSE_SQL = """
MERGE INTO delta.`{station_path}` AS target
USING station_updates AS source
ON target.station_key = source.station_key
 AND target.is_current = true
 AND target.attr_hash <> source.attr_hash
WHEN MATCHED THEN UPDATE SET
  is_current = false,
  effective_to = source.publish_date
"""

# Refresh a matching open version, or insert the first version and any new one
# opened by the close statement above.
SCD2_UPSERT_SQL = """
MERGE INTO delta.`{station_path}` AS target
USING station_updates AS source
ON target.station_key = source.station_key
 AND target.is_current = true
 AND target.attr_hash = source.attr_hash
WHEN MATCHED THEN UPDATE SET
  last_seen = source.publish_date
WHEN NOT MATCHED THEN INSERT (
  station_key, brand, address, suburb, postcode, area, region, attr_hash,
  effective_from, effective_to, last_seen, is_current
) VALUES (
  source.station_key, source.brand, source.address, source.suburb, source.postcode,
  source.area, source.region, source.attr_hash, source.publish_date, NULL,
  source.publish_date, true
)
"""

STATION_HASH_SQL = """
SELECT
  station_key,
  CAST(publish_date AS DATE) AS publish_date,
  brand, address, suburb, postcode, area, region,
  concat_ws('|',
    coalesce(brand, ''), coalesce(address, ''), coalesce(suburb, ''),
    coalesce(area, ''), coalesce(region, '')) AS attr_hash
FROM station_raw
"""


def build_session():
    from pyspark.sql import SparkSession

    return (
        SparkSession.builder.appName("fuel-shock-radar")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .getOrCreate()
    )


def parse_debezium(raw):
    """Turn a Kafka value column into the unwrapped Debezium row."""
    from pyspark.sql.functions import col, get_json_object

    value = col("value").cast("string")
    fields = {
        "station_key": get_json_object(value, "$.station_key"),
        "product": get_json_object(value, "$.product"),
        "publish_date": get_json_object(value, "$.publish_date"),
        "price_cpl": get_json_object(value, "$.price_cpl").cast("double"),
        "trading_name": get_json_object(value, "$.trading_name"),
        "brand": get_json_object(value, "$.brand"),
        "address": get_json_object(value, "$.address"),
        "suburb": get_json_object(value, "$.suburb"),
        "postcode": get_json_object(value, "$.postcode"),
        "area": get_json_object(value, "$.area"),
        "region": get_json_object(value, "$.region"),
        "table_name": get_json_object(value, "$.__table"),
    }
    return raw.select(*[expression.alias(name) for name, expression in fields.items()])


def apply_price_batch(batch_df, batch_id: int, price_path: str) -> None:
    del batch_id
    spark = batch_df.sparkSession
    batch_df.createOrReplaceTempView("price_updates")
    spark.sql(PRICE_MERGE_SQL.format(price_path=price_path))


def apply_station_batch(batch_df, batch_id: int, station_path: str) -> None:
    del batch_id
    spark = batch_df.sparkSession
    batch_df.createOrReplaceTempView("station_raw")
    spark.sql(STATION_HASH_SQL).createOrReplaceTempView("station_updates")
    spark.sql(SCD2_CLOSE_SQL.format(station_path=station_path))
    spark.sql(SCD2_UPSERT_SQL.format(station_path=station_path))


def _kafka(spark, topic: str):
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "redpanda:9092")
    return (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .load()
    )


def start_streams(spark, data_root: str = "/data/delta") -> None:
    price_path = f"{data_root}/retail_price"
    station_path = f"{data_root}/station_dim"
    prices = parse_debezium(_kafka(spark, "fuelwatch.public.retail_price"))
    stations = parse_debezium(_kafka(spark, "fuelwatch.public.station"))
    prices.writeStream.foreachBatch(
        lambda batch, batch_id: apply_price_batch(batch, batch_id, price_path)
    ).option("checkpointLocation", f"{data_root}/checkpoints/retail_price").start()
    stations.writeStream.foreachBatch(
        lambda batch, batch_id: apply_station_batch(batch, batch_id, station_path)
    ).option("checkpointLocation", f"{data_root}/checkpoints/station_dim").start()
    spark.streams.awaitAnyTermination()


def main() -> None:
    spark = build_session()
    start_streams(spark, os.environ.get("DELTA_ROOT", "/data/delta"))


if __name__ == "__main__":
    main()
