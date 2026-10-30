#!/bin/bash
# Load the latest fortnight of unleaded prices into Postgres so Debezium has a stream to read.
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "${root}"
mkdir -p data/raw/oltp
PYTHONPATH=src .venv/bin/python - <<'PY'
import duckdb
from pathlib import Path
out = Path("data/raw/oltp")
retail = "data/curated/retail.parquet"
con = duckdb.connect()
con.execute(f"""
COPY (
  SELECT DISTINCT station_key, trading_name, brand, address, suburb, postcode, area, region
  FROM read_parquet('{retail}')
  WHERE publish_date >= (SELECT max(publish_date) FROM read_parquet('{retail}')) - INTERVAL 14 DAY
    AND product = 'ULP'
) TO '{(out / "station.csv").as_posix()}' (HEADER, DELIMITER ',')
""")
con.execute(f"""
COPY (
  SELECT station_key, publish_date, product, price_cpl, trading_name, suburb, region
  FROM read_parquet('{retail}')
  WHERE publish_date >= (SELECT max(publish_date) FROM read_parquet('{retail}')) - INTERVAL 14 DAY
    AND product = 'ULP'
) TO '{(out / "retail_price.csv").as_posix()}' (HEADER, DELIMITER ',')
""")
print("wrote", out)
PY
docker compose exec -T postgres psql -U fuelwatch -d fuelwatch -c "TRUNCATE retail_price, station CASCADE;"
docker compose exec -T postgres psql -U fuelwatch -d fuelwatch \
  -c "\\copy station (station_key, trading_name, brand, address, suburb, postcode, area, region) FROM STDIN WITH (FORMAT csv, HEADER true)" \
  < data/raw/oltp/station.csv
docker compose exec -T postgres psql -U fuelwatch -d fuelwatch \
  -c "\\copy retail_price (station_key, publish_date, product, price_cpl, trading_name, suburb, region) FROM STDIN WITH (FORMAT csv, HEADER true)" \
  < data/raw/oltp/retail_price.csv
echo "Loaded station and retail_price."
