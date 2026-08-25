"""
Core package — Phase 3.1 reconciliation engine + Phase 3.2 evaluation layer.

reconciliation/
    normaliser.py   — ObservedWorld → NormaliserResult
    exact.py        — Stage 1: structural + financial matching
    composite.py    — Stage 2: composite multi-signal scoring
    engine.py       — Cascade orchestration
    validation.py   — Post-match temporal validation (V001–V004)
    policy.py       — Configurable policy constants

evaluation/
    evaluator.py         — Evaluator: joins engine output with ground truth
    exception_mapping.py — E001–E008 semantic bridge table
    metrics.py           — Pure Decimal-safe metric functions
    batch_integrity.py   — Batch-level integrity analysis
    aggregator.py        — MultiSeedAggregator
    benchmark.py         — Throughput benchmark harness

Planned (Phase 4):
    reconciliation/fuzzy.py   — Stage 3: fuzzy matching
    reconciliation/agent.py   — Stage 4: agent investigation
"""
