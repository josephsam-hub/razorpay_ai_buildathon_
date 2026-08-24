"""
LedgerLens Phase 2 — Dataset Configuration
============================================
DatasetConfig Pydantic model + YAML loader.

Config files live in data/synthetic/config_*.yaml.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class MerchantTierConfig(BaseModel):
    """Fee rate and settlement cycle for one merchant tier."""

    fee_rate: Decimal
    settlement_cycle_days: int = Field(ge=1, le=3)

    @field_validator("fee_rate")
    @classmethod
    def fee_rate_range(cls, v: Decimal) -> Decimal:
        if not (Decimal("0.001") <= v <= Decimal("0.05")):
            raise ValueError(f"fee_rate {v} outside [0.001, 0.05]")
        return v


class CorruptionRateConfig(BaseModel):
    """
    Proportion of payments to receive each discrepancy type.
    All rates must sum to <= 1.0 (remainder are clean cases).
    """

    missing_settlement: float = Field(default=0.05, ge=0.0, le=1.0)
    missing_bank_entry: float = Field(default=0.04, ge=0.0, le=1.0)
    missing_ledger_entry: float = Field(default=0.04, ge=0.0, le=1.0)
    amount_mismatch: float = Field(default=0.05, ge=0.0, le=1.0)
    date_mismatch: float = Field(default=0.04, ge=0.0, le=1.0)
    duplicate_bank_entry: float = Field(default=0.03, ge=0.0, le=1.0)
    settlement_fee_variance: float = Field(default=0.03, ge=0.0, le=1.0)
    orphan_bank_entry: float = Field(default=0.02, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def rates_sum_le_one(self) -> "CorruptionRateConfig":
        total = sum([
            self.missing_settlement,
            self.missing_bank_entry,
            self.missing_ledger_entry,
            self.amount_mismatch,
            self.date_mismatch,
            self.duplicate_bank_entry,
            self.settlement_fee_variance,
            self.orphan_bank_entry,
        ])
        if total > 1.0:
            raise ValueError(
                f"Corruption rates sum to {total:.4f} which exceeds 1.0. "
                "Reduce one or more rates."
            )
        return self

    @property
    def clean_rate(self) -> float:
        return 1.0 - sum([
            self.missing_settlement,
            self.missing_bank_entry,
            self.missing_ledger_entry,
            self.amount_mismatch,
            self.date_mismatch,
            self.duplicate_bank_entry,
            self.settlement_fee_variance,
            self.orphan_bank_entry,
        ])


class PaymentAmountConfig(BaseModel):
    """Controls the range of seeded payment amounts."""

    min_amount: Decimal = Decimal("100.00")
    max_amount: Decimal = Decimal("50000.00")
    round_to_paisa: bool = True  # round to 2 decimal places

    @model_validator(mode="after")
    def min_lt_max(self) -> "PaymentAmountConfig":
        if self.min_amount >= self.max_amount:
            raise ValueError("min_amount must be less than max_amount")
        return self


class DatasetConfig(BaseModel):
    """
    Full configuration for one dataset generation run.
    Loaded from YAML via load_config().
    """

    version: str = Field(description="e.g. '1.0'")
    n_payments: int = Field(ge=10, description="total number of payments")
    n_merchants: int = Field(ge=1, le=20, description="number of merchant entities")
    seed: int = Field(description="master random seed")
    currency: str = "INR"

    start_date: str = Field(description="ISO date string e.g. '2026-08-01'")
    end_date: str = Field(description="ISO date string e.g. '2026-08-31'")

    payment_amount: PaymentAmountConfig = Field(
        default_factory=PaymentAmountConfig
    )

    merchant_tiers: dict[str, MerchantTierConfig] = Field(
        default_factory=lambda: {
            "T1": MerchantTierConfig(fee_rate=Decimal("0.0175"), settlement_cycle_days=1),
            "T2": MerchantTierConfig(fee_rate=Decimal("0.0200"), settlement_cycle_days=2),
            "T3": MerchantTierConfig(fee_rate=Decimal("0.0250"), settlement_cycle_days=3),
        }
    )

    corruption: CorruptionRateConfig = Field(
        default_factory=CorruptionRateConfig
    )

    # Settlement batch size range (Tech Lead Q2: variable 1-5)
    min_batch_size: int = Field(default=1, ge=1, le=5)
    max_batch_size: int = Field(default=5, ge=1, le=5)

    output_parquet: bool = Field(
        default=False,
        description="Also write .parquet files alongside .csv"
    )

    @model_validator(mode="after")
    def batch_size_valid(self) -> "DatasetConfig":
        if self.min_batch_size > self.max_batch_size:
            raise ValueError("min_batch_size must be <= max_batch_size")
        return self


def load_config(path: Path) -> DatasetConfig:
    """Load and validate a DatasetConfig from a YAML file."""
    text = path.read_text(encoding="utf-8")
    raw: dict[str, Any] = yaml.safe_load(text)
    return DatasetConfig.model_validate(raw)


def hash_config_file(path: Path) -> str:
    """Return sha256:<hex> of the raw YAML config file."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"
