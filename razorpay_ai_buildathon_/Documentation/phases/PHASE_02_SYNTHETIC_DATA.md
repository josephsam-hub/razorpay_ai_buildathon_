# Phase 2 â€” Synthetic Data Generator

## Problem
reconciliation systems require realistic datasets to test complex business edge cases. Relying on live production financial records presents severe data security risks, whereas using naive random generators fails to capture the relationships between different source tables (Payments, Settlements, statement lines, ledgers).

## What We Built
- Built a multi-source transactional data generator (`ObservedWorld` factory).
- Implemented clean and corrupted relationship builders tracking payouts, gateway fees, timing clearances, and statement clearings.
- Generated explicit ground-truth mapping metadata separate from the input datasets.

## How It Works
- The generator simulates an order clearance lifecycle: Payment $\rightarrow$ Settlement Payout $\rightarrow$ Bank Statement entry $\rightarrow$ Accounting General Ledger entry.
- Corruption functions inject transaction anomalies (e.g. removing settlements, altering bank amounts, injecting duplicate narrations, or delaying clearance times).

## Failure / Challenge
- **Challenge:** Early generator configurations allowed corruption delay values that fell within acceptable business timings.
- **Diagnosis:** A 1-day timing delay corruption was generated, but since the matching rules allowed a 1-day clearing tolerance buffer, the engine correctly matched the payment (unsafe auto-match).
- **Resolution:** Hardened generator timing delays to shift dates strictly outside V003 business timing thresholds, ensuring they are mathematically unmatchable.

## Evidence
- Generator functions: [`world.py`](../../backend/app/data/generator/world.py) and [`corruption.py`](../../backend/app/data/generator/corruption.py).
- Dataset validation configurations: [`config_bench_100.yaml`](../../backend/data/synthetic/config_bench_100.yaml).
- Direct unit tests verifying generator invariants in `backend/tests/data/test_corruption.py`.

## What This Unlocked
Allowed our evaluation and benchmarking services to test the reconciler against known, measurable ground truth.

## Judge Takeaway
A high-quality evaluation pipeline is built on realistic synthetic models. Enforcing mathematical constraints at the generation layer prevents boundary leakage, ensuring that metrics measure real performance.
