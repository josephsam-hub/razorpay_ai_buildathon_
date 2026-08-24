"""
Tests — Writer: files are written correctly and row counts match metadata.json.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from app.data.generator.config import DatasetConfig
from app.data.generator.world import generate
from app.data.generator.writer import write_dataset


@pytest.fixture(scope="module")
def write_config():
    return DatasetConfig.model_validate({
        "version": "test",
        "n_payments": 25,
        "n_merchants": 3,
        "seed": 321,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "corruption": {
            "missing_settlement": 0.04,
            "missing_bank_entry": 0.04,
            "amount_mismatch": 0.04,
            "date_mismatch": 0.04,
            "duplicate_bank_entry": 0.0,
            "settlement_fee_variance": 0.0,
            "orphan_bank_entry": 0.0,
            "missing_ledger_entry": 0.04,
        },
    })


@pytest.fixture(scope="module")
def written_dataset(tmp_path_factory, write_config):
    """Generate and write a dataset once for the module scope."""
    out_dir = tmp_path_factory.mktemp("dataset")
    clean, observed = generate(write_config)
    metadata = write_dataset(out_dir, write_config, observed, "sha256:test_hash")
    return out_dir, observed, metadata


class TestFilesExist:
    def test_all_csv_files_created(self, written_dataset):
        out_dir, _, _ = written_dataset
        expected_files = [
            "merchants.csv",
            "payments.csv",
            "settlements.csv",
            "bank_entries.csv",
            "ledger_entries.csv",
            "ground_truth.csv",
            "corruption_events.csv",
            "metadata.json",
        ]
        for fname in expected_files:
            assert (out_dir / fname).exists(), f"Missing file: {fname}"


class TestRowCounts:
    def test_payments_csv_row_count(self, written_dataset):
        out_dir, observed, metadata = written_dataset
        with (out_dir / "payments.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(observed.payments)
        assert len(rows) == metadata.record_counts["payments"]

    def test_ground_truth_row_count_equals_payments(self, written_dataset):
        out_dir, observed, metadata = written_dataset
        with (out_dir / "ground_truth.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        # One ground truth row per payment
        assert len(rows) == len(observed.payments)

    def test_corruption_events_count_matches_metadata(self, written_dataset):
        out_dir, observed, metadata = written_dataset
        with (out_dir / "corruption_events.csv").open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(observed.corruption_events)
        assert len(rows) == metadata.record_counts["corruption_events"]


class TestMetadataJson:
    def test_metadata_json_parseable(self, written_dataset):
        out_dir, _, _ = written_dataset
        raw = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
        assert "seed" in raw
        assert "generator_version" in raw
        assert "record_counts" in raw
        assert "corruption_profile" in raw
        assert "file_hashes" in raw

    def test_metadata_seed_matches_config(self, written_dataset, write_config):
        out_dir, _, metadata = written_dataset
        assert metadata.seed == write_config.seed

    def test_file_hashes_present(self, written_dataset):
        out_dir, _, metadata = written_dataset
        for fname in ["payments.csv", "ground_truth.csv", "corruption_events.csv"]:
            assert fname in metadata.file_hashes
            assert metadata.file_hashes[fname].startswith("sha256:")

    def test_metadata_record_counts_accurate(self, written_dataset):
        out_dir, observed, metadata = written_dataset
        assert metadata.record_counts["payments"] == len(observed.payments)
        assert metadata.record_counts["merchants"] == len(observed.merchants)


class TestCsvFields:
    def test_payments_csv_has_required_columns(self, written_dataset):
        out_dir, _, _ = written_dataset
        with (out_dir / "payments.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        required = {"payment_id", "merchant_id", "amount", "payment_date", "gateway_ref"}
        assert required.issubset(set(fieldnames))

    def test_corruption_events_csv_has_required_columns(self, written_dataset):
        out_dir, _, _ = written_dataset
        with (out_dir / "corruption_events.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        required = {
            "corruption_id", "case_id", "corruption_type",
            "original_value", "observed_value", "applied_seed",
        }
        assert required.issubset(set(fieldnames))

    def test_ledger_entries_csv_has_allocated_amount(self, written_dataset):
        out_dir, _, _ = written_dataset
        with (out_dir / "ledger_entries.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        # Must use 'allocated_amount', NOT 'credit_amount'
        assert "allocated_amount" in fieldnames
        assert "credit_amount" not in fieldnames
