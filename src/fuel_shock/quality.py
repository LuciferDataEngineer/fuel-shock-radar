"""Great Expectations checks and Data Docs for the curated extracts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

os.environ.setdefault("GX_ANALYTICS_ENABLED", "false")

import great_expectations as gx
import pandas as pd
from great_expectations.expectations import (
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToNotBeNull,
    ExpectCompoundColumnsToBeUnique,
)

REGIONS = (
    "Metro",
    "Gascoyne",
    "Goldfields-Esperance",
    "Great Southern",
    "Kimberley",
    "Mid-West",
    "Peel",
    "Pilbara",
    "South-West",
    "Wheatbelt",
)
PRODUCTS = ("ULP", "Diesel", "Brand Diesel")


def _suite(name: str, expectations: list) -> gx.ExpectationSuite:
    suite = gx.ExpectationSuite(name=name)
    for expectation in expectations:
        suite.add_expectation(expectation)
    return suite


def _store(context, suite: gx.ExpectationSuite) -> gx.ExpectationSuite:
    existing = {item.name for item in context.suites.all()}
    if suite.name in existing:
        context.suites.delete(suite.name)
    return context.suites.add(suite)


def validate(frames: dict[str, pd.DataFrame], docs_dir: Path) -> dict:
    """Run expectation suites and write Data Docs under ``docs_dir``.

    Returns a summary with ``success`` and per-suite results. Raises nothing
    for a failed expectation; the caller decides whether to stop the build.
    """
    docs_dir.mkdir(parents=True, exist_ok=True)
    project_dir = docs_dir / "_gx_project"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    context = gx.get_context(mode="file", project_root_dir=str(project_dir))
    source = context.data_sources.add_or_update_pandas("fuel_shock")

    specs = {
        "retail": _suite(
            "retail_prices",
            [
                ExpectColumnValuesToNotBeNull(column="publish_date"),
                ExpectColumnValuesToNotBeNull(column="station_key"),
                ExpectColumnValuesToNotBeNull(column="price_cpl"),
                ExpectColumnValuesToBeBetween(column="price_cpl", min_value=70, max_value=500),
                ExpectColumnValuesToBeInSet(column="product", value_set=list(PRODUCTS)),
                ExpectColumnValuesToBeInSet(column="region", value_set=list(REGIONS)),
                ExpectCompoundColumnsToBeUnique(
                    column_list=["station_key", "publish_date", "product"]
                ),
            ],
        ),
        "wholesale": _suite(
            "terminal_gate_prices",
            [
                ExpectColumnValuesToNotBeNull(column="publish_date"),
                ExpectColumnValuesToNotBeNull(column="terminal"),
                ExpectColumnValuesToBeBetween(column="price_cpl", min_value=40, max_value=400),
                ExpectColumnValuesToBeInSet(column="product", value_set=list(PRODUCTS)),
            ],
        ),
        "brent": _suite(
            "brent_crude",
            [
                ExpectColumnValuesToNotBeNull(column="observe_date"),
                ExpectColumnValuesToBeBetween(column="brent_usd", min_value=5, max_value=250),
            ],
        ),
    }

    results = {}
    success = True
    for name, suite in specs.items():
        frame = frames[name]
        asset_name = f"{name}_asset"
        if asset_name in {asset.name for asset in source.assets}:
            source.delete_asset(asset_name)
        asset = source.add_dataframe_asset(asset_name)
        batch_definition = asset.add_batch_definition_whole_dataframe("whole")
        stored = _store(context, suite)
        definition_name = f"{name}_check"
        existing_defs = {item.name for item in context.validation_definitions.all()}
        if definition_name in existing_defs:
            context.validation_definitions.delete(definition_name)
        definition = context.validation_definitions.add(
            gx.ValidationDefinition(name=definition_name, data=batch_definition, suite=stored)
        )
        result = definition.run(batch_parameters={"dataframe": frame})
        results[name] = {
            "success": bool(result.success),
            "statistics": dict(result.statistics),
        }
        success = success and bool(result.success)

    context.build_data_docs()
    built = context.build_data_docs()
    # File context writes under project_dir/gx/uncommitted/data_docs/local_site.
    site = project_dir / "gx" / "uncommitted" / "data_docs" / "local_site"
    index = site / "index.html"
    if not index.exists():
        # Some versions return the site path from the second call.
        for value in (built or {}).values():
            candidate = Path(str(value)) / "index.html"
            if candidate.exists():
                index = candidate
                site = candidate.parent
                break
    public = docs_dir / "index.html"
    if index.exists() and index.resolve() != public.resolve():
        public.write_bytes(index.read_bytes())
    return {"success": success, "suites": results, "data_docs": str(site if index.exists() else docs_dir)}
