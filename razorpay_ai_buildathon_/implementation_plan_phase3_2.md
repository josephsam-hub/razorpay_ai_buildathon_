# LedgerLens — Phase 3.2: Evaluation + Calibration
## Implementation Plan — Revision 2

**Status:** DESIGN ONLY — DO NOT IMPLEMENT  
**Author:** Architecture review based on committed codebase `48b9223`  
**Revision:** Tech Lead revisions 1–8 incorporated  
**Date:** 2026-08-24  
**Prerequisite commit:** `48b9223 feat: add deterministic reconciliation engine`

---

## 1. Current Architecture Assessment

### What exists after Phase 3.1

```
ObservedWorld
  .merchants                          (observed — engine reads)
  .payments                           (observed — anchor)
  .settlements                        (observed — may be corrupted)
  .bank_entries                       (observed — may be corrupted, or orphan added)
  .ledger_entries                     (observed — may be corrupted)
  .ground_truth       ← EVALUATOR ONLY (list[GroundTruth])
  .corruption_events  ← EVALUATOR ONLY (list[CorruptionEvent])
         │
         ▼
ReconciliationService.reconcile()
         │
         ▼
BatchReconciliationResult
  .decisions          list[ReconciliationDecision]   (one per payment)
  .evidence_cards     list[EvidenceCard]
  .orphan_records     list[OrphanRecord]             (entity-level, no payment_id)
  .match_rate         Decimal                        (decision distribution only)
  .exception_rate     Decimal
         │
         ▼
  [nothing] ← no evaluator exists yet
```

### The core gap

`BatchReconciliationResult.match_rate = auto_matched / total_payments` measures what the engine *decided*, not whether those decisions were *correct*. An engine that AUTO_MATCHes every payment — including corrupted ones — would produce `match_rate = 1.00`. This is the exact failure mode Track 04 evaluators will penalise.

Furthermore, the current result focuses entirely on payment-level decisions. It says nothing about:
- Whether orphan bank entries were detected and surfaced
- Whether a batch containing a silent orphan should be considered fully reconciled
- Whether the correct exception code was produced for each discrepancy

Phase 3.2 must produce two independent scorecards and a batch-integrity report.

---

## 2. Phase 3.2 Architecture

```
seed_N config
     │
     ▼
generate(config)
     │
     ├── CleanWorld            (used only during generation, not stored)
     └── ObservedWorld
              │   ┌── .ground_truth        ─────────────────────────────┐
              │   └── .corruption_events   ─────────────────────────────┤
              │                                                          │
              ▼                                                          │
ReconciliationService.reconcile()         ← engine NEVER sees gt/events  │
              │                                                          │
              ▼                                                          │
BatchReconciliationResult                                                │
  .decisions (payment-level)                                             │
  .orphan_records (entity-level, no payment_id)                         │
              │                                                          │
              └──────────────────────────────────────────────────► ─────┘
                                                                         │
                        Evaluator.evaluate(                              │
                            result,          ← engine output             │
                            ground_truth,    ← evaluator input           │
                            corruption_events ← evaluator input          │
                        )                                                │
                                │
                                ▼
                        EvaluationResult  (per seed)
                                │
                                ▼
                        MultiSeedAggregator
                                │
                                ▼
                        AggregateEvaluationReport → JSON
```

**Hard boundary:** The `Evaluator` receives `BatchReconciliationResult` (engine output) and separately receives ground truth and corruption events (evaluator input). The engine never imports from the evaluator. This is enforced architecturally and verified by a test.

---

## 3. Entity-Aware Evaluation (Revision 1)

### Why payment_id alone is insufficient

Payment-level evaluation is necessary but not sufficient. Consider the E008 case (Section 3.2 below): the affected payment may be correctly reconciled while an orphan bank entity exists with no payment_id. If the evaluator only operates on payment_id, the orphan is invisible.

Every evaluation record must carry an entity-level identity, not just a payment-level one.

### Evaluation entity record

Every finding the evaluator produces is tagged with:

| Field | Type | Notes |
|-------|------|-------|
| `entity_type` | `Literal["payment", "settlement", "bank_entry", "ledger_entry", "batch"]` | What kind of entity this finding describes |
| `record_id` | `str` | Primary key of the entity (payment_id, settlement_id, bank_entry_id, etc.) |
| `payment_id` | `str \| None` | Payment that anchors this entity, null for orphan bank entries and orphan settlements |
| `related_record_ids` | `list[str]` | IDs of directly related entities that provide context |
| `finding_type` | str | see taxonomy below |
| `expected_outcome` | str | from ground truth |
| `observed_outcome` | str | from engine |

This structure allows the evaluator to score:
- A payment decision (`entity_type = "payment"`, `record_id = payment_id`)
- An orphan bank entry detection (`entity_type = "bank_entry"`, `record_id = bank_entry_id`, `payment_id = None`)
- A batch integrity check (`entity_type = "batch"`, `record_id = batch_id`)

---

## 4. E008 Orphan Bank Entry — Explicit Modelling (Revision 2)

### The E008 scenario

```
Clean world:
  PAY_001 ──► SET_001 ──► BNK_001 ──► LED_001
                     (one legitimate bank credit for the settlement)

E008 corruption applied to PAY_001's batch:
  PAY_001 ──► SET_001 ──► BNK_001 ──► LED_001   (unchanged — still present)
                         BNK_999                  (orphan injected — REF_ORPHAN_CE_...)
```

**PAY_001's reconciliation is unaffected.** The normaliser resolves `PAY_001 → SET_001 → BNK_001` (smallest bank_entry_id wins). PAY_001 may produce `AUTO_MATCH` with confidence 1.00 — correctly.

`BNK_999` has `settlement_ref = REF_ORPHAN_CE_...` which is not found in any settlement. The normaliser routes it to `NormaliserResult.orphan_bank_entries`. The engine converts it to `OrphanRecord` with `rec:E008`.

**Therefore:**
- `PAY_001 → AUTO_MATCH` is **correct** (payment reconciliation passes)
- `BNK_999 → unresolved orphan` is **also correct** (exception detection passes)

The evaluator must score **both** independently:
1. Payment-level: PAY_001 correctly AUTO_MATCHed → TP_MATCH ✓
2. Entity-level: BNK_999 correctly surfaced as orphan exception → correct exception detection ✓

A batch where every payment AUTO_MATCHes but `orphan_records` is non-empty is **NOT fully reconciled**. The batch-integrity scorecard must report this.

---

## 5. E-Code Semantic Mapping (Revision 3)

The mapping is based on examining what each corruption does to the observed records and which engine rules/validations detect it.

### Explicit semantic mapping table

| Gen code | Gen type | Affected entity | What is observed | How engine detects | Engine decision | Rec: codes | Multiple findings? |
|----------|----------|-----------------|------------------|--------------------|-----------------|------------|-------------------|
| **E001** | `missing_settlement` | Settlement | Row removed from settlements | R001 fails (settlement absent) | ABSTAIN (`is_no_candidate=True`) | `rec:E001` | No |
| **E002** | `missing_bank_entry` | BankEntry | Row removed from bank_entries | R002 fails (bank absent) | HUMAN_REVIEW (settlement present, bank missing) | `rec:E001` | No |
| **E003** | `missing_ledger_entry` | LedgerEntry | Row removed from ledger_entries | R003 fails (ledger absent) | HUMAN_REVIEW | `rec:E001` | No |
| **E004** | `amount_mismatch` | BankEntry | `credit_amount` shifted ±2–10% | R010 fails (credit ≠ net) | HUMAN_REVIEW | `rec:E002` | No |
| **E005** | `date_mismatch` | BankEntry | `value_date` shifted ±1–5 days | V003 fails (value_date outside 0–1 day window) | HUMAN_REVIEW (structural match + temporal anomaly) | `rec:E004` | Possible: V002 may also fire if shift crosses the settlement cycle boundary |
| **E006** | `duplicate_bank_entry` | BankEntry | Duplicate BNK row added | Normaliser: detected as duplicate. R013 fires → structural match blocked | HUMAN_REVIEW | `rec:E003` | No (R013 blocks before composite) |
| **E007** | `settlement_fee_variance` | Settlement + BankEntry (CRIT-2: bank credit updated to match new net) | Both settlement.net and bank.credit changed proportionally | R010 passes (credit = new net). V002 fails (settlement_date ≠ expected from clean cycle, OR — see note below). **Primary detection: clean_settlement_net_amount ≠ observed net** | HUMAN_REVIEW via V002 WARNING (cycle deviated) or no detection | `rec:E004` (V002) or **MISSED** — see note | Yes: may produce V002 finding only |
| **E008** | `orphan_bank_entry` | BankEntry (new row) | New BNK with `REF_ORPHAN_*` ref | Normaliser: `settlement_ref` not in known settlements → `orphan_bank_entries`. Engine creates `OrphanRecord` | Payment itself: unaffected. OrphanRecord: `rec:E008` | `rec:E008` | No: payment may be AUTO_MATCH, orphan is separate |

### Critical note on E007

E007 is the most subtle corruption. CRIT-2 keeps settlement net and bank credit in sync — so R010 (`bank_credit == settlement_net`) **passes**. The only detectors are:
- V002: `settlement_date == latest_payment_date + cycle_days` — this may or may not detect the fee variance depending on whether the corruption changed the settlement date (it does not; only fee/net is changed). V002 checks the **date cycle**, not the **financial amount**. **V002 DOES NOT detect E007.**
- There is currently no rule that compares observed `settlement.net_amount` against an expected net computed from payment amounts. This is a **detection gap**.

**E007 with the current Phase 3.1 engine:** The reconciliation will likely produce `AUTO_MATCH` for many E007 cases because:
1. All structural links are present (R001–R006 pass)
2. Bank credit equals the corrupted settlement net (R010 passes, because CRIT-2 kept them in sync)
3. V002 checks date cycle, not fee variance
4. No rule compares `bank_credit + fee` against `payment_amount`

This means **E007 may currently be a miss** — the engine AUTO_MATCHes it. The evaluator will measure this. The Phase 3.3 calibration can use this finding to design a new rule (R014: `bank_credit + settlement_fee == payment_amount` for single-payment settlements). **This is a known gap, not a defect to fix now — it is information the evaluator must surface.**

The semantic mapping for E007 is therefore:
- **Expected detection:** HUMAN_REVIEW  
- **Actual detection (Phase 3.1):** Likely AUTO_MATCH (false auto-match)  
- **Evaluation result:** `FP_MATCH` — the evaluator will catch this and report it

### Multiple-finding note

E005 may produce two validation findings (V002 + V003) if the date shift is large enough to also affect the settlement cycle check. The evaluator must handle multiple `rec:` codes per payment — `exception_codes` is already `list[str]` in `ReconciliationDecision`.

---

## 6. Two Independent Scorecards (Revision 4)

### Scorecard A — Reconciliation Scorecard (payment-level)

Measures whether the engine made correct payment-level decisions.

| Metric | Definition | Formula | Edge case |
|--------|-----------|---------|-----------|
| `total_payments` | All payments in batch | `N` | — |
| `auto_matched_count` | Engine decided AUTO_MATCH | `N_am` | — |
| `human_review_count` | Engine decided HUMAN_REVIEW | `N_hr` | — |
| `abstained_count` | Engine decided ABSTAIN | `N_ab` | — |
| `resolution_rate` | Payments with any decision | `N / N` = 1.00 always in Phase 3.1 | Always 1.00 until Phase 4 adds partial batches |
| `correct_match_count` | TP: ground_truth=AUTO_MATCH AND engine=AUTO_MATCH | `TP` | — |
| `incorrect_match_count` | FP: ground_truth=HUMAN_REVIEW AND engine=AUTO_MATCH | `FP` | — |
| `missed_match_count` | FN: ground_truth=AUTO_MATCH AND engine≠AUTO_MATCH | `FN_clean` | engine was too conservative |
| `correct_exception_count` | TN: ground_truth=HUMAN_REVIEW AND engine≠AUTO_MATCH | `TN` | — |
| `auto_match_precision` | Correct AUTO_MATCHes out of all AUTO_MATCHes | `TP / (TP + FP)` | `null` if `TP+FP == 0` |
| `auto_match_recall` | Correct AUTO_MATCHes out of all clean payments | `TP / N_clean` | `null` if `N_clean == 0` |
| `reconciliation_f1` | Harmonic mean of precision and recall | `2·P·R / (P+R)` | `null` if either null |

### Scorecard B — Exception Controller Scorecard (entity-level)

Measures whether the engine correctly detected and classified exceptions. Operates on both payment-level exceptions and entity-level orphan records.

| Metric | Definition | Formula | Edge case |
|--------|-----------|---------|-----------|
| `total_injected_exceptions` | Ground-truth records with expected_decision = HUMAN_REVIEW + orphan entities | `N_corrupt + N_orphan_injected` | — |
| `correctly_detected_exceptions` | Engine flagged HUMAN_REVIEW or ABSTAIN (not AUTO_MATCH) for corrupted payments, AND correctly surfaced orphan entities | count | — |
| `missed_exceptions` | Corrupted payments that got AUTO_MATCH + injected orphans not surfaced | count | — |
| `incorrectly_classified_exceptions` | Detected but wrong rec: code (no intersection with expected codes) | count | — |
| `false_exception_detections` | Engine flagged exception on a clean payment (HUMAN_REVIEW or ABSTAIN on AUTO_MATCH ground truth) | count | — |
| `exception_detection_precision` | Correct detections / all detections | `TN / (TN + FP_excep)` | `null` if denominator 0 |
| `exception_detection_recall` | Correct detections / all true exceptions | `TN / N_corrupt_total` | `null` if `N_corrupt_total == 0` |
| `exception_detection_f1` | | `2·P·R/(P+R)` | `null` |
| `per_corruption_type_metrics` | Per E001–E008: detected, missed, misclassified | See §7 | — |
| `per_entity_type_metrics` | Per payment/settlement/bank/ledger: exception counts | See §7 | — |

### How the two scorecards differ

Scorecard A answers: **"Did the engine make the right payment decisions?"**  
Scorecard B answers: **"Did the engine catch all the problems, with the right codes, at the right entities?"**

They are separate because:
- A payment can be correctly AUTO_MATCHed while an orphan bank entity is missed (Scorecard A passes, Scorecard B fails for that entity)
- A payment can be correctly flagged HUMAN_REVIEW (Scorecard A passes) but with the wrong `rec:` code (Scorecard B marks it as misclassified)
- High Scorecard A score with low Scorecard B score signals the engine catches obvious problems but misidentifies subtle ones

---

## 7. Unsafe Auto-Match Metric (Revision 5)

This is a critical finance-safety metric. An auto-match on a corrupted record is a direct financial risk — the system cleared a transaction that should have been reviewed.

### Definitions

| Metric | Formula | Unit | Notes |
|--------|---------|------|-------|
| `unsafe_auto_match_count` | Count of payments where `ground_truth=HUMAN_REVIEW` AND `engine=AUTO_MATCH` | int | = `FP` from Scorecard A |
| `unsafe_auto_match_rate` | `unsafe_auto_match_count / all_auto_match_count` | fraction | `null` if `all_auto_match_count == 0` |

**Interpretation:**  
- `unsafe_auto_match_rate = 0.00` — the engine never cleared a corrupted record. Ideal.
- `unsafe_auto_match_rate = 0.01` — 1 in 100 auto-matches was wrong. Potentially acceptable depending on corruption type severity.
- Any nonzero rate involving E007 (fee variance) is particularly concerning — fee errors are financial misstatements.

**No target percentage is set here.** The evaluation measures it honestly. TBD-3.2-01 asks Tech Lead to set the acceptable threshold after reviewing measured values across calibration seeds.

### Per-corruption unsafe auto-match

The evaluator must also report `unsafe_auto_match_count` broken down by `discrepancy_type`:

```json
"unsafe_auto_match_by_corruption": {
  "missing_settlement":   0,
  "amount_mismatch":      0,
  "settlement_fee_variance": 3,   ← expected: E007 likely missed in Phase 3.1
  "date_mismatch":        0
}
```

This directs future rule work to the specific corruption types that are leaking through.

---

## 8. Batch Integrity Evaluation (Revision 7)

### The batch integrity problem

A batch is a settlement batch: one settlement covering 1–5 payments, one bank entry, and multiple ledger entries. A batch-level integrity check answers: "Is this entire batch clean, or does something within it remain unresolved?"

**Scenarios that pass payment-level evaluation but fail batch integrity:**

| Scenario | Payment decision | Batch integrity |
|----------|-----------------|-----------------|
| All payments AUTO_MATCH; orphan bank entry exists | PASS | FAIL — unresolved entity |
| 4 of 5 payments AUTO_MATCH; 1 is HUMAN_REVIEW | PARTIAL | FAIL — incomplete batch |
| All payments AUTO_MATCH; ledger total ≠ settlement net (multi-payment rounding) | PASS | WARNING — financial inconsistency |
| Settlement is missing; all payments ABSTAIN | FAIL | FAIL — no settlement anchor |
| Duplicate bank entry detected; payment is HUMAN_REVIEW | FAIL | FAIL |

### Batch integrity findings taxonomy

| Finding code | Description |
|-------------|-------------|
| `BATCH_CLEAN` | All payments in batch are AUTO_MATCH; no orphan/duplicate entities; no validation anomalies |
| `BATCH_PARTIAL` | Some payments resolved, some not (multi-payment settlement) |
| `BATCH_ORPHAN_ENTITY` | One or more orphan entities detected within the batch's settlement_ref scope |
| `BATCH_DUPLICATE_ENTITY` | Duplicate bank entry detected for this batch |
| `BATCH_MISSING_SETTLEMENT` | Settlement absent — no anchor for the batch |
| `BATCH_TEMPORAL_ANOMALY` | All payments matched but one or more temporal validation findings (V001–V004) failed |

**Key claim prevention:** The batch-integrity scorecard must ensure the final report does NOT claim "100% reconciliation" if any batch has a non-`BATCH_CLEAN` finding.

---

## 9. Per-Corruption-Type and Per-Entity-Type Metrics

### Per-corruption-type section

For each generator type `t ∈ {missing_settlement, missing_bank_entry, missing_ledger_entry, amount_mismatch, date_mismatch, duplicate_bank_entry, settlement_fee_variance, orphan_bank_entry}`:

```json
{
  "corruption_type": "amount_mismatch",
  "gen_code": "E004",
  "expected_rec_codes": ["rec:E002"],
  "injected_count": 5,
  "correctly_detected_count": 5,
  "missed_count": 0,
  "auto_matched_incorrectly_count": 0,
  "correct_code_classification_count": 5,
  "wrong_code_classification_count": 0,
  "detection_rate": "1.00",
  "unsafe_auto_match_count": 0,
  "notes": ""
}
```

### Per-entity-type section

For each entity type `e ∈ {payment, settlement, bank_entry, ledger_entry}`:

```json
{
  "entity_type": "bank_entry",
  "total_observed": 36,
  "corrupted": 9,
  "correctly_handled": 8,
  "incorrectly_handled": 1,
  "orphan_detected": 2,
  "orphan_missed": 0
}
```

---

## 10. Evaluation Taxonomy — Complete

### Payment-level outcomes

| Code | Condition | Counts toward |
|------|-----------|---------------|
| `TP_MATCH` | gt=AUTO_MATCH AND engine=AUTO_MATCH | Scorecard A precision + recall |
| `FP_MATCH` | gt=HUMAN_REVIEW AND engine=AUTO_MATCH | **unsafe_auto_match**, Scorecard A precision |
| `TN_EXCEPTION` | gt=HUMAN_REVIEW AND engine=HUMAN_REVIEW | Scorecard B recall |
| `ABST_CORRUPT` | gt=HUMAN_REVIEW AND engine=ABSTAIN | Scorecard B recall (conservative TN) |
| `FN_MISS_CLEAN` | gt=AUTO_MATCH AND engine=HUMAN_REVIEW or ABSTAIN | Scorecard A recall, false_exception_detections |
| `ABST_CLEAN` | gt=AUTO_MATCH AND engine=ABSTAIN | Scorecard A recall |

### Exception classification sub-outcomes (apply to TN_EXCEPTION and ABST_CORRUPT)

| Code | Condition |
|------|-----------|
| `CORRECT_CODE` | `engine.exception_codes` ∩ `expected_rec_codes_via_bridge` is non-empty |
| `WRONG_CODE` | engine detected exception but codes do not intersect expected |
| `NO_CODE` | engine correctly routed to HUMAN_REVIEW but `exception_codes` is empty |

### Entity-level outcomes (orphan records)

| Code | Condition |
|------|-----------|
| `ORPHAN_DETECTED` | Injected orphan entity appears in `BatchReconciliationResult.orphan_records` |
| `ORPHAN_MISSED` | Injected orphan entity not surfaced (should not happen with current normaliser, but must be checked) |
| `FALSE_ORPHAN` | Engine surfaced an orphan that was not injected (possible if a legitimate settlement was missed) |

---

## 11. Holdout Strategy (Revision 6)

### Three-way partition

```
Calibration:  seeds 42–46   (5 datasets) — tune signal weights, threshold selection
Evaluation:   seeds 100–104 (5 datasets) — measure true performance on unseen data
Holdout:      seed 999      (1 dataset)  — final demo/submission report ONLY
```

### Holdout isolation invariants

The holdout seed must **never** influence:
- threshold selection
- feature selection (which composite signals to include)
- rule changes (new R-rules or V-rules)
- implementation decisions
- calibration

The holdout is run exactly once: after all policy decisions are frozen. If the holdout result is inspected before policy is frozen, the holdout seed must be discarded and replaced with a new one (e.g. 1999). This must be documented in the evaluation run log.

### Freeze conditions

Policy is considered frozen when:
- All R-rules and V-rules are committed and passing
- Any composite AUTO_MATCH threshold is documented as an explicit constant in `policy.py`
- The evaluation seeds 100–104 have been run and their aggregate results recorded

Only after all three conditions are met may the holdout seed be used.

---

## 12. Multi-Seed Strategy

### Seed independence verification

Two datasets are considered independent if:
1. Their `corruption_profile` dictionaries differ (different permutation of corruption types across payments)
2. Their `payments.csv` first and last rows differ (different random amounts and dates)

The `MultiSeedAggregator` will assert these differences before including a dataset in aggregation.

### Aggregation statistics

For each metric `m` across `K` seeds:

```
mean(m)   = sum(m_i) / K
median(m) = middle value of sorted [m_i]
std(m)    = sqrt(sum((m_i - mean)^2) / K)
min(m)    = min(m_i)
max(m)    = max(m_i)
```

For K ≥ 8: report 95% confidence interval `mean ± t(0.975, df=K-1) * std/sqrt(K)`.  
For K < 8: report CI as `null`.

Metrics that return `null` (zero denominator) in any seed are excluded from the mean/std calculation for that seed; the aggregate notes how many seeds had `insufficient_data`.

---

## 13. Calibration Strategy

### What needs calibration

From Phase 3.1:
- Composite AUTO_MATCH threshold — currently unused (composite never AUTO_MATCHes)
- Composite signal weights (CS001–CS005) — currently equal weight
- Amount tolerance for CS003 near-match
- V003 and V004 day-window tolerances (currently hard-coded as Phase 2 clean-world invariants; may need relaxation)

From Phase 3.2 evaluation findings (anticipated):
- R014 (or equivalent) for E007 detection — fee variance not currently caught

### Calibration process

```
Step 1 — Score distribution analysis (calibration seeds 42–46 only)
  For every payment:
    record: composite_score, ground_truth.expected_decision, ground_truth.discrepancy_type
  Plot: score histograms for {clean, corrupted} classes
  Compute: KL divergence or overlap coefficient between distributions

Step 2 — Unsafe auto-match analysis
  Identify which corruption types produce FP_MATCH in Phase 3.1
  Specifically: does E007 produce FP_MATCH? (expected: yes)

Step 3 — Threshold sweep (only if Step 2 shows useful signal)
  For t ∈ {0.50, 0.55, ..., 0.95}:
    compute: precision(t), recall(t), unsafe_auto_match_rate(t)

Step 4 — Threshold selection criteria
  TBD-3.2-01: maximum acceptable unsafe_auto_match_rate must be set before a threshold is chosen
  Suggested primary criterion: unsafe_auto_match_rate(t) == 0.00 (zero tolerance)
  Secondary: maximise recall(t) subject to primary criterion

Step 5 — Cross-validate on evaluation seeds 100–104
  Apply selected threshold, measure degradation
  If unsafe_auto_match_rate > 0 on evaluation seeds: reject threshold

Step 6 — Freeze policy in policy.py

Step 7 — Run holdout seed 999 once
```

---

## 14. Throughput Benchmark Methodology

### Target sizes

All four benchmark configs already exist in `data/synthetic/config_bench_*.yaml`.

| Config | N | Purpose |
|--------|---|---------|
| `config_bench_100.yaml` | 100 | Baseline |
| `config_bench_500.yaml` | 500 | Linear scaling check |
| `config_bench_1000.yaml` | 1,000 | Full reconciliation |
| `config_bench_10000.yaml` | 10,000 | Scale ceiling |

### Measurement protocol

```
Environment record:
  - Platform: Windows 11 / Python 3.12.14
  - RAM: approx.
  - No database, no network (in-memory only)
  - Cold: first call after fresh Python process

For each dataset size N (3 runs each):
  1. run generate(config)   — time separately (not included in reconciliation time)
  2. run reconcile(world)   — MEASURE THIS
  3. record wall_clock_seconds, records_per_second, avg_latency_ms
  
Report: mean ± std across 3 runs
```

### P95 latency

P95 requires per-record instrumentation. This is collected only in benchmark mode via a flag passed to the benchmark harness — never in the production `ReconciliationService`. The benchmark harness wraps the per-payment loop with `time.perf_counter()` calls. The 95th percentile is computed over the per-record times.

---

## 15. Output Schema (Revision 8)

The complete machine-readable output. All fractional metrics are `string` representations of `Decimal` or `null`. Never `0.0` or `NaN` on zero denominators.

```json
{
  "run_metadata": {
    "run_id": "EVAL_20260824_001",
    "evaluation_version": "0.1.0",
    "engine_commit": "48b9223",
    "python_version": "3.12.14",
    "platform": "win32",
    "timestamp_utc": "2026-08-24T12:00:00Z",
    "partition": "calibration",
    "seed_list": [42, 43, 44, 45, 46]
  },

  "per_seed_results": [
    {
      "seed": 42,
      "dataset_metadata": {
        "dataset_version": "1.0",
        "config_hash": "sha256:...",
        "record_counts": {
          "merchants": 5,
          "payments": 100,
          "settlements": 30,
          "bank_entries": 36,
          "ledger_entries": 96,
          "ground_truth": 100,
          "corruption_events": 30
        },
        "corruption_profile": {
          "missing_settlement": 5,
          "missing_bank_entry": 4,
          "missing_ledger_entry": 4,
          "amount_mismatch": 5,
          "date_mismatch": 4,
          "duplicate_bank_entry": 3,
          "settlement_fee_variance": 3,
          "orphan_bank_entry": 2,
          "clean": 70
        }
      },

      "entity_counts": {
        "total_payments": 100,
        "clean_payments": 70,
        "corrupted_payments": 30,
        "total_orphan_entities_injected": 2,
        "total_duplicate_entities_injected": 3
      },

      "decision_distribution": {
        "auto_matched": 72,
        "human_review": 25,
        "abstained": 3
      },

      "reconciliation_scorecard": {
        "correct_match_count": 70,
        "incorrect_match_count": 2,
        "missed_match_count": 0,
        "correct_exception_count": 28,
        "false_exception_count": 0,
        "abstained_clean_count": 0,
        "abstained_corrupt_count": 2,
        "auto_match_precision": "0.97",
        "auto_match_recall": "1.00",
        "reconciliation_f1": "0.98",
        "resolution_rate": "1.00"
      },

      "exception_scorecard": {
        "total_injected_exceptions": 32,
        "correctly_detected_exceptions": 30,
        "missed_exceptions": 2,
        "incorrectly_classified_exceptions": 1,
        "false_exception_detections": 0,
        "exception_detection_precision": "1.00",
        "exception_detection_recall": "0.94",
        "exception_detection_f1": "0.97"
      },

      "unsafe_auto_match_metrics": {
        "unsafe_auto_match_count": 2,
        "unsafe_auto_match_rate": "0.03",
        "insufficient_data": false,
        "unsafe_auto_match_by_corruption": {
          "settlement_fee_variance": 2,
          "amount_mismatch": 0,
          "missing_settlement": 0
        }
      },

      "per_corruption_metrics": [
        {
          "corruption_type": "settlement_fee_variance",
          "gen_code": "E007",
          "expected_rec_codes": ["rec:E002"],
          "injected_count": 3,
          "correctly_detected_count": 1,
          "missed_count": 0,
          "auto_matched_incorrectly_count": 2,
          "correct_code_classification_count": 1,
          "wrong_code_classification_count": 0,
          "detection_rate": "0.33",
          "unsafe_auto_match_count": 2,
          "insufficient_data": false,
          "notes": "E007 partial miss expected: Phase 3.1 has no fee-vs-payment rule"
        }
      ],

      "per_entity_metrics": [
        {
          "entity_type": "bank_entry",
          "total_observed": 36,
          "corrupted_count": 9,
          "correctly_handled_count": 8,
          "incorrectly_handled_count": 1,
          "orphan_injected_count": 2,
          "orphan_detected_count": 2,
          "orphan_missed_count": 0,
          "insufficient_data": false
        }
      ],

      "batch_integrity": {
        "total_batches": 30,
        "clean_batches": 25,
        "partial_batches": 2,
        "orphan_entity_batches": 2,
        "duplicate_entity_batches": 3,
        "missing_settlement_batches": 5,
        "temporal_anomaly_batches": 4,
        "fully_reconciled_rate": "0.83",
        "insufficient_data": false,
        "note": "fully_reconciled_rate != auto_match_rate — orphan entities prevent full clean status"
      },

      "throughput_metrics": {
        "total_records": 100,
        "wall_clock_seconds": "0.012",
        "records_per_second": "8333",
        "avg_latency_ms": "0.12",
        "p95_latency_ms": null,
        "benchmark_mode": false,
        "platform": "win32",
        "python_version": "3.12.14"
      },

      "unresolved_entities": [
        {
          "entity_type": "payment",
          "record_id": "PAY_20260801_00003",
          "payment_id": "PAY_20260801_00003",
          "related_record_ids": ["SET_20260802_0002"],
          "engine_decision": "HUMAN_REVIEW",
          "engine_confidence": "0.98",
          "engine_exception_codes": ["rec:E002"],
          "stage_reached": "composite",
          "notes": "Exact match failed; composite score=0.98"
        },
        {
          "entity_type": "bank_entry",
          "record_id": "BNK_ORP_CE_20260801_0001_07",
          "payment_id": null,
          "related_record_ids": [],
          "engine_decision": "ORPHAN",
          "engine_confidence": null,
          "engine_exception_codes": ["rec:E008"],
          "stage_reached": "normaliser",
          "notes": "Orphan bank entry: settlement_ref 'REF_ORPHAN_CE_...' not found in any settlement"
        }
      ],

      "exception_list": [
        {
          "entity_type": "payment",
          "record_id": "PAY_20260801_00003",
          "payment_id": "PAY_20260801_00003",
          "decision": "HUMAN_REVIEW",
          "exception_codes": ["rec:E002"],
          "exception_type": "amount_mismatch",
          "reason": "Exact match failed; composite score=0.98",
          "evidence_summary": "BankEntry.credit_amount=4802.00 != Settlement.net_amount=4900.00 (delta=-98.00)",
          "structural_confidence": "0.98",
          "affected_records": ["BNK_20260802_0001", "SET_20260802_0002"]
        }
      ],

      "composite_score_distribution": {
        "note": "Populated only during calibration runs for Phase 3.3 threshold analysis",
        "clean_payment_scores": [],
        "corrupt_payment_scores": []
      }
    }
  ],

  "aggregate_statistics": {
    "seed_count": 5,
    "seeds_with_insufficient_data": {},
    "reconciliation_scorecard": {
      "auto_match_precision": {
        "mean": "0.97", "median": "0.97", "std": "0.01",
        "min": "0.95", "max": "0.99",
        "confidence_interval_95": null,
        "seeds_with_insufficient_data": 0
      },
      "reconciliation_f1": { "..." : "..." },
      "unsafe_auto_match_rate": { "..." : "..." }
    },
    "exception_scorecard": { "..." : "..." },
    "batch_integrity": {
      "fully_reconciled_rate": {
        "mean": "0.83", "..." : "..."
      }
    }
  }
}
```

---

## 16. Proposed Module/File Structure

```
backend/
  app/
    core/
      evaluation/
        __init__.py
        evaluator.py            ← Evaluator.evaluate(result, ground_truth, corruption_events)
        exception_mapping.py    ← GENERATOR_TO_REC_CODE bridge table + semantic descriptions
        metrics.py              ← pure metric functions, Decimal-safe, null on zero-denom
        aggregator.py           ← MultiSeedAggregator.aggregate([EvaluationResult])
        calibrator.py           ← score distribution analysis, threshold sweep
        benchmark.py            ← throughput harness (benchmark-mode flag only)
        batch_integrity.py      ← batch-level finding taxonomy and scoring
    models/
      evaluation.py             ← EvaluationResult, PerSeedResult, AggregateEvaluationReport,
                                   ThroughputResult, EntityFinding, CalibrationResult,
                                   BatchIntegrityResult, UnsafeAutoMatchMetrics
    services/
      evaluation.py             ← EvaluationService (thin public facade)

  tests/
    evaluation/
      __init__.py
      conftest.py
      test_evaluator.py
      test_metrics.py
      test_exception_mapping.py
      test_aggregator.py
      test_calibrator.py
      test_benchmark.py         (marked: slow)
      test_batch_integrity.py

scripts/
  evaluate_reconciliation.py    ← CLI: run evaluator against one or more seeds
  calibrate_thresholds.py       ← CLI: calibration analysis (calibration seeds only)
  benchmark_reconciliation.py   ← CLI: throughput benchmarks
```

---

## 17. Testing Strategy

### test_metrics.py

All pure functions, all edge cases:

| Test | Description |
|------|-------------|
| `test_perfect_reconciliation` | All TP → precision=1.00, recall=1.00, FP=0 |
| `test_all_abstained` | precision=null, recall=null |
| `test_single_false_match` | 1 FP → unsafe_auto_match_count=1, rate > 0 |
| `test_zero_denominator_precision` | TP+FP=0 → null, insufficient_data=true |
| `test_zero_denominator_recall` | N_clean=0 → null, insufficient_data=true |
| `test_zero_denominator_f1` | Both null → f1=null |
| `test_unsafe_auto_match_rate_zero_denom` | 0 auto-matches → null |
| `test_zero_corruption_dataset` | N_corrupt=0 → exception_recall=null |
| `test_abstain_on_clean` | ABST_CLEAN counted separately from FP_MATCH |
| `test_abstain_on_corrupt` | ABST_CORRUPT counts as TN in Scorecard B |
| `test_all_metrics_return_decimal_not_float` | |
| `test_exception_code_alignment_correct` | Codes intersect expected |
| `test_exception_code_alignment_wrong` | No intersection → WRONG_CODE |
| `test_e007_likely_false_positive` | E007 likely AUTO_MATCHed — measured correctly |

### test_evaluator.py

End-to-end via generate() + reconcile() + evaluate():

| Test | Description |
|------|-------------|
| `test_zero_corruption_all_correct` | 0 corruption → FP=0, unsafe_auto_match=0 |
| `test_full_corruption_profile` | All 8 E-codes → per-type metrics populated |
| `test_e008_payment_and_orphan_independent` | PAY still AUTO_MATCHes; BNK_999 in orphan_records |
| `test_e008_orphan_detected_entity_record` | OrphanRecord has entity_type="bank_entry", payment_id=null |
| `test_e006_duplicate_surfaced` | E006 → HUMAN_REVIEW, rec:E003 |
| `test_e007_unsafe_auto_match_measured` | E007 unsafe_auto_match_count > 0 (Phase 3.1 known gap) |
| `test_batch_integrity_not_clean_with_orphan` | Orphan in batch → batch NOT BATCH_CLEAN |
| `test_ground_truth_not_in_engine_output` | No GroundTruth fields in BatchReconciliationResult |
| `test_engine_modules_no_groundtruth_import` | Assert no GroundTruth import in core/reconciliation/* |
| `test_deterministic_evaluation` | Same inputs → identical EvaluationResult |

### test_batch_integrity.py

| Test | Description |
|------|-------------|
| `test_batch_clean_all_match_no_orphan` | → BATCH_CLEAN |
| `test_batch_partial_some_human_review` | → BATCH_PARTIAL |
| `test_batch_orphan_entity` | Orphan in batch scope → BATCH_ORPHAN_ENTITY |
| `test_batch_duplicate_entity` | Duplicate bank entry → BATCH_DUPLICATE_ENTITY |
| `test_batch_missing_settlement` | E001 → BATCH_MISSING_SETTLEMENT |
| `test_fully_reconciled_rate_not_100_with_orphan` | |

### test_aggregator.py

| Test | Description |
|------|-------------|
| `test_mean_and_std_correctness` | 3 known seeds → correct mean |
| `test_duplicate_seed_raises` | Same seed twice → ValueError |
| `test_null_metric_excluded_from_aggregate` | Seed with null excluded from mean |
| `test_aggregate_reports_insufficient_data_count` | |
| `test_single_seed_std_zero` | |

---

## 18. Risks and Failure Modes

| Risk | Severity | Mitigation |
|------|----------|------------|
| E007 produces unsafe auto-match (expected in Phase 3.1) | High | Evaluator measures and reports it explicitly; Phase 3.3 will add R014 |
| Evaluator accidentally imports GroundTruth into reconciliation module scope | Critical | Test asserts no GroundTruth import in `core/reconciliation/*` |
| Orphan entity (E008) counted as missed payment exception | Medium | Two-scorecard design keeps payment-level and entity-level separate |
| Zero denominator silently returns 0 | High | All metric functions return `null` + `insufficient_data=true` on zero denom |
| Holdout contamination | High | Holdout seed stored in separate config; run count tracked; policy freeze conditions explicit |
| E007 detection gap misattributed to engine failure | Medium | Document as known gap, not defect; calibration step 2 will confirm |
| Batch integrity false positive: clean settlement with orphan from different payment | Medium | Orphan is linked to `settlement_ref`; batch integrity checks by settlement scope, not payment |
| Multi-payment E007: fee variance affects allocation for all batch payments | Medium | Per-payment evaluation still correct (each payment's allocated_amount is checked against corrupted net); TBD-3.2-03 tracks this |

---

## 19. Acceptance Criteria

Phase 3.2 is complete when:

1. `test_metrics.py` passes — all formulas verified, all zero-denominator cases return `null`
2. `test_evaluator.py` passes — including E008 two-level evaluation and E007 unsafe-auto-match measurement
3. `test_batch_integrity.py` passes — batch not reported clean when orphan exists
4. `test_aggregator.py` passes — multi-seed aggregation correct
5. `unsafe_auto_match_count = 0` on a zero-corruption 100-payment dataset (Scorecard A + B both perfect)
6. E008 orphan bank entry appears in `unresolved_entities` with `payment_id = null`
7. E007 unsafe auto-matches are measured and reported (expected nonzero; not a test failure — it's a measurement)
8. `evaluate_reconciliation.py` produces valid JSON against `v1_seed42`
9. Multi-seed report produced for calibration seeds 42–46
10. Holdout seed 999 has never been run (verified by holdout_run_count check)
11. Full test suite still passes (currently 286 passed, 1 skipped) — no regressions

---

## 20. Questions / TBD Decisions

| ID | Question | Impact |
|----|----------|--------|
| TBD-3.2-01 | Maximum acceptable `unsafe_auto_match_rate`? (sets the bar for composite AUTO_MATCH enablement) | Threshold calibration |
| TBD-3.2-02 | Is `ABST_CORRUPT` a true negative or a false negative? Current plan: TN (conservative). | Scorecard B recall |
| TBD-3.2-03 | For E007 in multi-payment batches: each affected payment shares the corrupted net. Does every payment produce a separate finding, or is it batch-level? | Per-corruption count accuracy |
| TBD-3.2-04 | Should V002 WARNING be sufficient to trigger exception detection credit for E007, or must a direct fee-vs-payment rule (R014) be added first? | E007 detection rate |
| TBD-3.2-05 | P95 latency: include per-record timing instrumentation in Phase 3.2 benchmarks? | Benchmark completeness |
| TBD-3.2-06 | `evaluate_reconciliation.py`: accept in-memory ObservedWorld or read from CSV on disk? | CLI design |
| TBD-3.2-07 | For calibration score distribution: should composite scores for payments that reached exact match (and never hit composite stage) be included in the calibration dataset? Their composite score exists but was not the decision factor. | Calibration validity |
| TBD-3.2-08 | Should the two-scorecard design eventually converge into a single weighted composite score for the demo leaderboard, or remain two separate scorecards? | Demo reporting |

---

## READY FOR TECH LEAD REVIEW
