"""
LedgerLens Phase 2 — Dataset Writer
=====================================
Writes CSV files, optional Parquet files, and metadata.json.

Outputs per dataset:
  merchants.csv
  payments.csv
  settlements.csv
  bank_entries.csv
  ledger_entries.csv
  ground_truth.csv
  corruption_events.csv
  metadata.json

File hashes are SHA-256 of each CSV/JSON file (for reproducibility verification).
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.data.generator.config import DatasetConfig
from app.data.generator.models import (
    BankEntry,
    CorruptionEvent,
    DatasetMetadata,
    GroundTruth,
    LedgerEntry,
    Merchant,
    Payment,
    Settlement,
)
from app.data.generator.world import ObservedWorld

# Generator version — increment when generation logic changes
GENERATOR_VERSION = "0.1.0"


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _hash_file(path: Path) -> str:
    """Return sha256:<hex> of a file."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Write a list of dicts to a CSV file."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _merchant_to_row(m: Merchant) -> dict:
    return {
        "merchant_id": m.merchant_id,
        "name": m.name,
        "city": m.city,
        "settlement_tier": m.settlement_tier,
        "settlement_cycle_days": m.settlement_cycle_days,
        "fee_rate": str(m.fee_rate),
        "currency": m.currency,
    }


def _payment_to_row(p: Payment) -> dict:
    return {
        "payment_id": p.payment_id,
        "merchant_id": p.merchant_id,
        "amount": str(p.amount),
        "currency": p.currency,
        "payment_date": p.payment_date.isoformat(),
        "gateway_ref": p.gateway_ref,
        "status": p.status,
    }


def _settlement_to_row(s: Settlement) -> dict:
    return {
        "settlement_id": s.settlement_id,
        "merchant_id": s.merchant_id,
        "payment_ids": "|".join(s.payment_ids),  # pipe-separated list
        "settlement_date": s.settlement_date.isoformat(),
        "gross_amount": str(s.gross_amount),
        "fee_amount": str(s.fee_amount),
        "net_amount": str(s.net_amount),
        "settlement_ref": s.settlement_ref,
        "status": s.status,
    }


def _bank_entry_to_row(b: BankEntry) -> dict:
    return {
        "bank_entry_id": b.bank_entry_id,
        "merchant_id": b.merchant_id,
        "settlement_ref": b.settlement_ref,
        "credit_amount": str(b.credit_amount),
        "value_date": b.value_date.isoformat(),
        "bank_ref": b.bank_ref,
        "narration": b.narration,
    }


def _ledger_entry_to_row(le: LedgerEntry) -> dict:
    return {
        "ledger_entry_id": le.ledger_entry_id,
        "merchant_id": le.merchant_id,
        "payment_id": le.payment_id,
        "settlement_id": le.settlement_id,
        "bank_entry_id": le.bank_entry_id,
        "allocated_amount": str(le.allocated_amount),
        "posting_date": le.posting_date.isoformat(),
        "account_code": le.account_code,
        "status": le.status,
        "reconciled_flag": str(le.reconciled_flag),
    }


def _corruption_event_to_row(ce: CorruptionEvent) -> dict:
    return {
        "corruption_id": ce.corruption_id,
        "case_id": ce.case_id,
        "corruption_type": ce.corruption_type,
        "target_entity": ce.target_entity,
        "target_record_id": ce.target_record_id,
        "original_value": ce.original_value,
        "observed_value": ce.observed_value,
        "delta": ce.delta if ce.delta is not None else "",
        "applied_seed": str(ce.applied_seed),
    }


def _ground_truth_to_row(gt: GroundTruth) -> dict:
    return {
        "ground_truth_id": gt.ground_truth_id,
        "payment_id": gt.payment_id,
        "expected_decision": gt.expected_decision,
        "discrepancy_type": gt.discrepancy_type or "",
        "discrepancy_code": gt.discrepancy_code or "",
        "corruption_id": gt.corruption_id or "",
        "injected_layer": gt.injected_layer or "",
        "clean_settlement_net_amount": (
            str(gt.clean_settlement_net_amount)
            if gt.clean_settlement_net_amount is not None
            else ""
        ),
        "clean_allocated_amount": (
            str(gt.clean_allocated_amount)
            if gt.clean_allocated_amount is not None
            else ""
        ),
        "notes": gt.notes,
    }


def write_dataset(
    output_dir: Path,
    config: DatasetConfig,
    observed: ObservedWorld,
    config_hash: str,
) -> DatasetMetadata:
    """
    Write all dataset files to output_dir and return the DatasetMetadata.

    Creates output_dir if it does not exist.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write CSV files
    files = {
        "merchants.csv": [_merchant_to_row(m) for m in observed.merchants],
        "payments.csv": [_payment_to_row(p) for p in observed.payments],
        "settlements.csv": [_settlement_to_row(s) for s in observed.settlements],
        "bank_entries.csv": [_bank_entry_to_row(b) for b in observed.bank_entries],
        "ledger_entries.csv": [_ledger_entry_to_row(le) for le in observed.ledger_entries],
        "ground_truth.csv": [_ground_truth_to_row(gt) for gt in observed.ground_truth],
        "corruption_events.csv": [_corruption_event_to_row(ce) for ce in observed.corruption_events],
    }

    for filename, rows in files.items():
        _write_csv(output_dir / filename, rows)

    # Optionally write Parquet
    if config.output_parquet:
        try:
            import polars as pl

            for filename, rows in files.items():
                if rows:
                    stem = filename.replace(".csv", "")
                    df = pl.DataFrame(rows)
                    df.write_parquet(output_dir / f"{stem}.parquet")
        except ImportError:
            pass  # polars not installed — skip Parquet silently

    # Compute file hashes
    file_hashes: dict[str, str] = {}
    for filename in files:
        fpath = output_dir / filename
        if fpath.exists():
            file_hashes[filename] = _hash_file(fpath)

    # Build corruption profile
    corruption_profile: dict[str, int] = {}
    for ce in observed.corruption_events:
        corruption_profile[ce.corruption_type] = (
            corruption_profile.get(ce.corruption_type, 0) + 1
        )
    clean_count = sum(
        1 for gt in observed.ground_truth if gt.expected_decision == "AUTO_MATCH"
    )
    corruption_profile["clean"] = clean_count

    # Record counts
    record_counts = {
        "merchants": len(observed.merchants),
        "payments": len(observed.payments),
        "settlements": len(observed.settlements),
        "bank_entries": len(observed.bank_entries),
        "ledger_entries": len(observed.ledger_entries),
        "ground_truth": len(observed.ground_truth),
        "corruption_events": len(observed.corruption_events),
    }

    metadata = DatasetMetadata(
        dataset_version=config.version,
        generator_version=GENERATOR_VERSION,
        seed=config.seed,
        currency=config.currency,
        generation_timestamp=datetime.now(tz=timezone.utc),
        record_counts=record_counts,
        corruption_profile=corruption_profile,
        config_hash=config_hash,
        file_hashes=file_hashes,
    )

    # Write metadata.json
    metadata_path = output_dir / "metadata.json"
    metadata_dict = metadata.model_dump()
    # Convert datetime to ISO string and Decimal to str for JSON
    metadata_dict["generation_timestamp"] = metadata.generation_timestamp.isoformat()
    metadata_path.write_text(
        json.dumps(metadata_dict, indent=2, default=_decimal_default),
        encoding="utf-8",
    )

    return metadata
