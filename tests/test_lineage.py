import json

from fuel_shock.lineage import emit, emit_batch, event


def test_event_has_the_openlineage_fields():
    payload = event("serve.dashboard", ["duckdb.marts"], ["site.dashboard"], run_id="abc")
    assert payload["eventType"] == "COMPLETE"
    assert payload["job"]["namespace"] == "fuel-shock-radar"
    assert payload["job"]["name"] == "serve.dashboard"
    assert payload["inputs"][0]["name"] == "duckdb.marts"
    assert payload["outputs"][0]["name"] == "site.dashboard"
    assert payload["run"]["runId"] == "abc"


def test_emit_writes_every_batch_job(tmp_path):
    paths = emit_batch(tmp_path)
    names = {path.name for path in paths}
    assert "serve_dashboard.json" in names
    assert "quality_expectations.json" in names
    body = json.loads((tmp_path / "ingest_retail.json").read_text())
    assert body["eventType"] == "COMPLETE"
    written = emit(event("serve.dashboard", ["a"], ["b"]), tmp_path)
    assert written.exists()
