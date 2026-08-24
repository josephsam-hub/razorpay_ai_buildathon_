"""
LedgerLens Phase 2 — Dataset Generator Script
===============================================
Thin wrapper around the generator CLI.

Usage (from repo root):
  python scripts/generate_dataset.py \\
      --config data/synthetic/config_v1.yaml \\
      --output data/synthetic/generated/v1_seed42

Or use the module directly:
  cd backend
  python -m app.data.generator \\
      --config ../data/synthetic/config_v1.yaml \\
      --output ../data/synthetic/generated/v1_seed42
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend/ to sys.path so app.* imports resolve
REPO_ROOT = Path(__file__).parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.data.generator.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
