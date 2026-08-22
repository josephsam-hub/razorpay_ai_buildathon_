# LedgerLens Engineering Rules

## Project

LedgerLens is an evidence-first AI Finance Controller for Razorpay AI Buildathon Track 04.

The primary finance workflow is:

Payment → Settlement → Bank → Ledger reconciliation.

---

## Core Principles

1. Financial calculations must be deterministic.
2. The LLM must never be the source of financial truth.
3. Every automated decision must be explainable.
4. Every decision must have evidence.
5. The system must support abstention.
6. Never fabricate financial data or evaluation metrics.
7. Synthetic datasets must contain explicit ground truth.
8. All benchmark results must be reproducible.
9. Prefer simple deterministic solutions before AI.
10. Do not add dependencies without justification.

---

## AI Rules

Use AI only when deterministic logic cannot reliably solve the task.

The AI may:

- investigate exceptions
- retrieve evidence through tools
- classify root causes
- generate explanations
- answer natural-language finance questions

The AI must NOT:

- perform authoritative financial arithmetic
- silently modify financial records
- invent evidence
- bypass validation rules
- auto-resolve high-risk cases without policy approval

---

## Engineering Rules

- Use Python for backend/data/ML.
- Use FastAPI for the API.
- Use React + TypeScript for the frontend.
- Use PostgreSQL for persistent application data.
- Use DuckDB/Polars for analytical workloads where appropriate.
- Use Pydantic for API/domain validation.
- Write tests for core financial logic.
- Keep modules small and focused.
- Prefer typed interfaces.
- Avoid unnecessary abstractions.

---

## Reconciliation Rules

Every reconciliation decision should expose:

- source records
- candidate records
- matching features
- rules applied
- confidence
- decision
- exception code when applicable
- audit identifier

Possible decisions:

- AUTO_MATCH
- AGENT_REVIEW
- ABSTAIN
- HUMAN_REVIEW

---

## Git Rules

Use small meaningful commits.

Examples:

feat: add synthetic transaction generator
feat: add deterministic reconciliation engine
test: add reconciliation edge cases
feat: add evidence model
feat: add Gemini investigation tool

Never commit secrets.

Never commit API keys.

Never commit production financial data.

---

## Definition of Done

A feature is complete only when:

1. Code exists.
2. Tests exist where appropriate.
3. It runs locally.
4. Edge cases are considered.
5. Documentation is updated.
6. Git status is clean after commit.