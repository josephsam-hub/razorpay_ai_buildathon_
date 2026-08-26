# Phase 3 â€” Reconciliation Engine

## Problem
In financial applications, matching transactions across multiple files is difficult due to narration variance, time offsets, and gateway fee deductions. Naive AI-based matching introduces unacceptable risks of financial error and lack of audit trails, violating compliance standards.

## What We Built
- Built a high-performance deterministic reconciliation engine ([`engine.py`](file:///d:/razorpay_buildathin/razorpay_ai_buildathon_/backend/app/core/reconciliation/engine.py)).
- Implemented core validation rules `V001`â€“`V004` and composite signal scores `CS001`â€“`CS004`.
- Integrated strict `Decimal` precision matching to eliminate floating-point representation errors.
- Created `EvidenceCard` models to record matching decisions and logical rule traces.

## How It Works
- **Normalisation:** Ingested transaction items are parsed into canonical objects.
- **Rule Verification:**
  - `V001` (Currency matching): Verifies payments and bank statements share exact currencies.
  - `V002` (Gross value checks): Computes payment amount against statement deposits.
  - `V003` (Clearing timing window): Enforces temporal clearances.
  - `V004` (Narration mapping): Compares payment identifiers against statement description tokens.
- **Composite Scoring:**
  - `CS001`: Evaluates gross balances.
  - `CS002`: Calculates Levenshtein similarities for reference IDs.
  - `CS003`: Verifies gateway fee math.
  - `CS004`: Computes date decays over clearing delays.
- **Evidence Card Packaging:** Decisions are categorized into `AUTO_MATCH`, `HUMAN_REVIEW`, or `ABSTAIN` alongside matched feature scores and rules triggered.

## Why Deterministic Reconciliation is Authoritative
Deterministic matching is strictly rule-based and mathematically verifiable. It guarantees that matching decisions can be audited and replayed under any condition. An LLM is never permitted to make financial decisions; it has no write permissions on the match ledger.

## Failure / Challenge
- **Challenge:** Differences in floating-point representations during fee mappings caused clean transactions to fail validation checks.
- **Diagnosis:** Comparing amounts as standard float numbers introduced minor precision skew.
- **Resolution:** Re-implemented all currency matching using Python's standard `Decimal` class, quantising all amounts to exactly two decimal places.

## Evidence
- Core reconciler code: [`engine.py`](../../backend/app/core/reconciliation/engine.py) and [`validation.py`](../../backend/app/core/reconciliation/validation.py).
- Output model definitions: [`decisions.py`](../../backend/app/models/decisions.py).
- Direct unit tests verifying deterministic mappings in `backend/tests/reconciliation/test_validation.py`.

## What This Unlocked
Provided a high-speed, secure matching foundation that executes in milliseconds, leaving AI free to analyze the exceptions.

## Judge Takeaway
Financial systems require absolute correctness and audit trails. LedgerLens achieves this by enforcing a strict boundary: deterministic rules make the matching decisions, while AI is relegated to a read-only explanatory role.
