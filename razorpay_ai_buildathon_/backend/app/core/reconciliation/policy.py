"""
LedgerLens Phase 3 — Reconciliation Policy Constants
======================================================
Configurable policy values for the reconciliation engine.

POLICY vs SPECIFICATION:
  These constants encode business-policy decisions that are currently
  unspecified by the formal repository specification. Each constant is
  documented with:
    - its current value
    - the business rationale
    - the TBD calibration note

  Phase 3.2 will calibrate these values empirically against the synthetic
  benchmark (config_v1.yaml, config_bench_*.yaml). Until then they are
  intentionally conservative — preferring false negatives (HUMAN_REVIEW)
  over false positives (AUTO_MATCH on bad data).

DO NOT change these values without running the Phase 3.3 evaluation harness.

NOTE — R012 REMOVAL:
  These constants were originally used by exact.py rule R012.
  R012 was removed from exact matching per the approved Phase 3.1 architecture.
  Temporal validation now lives exclusively in validation.py (V001–V004).
  These constants are retained here for Phase 3.2 policy calibration —
  they will be referenced by the evaluation harness when determining
  acceptable settlement-date windows for the scoring model.
"""

# ---------------------------------------------------------------------------
# Settlement date window policy
# ---------------------------------------------------------------------------
# The maximum number of calendar days that settlement_date is permitted to
# lag AFTER this specific payment's payment_date.
#
# IMPORTANT DOMAIN NOTE (Phase 2 settlement semantics):
#   In Phase 2, settlement_date = latest_payment_date_in_batch + cycle_days.
#   For a payment that is NOT the latest in a multi-payment batch, its
#   individual settlement_date - payment_date can be:
#     (latest_payment_date - this_payment_date) + cycle_days
#   This can legitimately exceed cycle_days (1-3 days) by the batch spread.
#   Batches can span up to ~20 calendar days in the August 2026 test dataset.
#
# Conservative upper bound rationale:
#   max_batch_size = 5 payments, each randomly dated within a 31-day month.
#   Observed max delta in config_v1 (seed=42, 20 payments): 22 days.
#   Setting the window to 31 days (one full month) catches all legitimate
#   clean settlements while blocking clearly anomalous future-dated entries.
#   The definitive guard is V001 (settlement_date >= latest_payment_date).
#
# TBD — REQUIRES EMPIRICAL CALIBRATION in Phase 3.3 evaluation harness.
SETTLEMENT_DATE_MAX_DAYS_AFTER_PAYMENT: int = 31

# The maximum number of calendar days that settlement_date is permitted to
# appear BEFORE payment_date.
#
# In a clean world, settlement_date MUST be >= payment_date because a
# settlement cannot be processed before the payment is received.
# This invariant is enforced by V001 in validation.py.
#
# TBD — Phase 3.2 calibration.
SETTLEMENT_DATE_MIN_DAYS_BEFORE_PAYMENT: int = 0


# ---------------------------------------------------------------------------
# V003 — Bank entry timing window
# ---------------------------------------------------------------------------
# The maximum number of calendar days that bank.value_date may lag AFTER
# settlement.settlement_date.
#
# Clean-world generator invariant (from bank.py):
#   value_date = settlement_date + 0 or 1 days (seeded)
# Therefore the maximum legitimate delta is 1.
#
# TBD — expand if weekend/holiday offsets are introduced in real-world data.
V003_MAX_DAYS_AFTER_SETTLEMENT: int = 1

# ---------------------------------------------------------------------------
# V004 — Ledger posting timing window
# ---------------------------------------------------------------------------
# The maximum number of calendar days that ledger.posting_date may lag AFTER
# bank.value_date.
#
# Clean-world generator invariant (from ledger.py):
#   posting_date = value_date + 0, 1, or 2 days (seeded)
# Therefore the maximum legitimate delta is 2.
#
# TBD — expand if ERP processing delays are introduced.
V004_MAX_DAYS_AFTER_VALUE: int = 2

# ---------------------------------------------------------------------------
# CS004 — Composite date window
# ---------------------------------------------------------------------------
# The maximum calendar-day distance between settlement_date and payment_date
# that still scores > 0.0 in the CS004 composite signal.
#
# Rationale: maximum settlement cycle (3 days) + maximum E005 date-mismatch
# shift (5 days) = 8 days as a conservative outer bound.
#
# TBD — REQUIRES SPECIFICATION: exact tolerance and scoring function.
CS004_MAX_DATE_DISTANCE_DAYS: int = 8
