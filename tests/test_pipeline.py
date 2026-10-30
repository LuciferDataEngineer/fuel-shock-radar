"""Deterministic ETL acceptance tests using fictional FuelWatch-shaped records."""
from __future__ import annotations

from contextlib import closing
import copy
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fuel_radar import pipeline
from fuel_radar.pipeline import run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"


class FuelPipelineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.data_dir = self.work / "data"
        with (FIXTURES / "september_2026.csv").open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            self.headers = reader.fieldnames
            self.september = list(reader)
        with (FIXTURES / "august_2026.csv").open(newline="", encoding="utf-8") as stream:
            self.august = list(csv.DictReader(stream))
        self.september_file = self.work / "september.csv"
        self.august_file = self.work / "august.csv"
        self.write_inputs()

    def write_inputs(self):
        for path, rows in ((self.september_file, self.september), (self.august_file, self.august)):
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=self.headers)
                writer.writeheader()
                writer.writerows(rows)

    def ingest(self, *, include_august=False, as_of="2026-10-30"):
        self.write_inputs()
        files = [self.september_file]
        if include_august:
            files.insert(0, self.august_file)
        return run_pipeline(self.data_dir, files=files, as_of=as_of)

    def rows(self, sql, parameters=()):
        with closing(duckdb.connect(str(self.data_dir / "warehouse.duckdb"), read_only=True)) as connection:
            cursor = connection.execute(sql, parameters)
            columns = [field[0] for field in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def scalar(self, sql, parameters=()):
        return next(iter(self.rows(sql, parameters)[0].values()))

    def trusted_rows(self):
        return self.rows("SELECT * FROM price_observations ORDER BY observed_date,site_id,product")

    def assert_failed_without_mutation(self, baseline):
        with self.assertRaises((ValueError, RuntimeError)):
            self.ingest()
        self.assertEqual(self.trusted_rows(), baseline)
        self.assertGreaterEqual(self.scalar("SELECT COUNT(*) FROM pipeline_runs WHERE status='failed'"), 1)

    def test_complete_snapshot_loads_exact_decimal_prices(self):
        summary = self.ingest(include_august=True)
        self.assertIsInstance(summary, dict)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 67)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(DISTINCT site_id) FROM price_observations"), 4)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM pipeline_runs WHERE status='success'"), 1)
        price = self.scalar("SELECT price_cpl FROM price_observations WHERE month=DATE '2026-08-01' LIMIT 1")
        self.assertIsInstance(price, Decimal)
        self.assertEqual(price, Decimal("199.9"))

    def test_identical_replay_is_idempotent(self):
        self.ingest()
        original = self.trusted_rows()
        self.ingest()
        self.assertEqual(self.trusted_rows(), original)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 36)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM pipeline_runs WHERE status='success'"), 2)

    def test_corrected_month_replaces_removed_and_changed_rows_only_in_scope(self):
        self.ingest(include_august=True)
        august_before = self.rows("SELECT * FROM price_observations WHERE month=DATE '2026-08-01' ORDER BY observed_date,site_id")
        august_source = self.rows("SELECT * FROM source_months WHERE month=DATE '2026-08-01'")
        self.september = [row for row in self.september if row["TRADING_NAME"] != "Example Entrant"]
        for row in self.september:
            if row["TRADING_NAME"] == "Example Alpha" and row["PUBLISH_DATE"] == "01/09/2026":
                row["PRODUCT_PRICE"] = "155.00"
        self.ingest()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations WHERE month=DATE '2026-09-01'"), 35)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations WHERE site_name='Example Entrant'"), 0)
        self.assertEqual(self.scalar("SELECT price_cpl FROM price_observations WHERE site_name='Example Alpha' AND observed_date=DATE '2026-09-01'"), Decimal("155.0"))
        self.assertEqual(august_before, self.rows("SELECT * FROM price_observations WHERE month=DATE '2026-08-01' ORDER BY observed_date,site_id"))
        self.assertEqual(august_source, self.rows("SELECT * FROM source_months WHERE month=DATE '2026-08-01'"))

    def test_nonfinite_nonpositive_or_inexact_prices_cannot_replace_trusted_data(self):
        self.ingest()
        original = self.trusted_rows()
        original_price = self.september[0]["PRODUCT_PRICE"]
        for invalid in ("nan", "Infinity", "-Infinity", "0", "-1", "175.25", "100000.0"):
            with self.subTest(price=invalid):
                self.september[0]["PRODUCT_PRICE"] = invalid
                self.assert_failed_without_mutation(original)
        self.september[0]["PRODUCT_PRICE"] = original_price

    def test_duplicate_site_date_product_is_rejected_and_audited(self):
        self.ingest()
        original = self.trusted_rows()
        self.september.append(copy.deepcopy(self.september[0]))
        self.assert_failed_without_mutation(original)

    def test_missing_whole_day_rejects_partial_month_without_removing_rows(self):
        self.ingest()
        original = self.trusted_rows()
        self.september = [row for row in self.september if row["PUBLISH_DATE"] != "15/09/2026"]
        self.assert_failed_without_mutation(original)

    def test_one_file_cannot_silently_replace_multiple_months(self):
        self.ingest()
        original = self.trusted_rows()
        self.september.append(copy.deepcopy(self.august[0]))
        self.assert_failed_without_mutation(original)

    def test_publisher_url_month_mismatch_cannot_replace_trusted_data(self):
        self.ingest()
        original = self.trusted_rows()
        original_month = self.rows("SELECT * FROM source_months")
        wrong_month_url = "https://warsydprdstafuelwatch.blob.core.windows.net/historical-reports/FuelWatchRetail-08-2026.csv"
        with self.assertRaises(ValueError):
            run_pipeline(
                self.data_dir,
                files=[self.september_file],
                source_urls=[wrong_month_url],
                as_of="2026-10-30",
            )
        self.assertEqual(self.trusted_rows(), original)
        self.assertEqual(self.rows("SELECT * FROM source_months"), original_month)
        failures = self.rows("SELECT error FROM pipeline_runs WHERE status='failed'")
        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0]["error"])

    def test_current_and_future_months_are_rejected(self):
        for as_of in ("2026-09-30", "2026-08-31"):
            with self.subTest(as_of=as_of):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.ingest(as_of=as_of)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 0)

    def test_assessment_cannot_move_backwards_but_older_month_backfill_is_allowed(self):
        self.ingest(as_of="2026-10-30")
        original_rows = self.trusted_rows()
        pointer_file = self.data_dir / "exports" / "latest.json"
        original_pointer = pointer_file.read_text()
        with self.assertRaisesRegex(ValueError, "Assessment date cannot move backwards"):
            run_pipeline(self.data_dir, files=[self.august_file], as_of="2026-09-01")
        self.assertEqual(self.trusted_rows(), original_rows)
        self.assertEqual(pointer_file.read_text(), original_pointer)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 1)
        failures = self.rows("SELECT as_of,error FROM pipeline_runs WHERE status='failed'")
        self.assertEqual(len(failures), 1)
        self.assertIn("Assessment date cannot move backwards", failures[0]["error"])
        run_pipeline(self.data_dir, files=[self.august_file], as_of="2026-10-30")
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 67)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 2)
        self.assertEqual(original_rows, self.rows("SELECT * FROM price_observations WHERE month=DATE '2026-09-01' ORDER BY observed_date,site_id,product"))

    def test_brand_change_keeps_derived_identity(self):
        self.ingest()
        identities = self.rows("SELECT DISTINCT site_name,address,site_id FROM price_observations ORDER BY site_name,address")
        for row in self.september:
            row["BRAND_DESCRIPTION"] = "Different Synthetic Brand"
        self.ingest()
        self.assertEqual(identities, self.rows("SELECT DISTINCT site_name,address,site_id FROM price_observations ORDER BY site_name,address"))
        self.assertEqual(self.scalar("SELECT COUNT(DISTINCT brand) FROM price_observations"), 1)
        self.assertEqual(self.scalar("SELECT brand FROM price_observations LIMIT 1"), "Different Synthetic Brand")

    def test_different_trading_names_at_same_address_are_distinct_sites(self):
        additional = copy.deepcopy(next(row for row in self.september if row["TRADING_NAME"] == "Example Alpha"))
        additional["TRADING_NAME"] = "Example Separate Concession"
        self.september.append(additional)
        self.ingest()
        self.assertEqual(self.scalar("SELECT COUNT(DISTINCT site_id) FROM price_observations WHERE address='20 Fictional Road'"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 37)

    def test_missing_identity_field_is_rejected(self):
        self.ingest()
        original = self.trusted_rows()
        self.september[0]["ADDRESS"] = " "
        self.assert_failed_without_mutation(original)

    def test_matched_site_change_does_not_confuse_sample_composition_with_price_moves(self):
        self.ingest()
        paired = self.rows("SELECT * FROM matched_market_changes WHERE observed_date=DATE '2026-09-02' AND product='ULP'")[0]
        self.assertEqual(paired["paired_site_count"], 3)
        self.assertEqual(paired["mean_change_cpl"], 0)
        self.assertEqual(paired["median_change_cpl"], 0)
        market = self.rows("SELECT observed_date,site_count,median_cpl FROM daily_market_summary WHERE observed_date IN (DATE '2026-09-01',DATE '2026-09-02') ORDER BY observed_date")
        self.assertEqual([row["site_count"] for row in market], [3, 4])
        self.assertEqual([row["median_cpl"] for row in market], [Decimal("175.0"), Decimal("182.5")])
        changes = self.rows("SELECT site_name,change_cpl FROM matched_site_changes WHERE observed_date=DATE '2026-09-02' ORDER BY site_name")
        self.assertEqual({row["site_name"]: row["change_cpl"] for row in changes}, {"Example Alpha": Decimal("10.0"), "Example Anchor": Decimal("0.0"), "Example Bravo": Decimal("-10.0")})

    def test_site_observation_gap_is_not_a_day_on_day_change(self):
        self.ingest()
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM matched_site_changes WHERE site_name='Example Alpha' AND observed_date=DATE '2026-09-04'"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM matched_site_changes WHERE previous_date<>observed_date-INTERVAL 1 DAY"), 0)
        paired = self.rows("SELECT paired_site_count,mean_change_cpl FROM matched_market_changes WHERE observed_date=DATE '2026-09-04'")[0]
        self.assertEqual(paired["paired_site_count"], 1)
        self.assertEqual(paired["mean_change_cpl"], 0)

    def test_second_month_load_failure_rolls_back_first_month_and_retains_audit(self):
        real_replace = pipeline._replace_month
        calls = 0

        def fail_after_first_month(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected failure after first month was inserted")
            return real_replace(*args, **kwargs)

        with patch.object(pipeline, "_replace_month", side_effect=fail_after_first_month):
            with self.assertRaisesRegex(RuntimeError, "Injected failure"):
                self.ingest(include_august=True)
        self.assertEqual(calls, 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_artifacts"), 2)
        failure = self.rows("SELECT status,error FROM pipeline_runs")[0]
        self.assertEqual(failure["status"], "failed")
        self.assertIn("Injected failure", failure["error"])
        self.ingest(include_august=True)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM price_observations"), 67)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM source_months"), 2)

    def test_failed_export_preserves_previous_generation_and_replay_recovers(self):
        self.ingest()
        pointer_file = self.data_dir / "exports" / "latest.json"
        original_pointer = pointer_file.read_text()
        for row in self.september:
            if row["TRADING_NAME"] == "Example Alpha" and row["PUBLISH_DATE"] == "01/09/2026":
                row["PRODUCT_PRICE"] = "155.00"

        def fail_with_partial_generation(connection, directory, summary):
            generation = directory / summary["run_id"]
            generation.mkdir(parents=True)
            (generation / "price_observations.parquet").write_bytes(b"simulated incomplete export")
            raise OSError("Injected export failure")

        with patch.object(pipeline, "_export", side_effect=fail_with_partial_generation):
            with self.assertRaisesRegex(OSError, "Injected export failure"):
                self.ingest()
        self.assertEqual(pointer_file.read_text(), original_pointer)
        self.assertEqual(self.scalar("SELECT price_cpl FROM price_observations WHERE site_name='Example Alpha' AND observed_date=DATE '2026-09-01'"), Decimal("155.0"))
        error = self.rows("SELECT status,error FROM pipeline_runs WHERE error IS NOT NULL")[0]
        self.assertEqual(error["status"], "success")
        self.assertIn("Load succeeded; derived export failed", error["error"])
        self.ingest()
        new_pointer = json.loads(pointer_file.read_text())
        self.assertNotEqual(new_pointer, json.loads(original_pointer))
        restored = self.data_dir / "exports" / new_pointer["directory"] / "price_observations.parquet"
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM read_parquet(?)", (str(restored),)), 36)
        self.assertEqual(self.scalar("SELECT revision FROM source_months"), 2)

    def test_parquet_exports_round_trip_to_warehouse_values(self):
        self.ingest()
        pointer = json.loads((self.data_dir / "exports" / "latest.json").read_text())
        generation = self.data_dir / "exports" / pointer["directory"]
        export_contract = {
            "price_observations": "observed_date,site_id,product",
            "daily_market_summary": "observed_date,product,location",
            "matched_site_changes": "observed_date,site_id,product",
            "matched_market_changes": "observed_date,product,location",
        }
        for name, order in export_contract.items():
            with self.subTest(export=name):
                parquet = generation / f"{name}.parquet"
                self.assertTrue(parquet.is_file())
                expected = self.rows(f"SELECT * FROM {name} ORDER BY {order}")
                actual = self.rows(f"SELECT * FROM read_parquet(?) ORDER BY {order}", (str(parquet),))
                self.assertEqual(actual, expected)



if __name__ == "__main__":
    unittest.main()
