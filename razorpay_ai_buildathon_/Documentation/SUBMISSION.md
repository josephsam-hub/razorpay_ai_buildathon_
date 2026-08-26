# Buildathon Submission Form

This document maps LedgerLens capabilities to the official Razorpay AI Buildathon submission fields.

---

## 1. Track Selection
- **Selection:** Track 04 â€” AI Finance Controller

---

## 2. Project Name / Title
- **Title:** LedgerLens â€” Evidence-First AI Finance Controller

---

## 3. Project Objectives
- Build a secure, high-throughput financial controller that isolates AI from direct match decisions.
- Enforce deterministic matching rules as the sole authority for ledger entries.
- Leverage LLMs strictly in a non-authoritative role to investigate and analyze exceptions.
- Provide operators with structured audit trails (`EvidenceCard` rule traces) for every transaction.

---

## 4. What Does It Solve?
LedgerLens solves the compliance, hallucination, and operational latency risks of naive AI reconciliation. In traditional systems, letting an LLM decide matches leads to error propagation and lacks verifiable trails.

Our system divides matching from analysis:
1. **Deterministic matching algorithms** write immutable match records.
2. **AI investigates exceptions** using sandboxed, read-only tools, providing natural-language explanations and suggested actions.

If the AI fails, goes offline, or hallucinates, the core ledger remains correct.

---

## 5. GitHub Repository URL
- **URL:** [https://github.com/josephsam-hub/razorpay_ai_buildathon_.git](https://github.com/josephsam-hub/razorpay_ai_buildathon_.git)

---

## 6. 5-Minute Pitch Video Link
- **Link:** `[TO BE RECORDED]`

---

## 7. Build Challenges & Technical Obstacles

### Decoupling Logic & Authority
Financial audit guidelines require deterministic decisions. We solved this by executing rule checks (`V001`â€“`V004`) and composite calculations (`CS001`â€“`CS004`) locally in milliseconds, restricting the Gemini client to post-match explanation generation.

### Decimals vs Floats
JS/Python floating-point precision leads to rounding drift. We standardized on Python's `Decimal` type across all schemas and services, quantising all amounts to exactly two decimal places.

### Adversarial Timing Anomalies
In early testing, delayed transaction dates fell within allowed clearance timing buffers, creating false positives. We hardened our date mismatch generator to shift dates strictly outside acceptable windows, bringing unsafe matches to exactly zero.

### Batch-Level Contamination
A corrupted payment in a settlement group alters the overall total, making clean payments unmatchable and dropping baseline recall to ~55%. We implemented batch-level reclassification in our evaluator, bringing recall back to 98%â€“99%.
