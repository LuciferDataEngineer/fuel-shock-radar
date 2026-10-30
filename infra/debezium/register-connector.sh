#!/bin/bash
# Register the FuelWatch Postgres connector with Debezium Connect.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
connect_url="${CONNECT_URL:-http://localhost:8083}"
curl --fail-with-body -sS -X POST \
  -H "Content-Type: application/json" \
  --data @"${root}/infra/debezium/fuelwatch-connector.json" \
  "${connect_url}/connectors"
echo
