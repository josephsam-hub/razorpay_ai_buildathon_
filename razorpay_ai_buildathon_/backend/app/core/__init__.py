"""
Core package — Phase 3.1 reconciliation engine.

reconciliation/
    normaliser.py  — ObservedWorld → list[CanonicalTransaction]
    exact.py       — Stage 1: exact structural + financial matching
    composite.py   — Stage 2: composite multi-signal scoring
    engine.py      — Cascade orchestration → EvidenceCard + decisions

Planned (Phase 4):
    fuzzy.py       — Stage 3: fuzzy / probabilistic matching
    agent.py       — Stage 4: agent investigation
"""
