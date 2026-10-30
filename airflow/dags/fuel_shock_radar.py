"""Airflow Datasets for Fuel Shock Radar.

``fuel_shock_ingest`` lands the extracts and publishes a dataset.
``fuel_shock_publish`` is scheduled on that dataset and rebuilds the dashboard.
"""

from datetime import datetime

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator

CURATED = Dataset("file://fuel-shock-radar/data/curated")
SERVING = Dataset("duckdb://fuel-shock-radar/fuel_shock")
DASHBOARD = Dataset("site://fuel-shock-radar/dashboard")


def _ingest() -> None:
    from fuel_shock.ingest import ingest

    ingest()


def _publish() -> None:
    from fuel_shock.batch import run

    run(offline=True)


with DAG(
    dag_id="fuel_shock_ingest",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["fuel-shock-radar"],
) as ingest_dag:
    PythonOperator(
        task_id="fetch_fuelwatch_and_brent",
        python_callable=_ingest,
        outlets=[CURATED],
    )

with DAG(
    dag_id="fuel_shock_publish",
    start_date=datetime(2026, 1, 1),
    schedule=[CURATED],
    catchup=False,
    tags=["fuel-shock-radar"],
) as publish_dag:
    PythonOperator(
        task_id="build_dashboard",
        python_callable=_publish,
        outlets=[SERVING, DASHBOARD],
    )
