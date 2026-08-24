"""
Tests — Benchmark configs: all 5 YAML configs load and generate without error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.data.generator.config import load_config
from app.data.generator.world import WorldBuilder
from app.data.generator.validator import DatasetIntegrityValidator

# Resolve config directory relative to repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_CONFIG_DIR = _REPO_ROOT / "data" / "synthetic"

_CONFIGS = [
    "config_v1.yaml",
    "config_bench_100.yaml",
    "config_bench_500.yaml",
    "config_bench_1000.yaml",
    "config_bench_10000.yaml",
]


@pytest.mark.parametrize("config_name", _CONFIGS)
def test_config_loads_without_error(config_name):
    """Every benchmark config must parse without error."""
    config_path = _CONFIG_DIR / config_name
    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")
    config = load_config(config_path)
    assert config.seed > 0
    assert config.n_payments >= 10


@pytest.mark.parametrize("config_name", ["config_v1.yaml", "config_bench_100.yaml"])
def test_config_generates_and_passes_validation(config_name):
    """Smaller configs must generate a clean world that passes validation."""
    config_path = _CONFIG_DIR / config_name
    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")

    config = load_config(config_path)
    builder = WorldBuilder(config)
    clean = builder.build_clean()

    validator = DatasetIntegrityValidator()
    result = validator.validate(
        merchants=clean.merchants,
        payments=clean.payments,
        settlements=clean.settlements,
        bank_entries=clean.bank_entries,
        ledger_entries=clean.ledger_entries,
    )
    assert result.passed, f"{config_name}: {result}"


@pytest.mark.parametrize("config_name", ["config_v1.yaml", "config_bench_100.yaml"])
def test_record_counts_match_config(config_name):
    """Generated payment count must match config.n_payments."""
    config_path = _CONFIG_DIR / config_name
    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")

    config = load_config(config_path)
    builder = WorldBuilder(config)
    clean = builder.build_clean()

    assert len(clean.payments) == config.n_payments
    assert len(clean.merchants) == config.n_merchants


@pytest.mark.parametrize("config_name", ["config_bench_500.yaml", "config_bench_1000.yaml"])
def test_large_config_generates_without_error(config_name):
    """Larger benchmark configs generate without raising exceptions."""
    config_path = _CONFIG_DIR / config_name
    if not config_path.exists():
        pytest.skip(f"Config file not found: {config_path}")

    config = load_config(config_path)
    # Only build clean world — no need to corrupt for benchmark validation
    builder = WorldBuilder(config)
    clean = builder.build_clean()
    assert len(clean.payments) == config.n_payments


@pytest.mark.skip(reason="10k generation takes ~5s; run manually with: pytest -k bench_10000 -s")
def test_bench_10000_generates():
    """10k benchmark: run manually to avoid slow CI."""
    config_path = _CONFIG_DIR / "config_bench_10000.yaml"
    if not config_path.exists():
        pytest.skip("Config not found")
    config = load_config(config_path)
    builder = WorldBuilder(config)
    clean = builder.build_clean()
    assert len(clean.payments) == 10000
