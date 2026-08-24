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
