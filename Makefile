PYTHON ?= python3
export PYTHONPATH := src

.PHONY: setup data batch test ci benchmark site up down load-oltp connector

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements.txt

data:
	PYTHONPATH=src $(PYTHON) -m fuel_shock.ingest

batch:
	PYTHONPATH=src $(PYTHON) -m fuel_shock.batch --offline

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

ci: test
	PYTHONPATH=src $(PYTHON) -m fuel_shock.batch --offline
	PYTHONPATH=src $(PYTHON) -m fuel_shock.benchmark --quick

benchmark:
	PYTHONPATH=src $(PYTHON) -m fuel_shock.benchmark

site:
	$(PYTHON) -m http.server 8080 --directory site

up:
	docker compose up -d --build

down:
	docker compose down

load-oltp:
	bash scripts/load_oltp.sh

connector:
	bash infra/debezium/register-connector.sh
