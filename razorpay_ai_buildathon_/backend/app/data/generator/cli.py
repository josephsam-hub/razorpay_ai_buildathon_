"""
LedgerLens Phase 2 — Dataset Generator CLI
============================================
Entry point: python -m app.data.generator --config <path> --output <dir>

Usage:
  python -m app.data.generator \\
      --config data/synthetic/config_v1.yaml \\
      --output data/synthetic/generated/v1_seed42

Or via scripts/generate_dataset.py wrapper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ledgerlens-generator",
        description="LedgerLens — Synthetic Financial Dataset Generator",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to YAML config file (e.g. data/synthetic/config_v1.yaml)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for generated dataset files",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        default=True,
        help="Run integrity validation on clean world before writing (default: True)",
    )
    parser.add_argument(
        "--no-validate",
        action="store_false",
        dest="validate",
        help="Skip clean world validation",
    )

    args = parser.parse_args(argv)

    config_path: Path = args.config
    output_dir: Path = args.output

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        return 1

    # Late imports to keep CLI startup fast
    from app.data.generator.config import hash_config_file, load_config
    from app.data.generator.validator import DatasetIntegrityValidator
    from app.data.generator.world import generate
    from app.data.generator.writer import write_dataset

    print(f"Loading config: {config_path}")
    config = load_config(config_path)
    config_hash = hash_config_file(config_path)

    print(
        f"Generating dataset: n_payments={config.n_payments}, "
        f"seed={config.seed}, version={config.version}"
    )
    clean, observed = generate(config)

    if args.validate:
        print("Running integrity validation on clean world...")
        validator = DatasetIntegrityValidator()
        result = validator.validate(
            merchants=clean.merchants,
            payments=clean.payments,
            settlements=clean.settlements,
            bank_entries=clean.bank_entries,
            ledger_entries=clean.ledger_entries,
        )
        print(result)
        if not result.passed:
            print("ERROR: Integrity validation failed. Aborting.", file=sys.stderr)
            return 2

    print(f"Writing dataset to: {output_dir}")
    metadata = write_dataset(output_dir, config, observed, config_hash)

    print("\n=== Dataset Summary ===")
    for entity, count in metadata.record_counts.items():
        print(f"  {entity:25s}: {count:>6d}")
    print(f"\n  Seed:              {metadata.seed}")
    print(f"  Generator version: {metadata.generator_version}")
    print(f"  Config hash:       {metadata.config_hash[:20]}...")
    print(f"\nCorruption profile:")
    for ctype, count in sorted(metadata.corruption_profile.items()):
        print(f"  {ctype:30s}: {count:>4d}")
    print(f"\nOutput: {output_dir.resolve()}")
    print("Done.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
