# LedgerLens Development Phases

This directory documents the step-by-step engineering timeline of **LedgerLens**, detailing the problem, technical implementation, failures, and validations at each milestone.

```
       Phase 0 â€” Repository Setup
                   â”‚
                   â–¼
       Phase 1 â€” Project Foundation
                   â”‚
                   â–¼
       Phase 2 â€” Synthetic Data Generator
                   â”‚
                   â–¼
       Phase 3 â€” Reconciliation Engine
                   â”‚
                   â–¼
       Phase 4 â€” AI Investigation Layer
                   â”‚
                   â–¼
       Phase 5 â€” Operator Dashboard
                   â”‚
                   â–¼
       Phase 6 â€” Benchmarking Framework
                   â”‚
                   â–¼
       Phase 7 â€” Adversarial Hardening
                   â”‚
                   â–¼
               LedgerLens
```

---

## Sitemap

| Phase | Purpose | Documentation Link | Major Outcome |
|---|---|---|---|
| **Phase 0** | Workspace & environment setup | [PHASE_00_REPOSITORY_SETUP.md](./PHASE_00_REPOSITORY_SETUP.md) | Standardized `.env` templates |
| **Phase 1** | Backend routing & main skeleton | [PHASE_01_FOUNDATION.md](./PHASE_01_FOUNDATION.md) | FastAPI main app, health endpoint |
| **Phase 2** | Synthetic order lifecycle models | [PHASE_02_SYNTHETIC_DATA.md](./PHASE_02_SYNTHETIC_DATA.md) | Multi-source clean/corrupt generators |
| **Phase 3** | Exact & Composite rule engine | [PHASE_03_RECONCILIATION_ENGINE.md](./PHASE_03_RECONCILIATION_ENGINE.md) | Decimal matching, V001â€“V004 rules, EvidenceCards |
| **Phase 4** | Bounded AI investigation agent | [PHASE_04_AI_INVESTIGATION.md](./PHASE_04_AI_INVESTIGATION.md) | Gemini integration with read-only tools |
| **Phase 5** | Single-page operator interface | [PHASE_05_OPERATOR_DASHBOARD.md](./PHASE_05_OPERATOR_DASHBOARD.md) | React dashboard, offline connectivity warnings |
| **Phase 6** | Scorecards and metric runners | [PHASE_06_BENCHMARKING.md](./PHASE_06_BENCHMARKING.md) | Precision/Recall/F1/Throughput scripts |
| **Phase 7** | Self-adversarial evaluation | [PHASE_07_HARDENING.md](./PHASE_07_HARDENING.md) | Date delay invariant hardening, Model B reclassification |
