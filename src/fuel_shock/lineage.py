"""OpenLineage events for the batch build.

Events are written as JSON so they can be inspected without Marquez. When
MARQUEZ_URL or OPENLINEAGE_URL is set, each event is also posted to
``{url}/api/v1/lineage``, which is the Marquez OpenLineage endpoint.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

PRODUCER = "https://github.com/LuciferDataEngineer/fuel-shock-radar"
NAMESPACE = "fuel-shock-radar"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def event(job: str, inputs: list[str], outputs: list[str], run_id: str | None = None) -> dict:
    return {
        "eventType": "COMPLETE",
        "eventTime": _now(),
        "run": {"runId": run_id or str(uuid.uuid4())},
        "job": {"namespace": NAMESPACE, "name": job},
        "inputs": [{"namespace": NAMESPACE, "name": name} for name in inputs],
        "outputs": [{"namespace": NAMESPACE, "name": name} for name in outputs],
        "producer": PRODUCER,
        "schemaURL": "https://openlineage.io/spec/1-0-5/OpenLineage.json#/definitions/RunEvent",
    }


def emit(payload: dict, directory: Path, post_url: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['job']['name'].replace('.', '_')}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    url = post_url if post_url is not None else os.environ.get("MARQUEZ_URL") or os.environ.get("OPENLINEAGE_URL")
    if url:
        endpoint = url.rstrip("/") + "/api/v1/lineage"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                response.read()
        except URLError:
            # The file is the durable copy. Marquez may simply be down.
            pass
    return path


def emit_batch(directory: Path) -> list[Path]:
    """Lineage for one offline batch build of the dashboard."""
    jobs = [
        ("ingest.retail", ["fuelwatch.historic_retail"], ["curated.retail"]),
        ("ingest.wholesale", ["fuelwatch.historic_terminal_gate"], ["curated.wholesale"]),
        ("ingest.brent", ["fred.DCOILBRENTEU"], ["curated.brent"]),
        ("ingest.daily_feed", ["fuelwatch.daily_feed"], ["curated.daily_feed"]),
        (
            "transform.metrics",
            ["curated.retail", "curated.wholesale", "curated.brent", "curated.daily_feed"],
            ["duckdb.daily_metro", "duckdb.station_dim", "duckdb.margin_weekly"],
        ),
        ("quality.expectations", ["curated.retail", "curated.wholesale", "curated.brent"], ["gx.data_docs"]),
        ("serve.dashboard", ["duckdb.daily_metro", "duckdb.margin_weekly", "duckdb.station_dim"], ["site.dashboard"]),
    ]
    return [emit(event(name, inputs, outputs), directory) for name, inputs, outputs in jobs]
