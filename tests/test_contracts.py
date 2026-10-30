import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_debezium_connector_targets_the_oltp_tables():
    payload = json.loads((ROOT / "infra/debezium/fuelwatch-connector.json").read_text())
    config = payload["config"]
    assert config["connector.class"].endswith("PostgresConnector")
    assert config["plugin.name"] == "pgoutput"
    assert "public.retail_price" in config["table.include.list"]
    assert "ExtractNewRecordState" in config["transforms.unwrap.type"]


def test_airflow_dag_uses_datasets():
    source = (ROOT / "airflow/dags/fuel_shock_radar.py").read_text()
    assert "from airflow.datasets import Dataset" in source
    assert "schedule=[CURATED]" in source
    assert "outlets=[CURATED]" in source
    assert "fuel_shock_publish" in source
    compile(source, "fuel_shock_radar.py", "exec")


def test_spark_job_merges_prices_and_closes_station_versions():
    source = (ROOT / "src/fuel_shock/spark_job.py").read_text()
    assert "MERGE INTO" in source
    assert "is_current = false" in source
    assert "foreachBatch" in source
    assert "readStream" in source
    compile(source, "spark_job.py", "exec")


def test_dashboard_page_has_no_pipeline_jargon():
    banned = ("kafka", "debezium", "airflow", "duckdb", "parquet", "spark", "marquez", "redpanda")
    for name in ("index.html", "app.js", "styles.css"):
        text = (ROOT / "site" / name).read_text().lower()
        for word in banned:
            assert word not in text, name
    html = (ROOT / "site/index.html").read_text()
    assert 'id="cards"' in html
    assert 'id="chart-week"' in html
    assert 'id="chart-wholesale"' in html
    assert 'id="chart-regions"' in html


def test_pages_workflow_uploads_and_deploys():
    text = (ROOT / ".github/workflows/pages.yml").read_text()
    assert "actions/upload-pages-artifact@" in text
    assert "actions/deploy-pages@" in text
    assert "branches:" in text and "main" in text
