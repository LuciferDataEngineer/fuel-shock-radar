#!/bin/bash
# Schema for the OLTP source Debezium reads. A second database is created for Marquez.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS station (
  station_key TEXT PRIMARY KEY,
  trading_name TEXT NOT NULL,
  brand TEXT,
  address TEXT,
  suburb TEXT,
  postcode TEXT,
  area TEXT,
  region TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retail_price (
  station_key TEXT NOT NULL REFERENCES station (station_key),
  publish_date DATE NOT NULL,
  product TEXT NOT NULL,
  price_cpl NUMERIC(8, 2) NOT NULL,
  trading_name TEXT,
  suburb TEXT,
  region TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (station_key, publish_date, product)
);

CREATE TABLE IF NOT EXISTS terminal_gate_price (
  terminal TEXT NOT NULL,
  publish_date DATE NOT NULL,
  product TEXT NOT NULL,
  brand TEXT,
  location TEXT,
  price_cpl NUMERIC(8, 2) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (terminal, publish_date, product)
);

CREATE TABLE IF NOT EXISTS crude_price (
  observe_date DATE PRIMARY KEY,
  brent_usd NUMERIC(8, 2) NOT NULL
);

DROP PUBLICATION IF EXISTS fuelwatch_pub;
CREATE PUBLICATION fuelwatch_pub FOR TABLE station, retail_price, terminal_gate_price;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'marquez') THEN
    CREATE ROLE marquez LOGIN PASSWORD 'marquez';
  END IF;
END
$$;
SELECT 'CREATE DATABASE marquez OWNER marquez'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'marquez')\gexec
SQL
