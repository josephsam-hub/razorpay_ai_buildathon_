# Why LedgerLens?

This document outlines the core design philosophy, safety boundaries, and competitive differentiators of LedgerLens.

---

## 1. The Reconciliation Problem
Financial reconciliation involves matching internal sales ledgers against external payment gateway settlements and statement clearings. This process is complex due to timing clearance lags (T+1/T+2 delays), gateway fees, and free-form narration mismatches.

---

## 2. The Naive AI Approach
Many modern hackathon submissions take a naive approach to AI: they ingest two CSV statements, feed them directly to an LLM prompt, and ask the model to output matches.

This introduces severe risks:
- **Financial Hallucinations:** Generative models make mistakes on numeric alignment and date boundaries.
- **Zero Audit Trails:** LLM matches lack logical, step-by-step traces, violating regulatory compliance.
- **Operational Vulnerability:** If the AI provider experiences downtime, the entire matching pipeline halts.

---

## 3. Our Design
LedgerLens resolves this conflict by separating **Authority** from **Investigation**:

```
   Multi-Source Data
          â”‚
          â–¼
   Deterministic Reconciler (Authoritative Decisions)
          â”‚
   â”Œâ”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”
   â–¼             â–¼
Matched      Exception (Abstain / Review)
                 â”‚
                 â–¼
          EvidenceCard (Immutable Logical Traces)
                 â”‚
                 â–¼
          Bounded AI Agent (Non-Authoritative Research)
                 â”‚
                 â–¼
          Human Operator (Final Resolution Action)
```

### The Critical Boundary
> **AI can investigate why a transaction failed to reconcile. It cannot decide whether the transaction reconciles.**

---

## 4. Why This Architecture Matters
1. **Deterministic Authority:** Match decisions are written strictly by logical rule constraints. There is zero risk of an LLM writing incorrect entries to the ledger.
2. **Auditability:** Decisions are recorded with an `EvidenceCard` documenting exact scores, rules applied, and features matched.
3. **Failure Containment:** If the Gemini API is unconfigured or goes offline, the matching engine remains fully operational, routing exceptions to review queues with safe fallback messages.
4. **Human Review Support:** AI accelerates human operations by researching exceptions and retrieving sandbox context, acting as an advisor.

---

## 5. What We Measured
We validated the system using isolated calibration and evaluation seeds:
- **Precision:** `1.0000` (100% correct matches, zero unsafe matches) across all evaluated seeds.
- **Recall:** `98%` (calibration) and `99%` (evaluation) of clean matchable records resolved automatically.
- **Throughput:** `10,000+ payments/second` local matching engine performance.

---

## 6. What We Learned
During testing, we discovered that timing anomalies could slip past rules when delays matched clearance windows. We hardened our date mismatch generators and implemented batch contamination checks to ensure clean records are reclassified when settlement groups fail. This adversarial hardening brought our unsafe matches to exactly zero.

---

## 7. Core Vision
> **LedgerLens is an evidence-first AI finance controller where deterministic rules decide financial truth and AI investigates the exceptions.**
