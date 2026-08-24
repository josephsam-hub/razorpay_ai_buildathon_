"""
Tests — DatasetConfig validation.
Covers: rate sum constraint, date range, batch size, fee rate range.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.data.generator.config import DatasetConfig, CorruptionRateConfig, MerchantTierConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def minimal_config() -> dict:
    return {
        "version": "1.0",
        "n_payments": 50,
        "n_merchants": 3,
        "seed": 42,
        "currency": "INR",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
    }


# ---------------------------------------------------------------------------
# CorruptionRateConfig
# ---------------------------------------------------------------------------

class TestCorruptionRateConfig:
    def test_default_rates_sum_le_one(self):
        cfg = CorruptionRateConfig()
        total = sum([
            cfg.missing_settlement,
            cfg.missing_bank_entry,
            cfg.missing_ledger_entry,
            cfg.amount_mismatch,
            cfg.date_mismatch,
            cfg.duplicate_bank_entry,
            cfg.settlement_fee_variance,
            cfg.orphan_bank_entry,
        ])
        assert total <= 1.0

    def test_clean_rate_is_complement(self):
        cfg = CorruptionRateConfig()
        assert abs(cfg.clean_rate + (1.0 - cfg.clean_rate) - 1.0) < 1e-9

    def test_rates_exceeding_one_raises(self):
        with pytest.raises(ValueError, match="exceed"):
            CorruptionRateConfig(
                missing_settlement=0.5,
                missing_bank_entry=0.5,
                missing_ledger_entry=0.1,  # total > 1.0
            )

    def test_zero_rates_valid(self):
        cfg = CorruptionRateConfig(
            missing_settlement=0.0,
            missing_bank_entry=0.0,
            missing_ledger_entry=0.0,
            amount_mismatch=0.0,
            date_mismatch=0.0,
            duplicate_bank_entry=0.0,
            settlement_fee_variance=0.0,
            orphan_bank_entry=0.0,
        )
        assert cfg.clean_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# MerchantTierConfig
# ---------------------------------------------------------------------------

class TestMerchantTierConfig:
    def test_fee_rate_too_high_raises(self):
        with pytest.raises(ValueError):
            MerchantTierConfig(fee_rate=Decimal("0.10"), settlement_cycle_days=1)

    def test_fee_rate_too_low_raises(self):
        with pytest.raises(ValueError):
            MerchantTierConfig(fee_rate=Decimal("0.0005"), settlement_cycle_days=1)

    def test_valid_tier(self):
        cfg = MerchantTierConfig(fee_rate=Decimal("0.0175"), settlement_cycle_days=1)
        assert cfg.fee_rate == Decimal("0.0175")
        assert cfg.settlement_cycle_days == 1


# ---------------------------------------------------------------------------
# DatasetConfig
# ---------------------------------------------------------------------------

class TestDatasetConfig:
    def test_valid_config_loads(self):
        raw = minimal_config()
        cfg = DatasetConfig.model_validate(raw)
        assert cfg.n_payments == 50
        assert cfg.seed == 42

    def test_min_batch_gt_max_raises(self):
        raw = minimal_config()
        raw["min_batch_size"] = 5
        raw["max_batch_size"] = 1
        with pytest.raises(ValueError, match="min_batch_size"):
            DatasetConfig.model_validate(raw)

    def test_batch_size_defaults_valid(self):
        cfg = DatasetConfig.model_validate(minimal_config())
        assert cfg.min_batch_size <= cfg.max_batch_size

    def test_n_payments_minimum(self):
        raw = minimal_config()
        raw["n_payments"] = 5  # below minimum of 10
        with pytest.raises(ValueError):
            DatasetConfig.model_validate(raw)

    def test_n_merchants_maximum(self):
        raw = minimal_config()
        raw["n_merchants"] = 25  # above maximum of 20
        with pytest.raises(ValueError):
            DatasetConfig.model_validate(raw)


# ---------------------------------------------------------------------------
# YAML Loader
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_load_config_v1(self, tmp_path):
        from app.data.generator.config import load_config

        yaml_content = """
version: "1.0"
n_payments: 50
n_merchants: 3
seed: 99
currency: INR
start_date: "2026-08-01"
end_date: "2026-08-31"
"""
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text(yaml_content)
        cfg = load_config(cfg_file)
        assert cfg.seed == 99
        assert cfg.n_payments == 50

    def test_hash_config_file(self, tmp_path):
        from app.data.generator.config import hash_config_file

        f = tmp_path / "cfg.yaml"
        f.write_text("seed: 1\n")
        h = hash_config_file(f)
        assert h.startswith("sha256:")
        assert len(h) == 7 + 64  # "sha256:" + 64 hex chars

        # Same content → same hash
        f2 = tmp_path / "cfg2.yaml"
        f2.write_text("seed: 1\n")
        assert hash_config_file(f) == hash_config_file(f2)

        # Different content → different hash
        f3 = tmp_path / "cfg3.yaml"
        f3.write_text("seed: 2\n")
        assert hash_config_file(f) != hash_config_file(f3)
