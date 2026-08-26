# 5-Minute Demo Presentation Script

This document details the recommended workflow, visual layout, and voiceover guidelines for the 5-minute pitch video submission.

---

## 0:00â€“0:30 (The Hook & The Core Principle)
- **What is shown:**
  - Landing dashboard view of the React Console.
  - Quick display of the core architecture flow: Normalization $\rightarrow$ Deterministic Reconciler $\rightarrow$ AI Investigation.
- **What is said:**
  - *"In corporate finance, letting an AI agent make matching decisions is unsafe. Generative models hallucinate, lack mathematical audit trails, and represent a security risk."*
  - *"We built LedgerLens: an evidence-first finance controller. Our central design principle is: AI explains exceptions, but deterministic rules decide financial truth."*
- **What the judge should understand:**
  - AI operates purely as a read-only advisor behind a deterministic safety boundary.

---

## 0:30â€“1:15 (Ingestion & Normalisation)
- **What is shown:**
  - Operator dragging and dropping the synthetic dataset files (`observed_transactions.json` containing 100 payments, settlements, statement lines, and ledger entries).
  - The UI showing parsing progress indicators.
- **What is said:**
  - *"We ingest raw files from multiple sources: payment gates, statement exports, and internal ledgers. Everything is parsed, timezone-aligned, and converted to canonical types using Decimal precision."*
- **What the judge should understand:**
  - Raw inputs are normalized and sanitized before matching execution.

---

## 1:15â€“2:00 (Reconciliation Execution)
- **What is shown:**
  - The operator clicking the **"Run Reconciliation"** button.
  - The dashboard updating to display the summary metrics card: Total Payments (100), Auto-Matched (e.g. 50), Human Review (e.g. 40), Abstained (e.g. 10).
  - Metrics graphs showing match distributions and confidence levels.
- **What is said:**
  - *"Reconciliation runs locally in milliseconds, achieving a local engine throughput of over 10,000 payments per second. We see our results immediately: 50% matched automatically, and the remainder routed to exception queues."*
- **What the judge should understand:**
  - High-performance, local deterministic matching operates independently of third-party APIs.

---

## 2:00â€“3:00 (Exception Identification & EvidenceCards)
- **What is shown:**
  - Operator clicking on an exception record in the "Unresolved Exceptions" panel.
  - The UI displaying the **EvidenceCard** containing rules executed, scores computed, and matching details.
- **What is said:**
  - *"For every unresolved exception, the engine builds an EvidenceCard. Here we see an amount mismatch: payment net was 98.00, but the statement was 100.00. Rule V002 was violated, routing the transaction to review."*
- **What the judge should understand:**
  - Every matching decision is fully auditable with deterministic evidence records.

---

## 3:00â€“3:45 (Agentic Investigation & Sandboxing)
- **What is shown:**
  - Operator clicking **"Investigate exception with AI"**.
  - The agent executing tools: `fetch_payment_evidence()`, `fetch_policy_rules()`, etc.
  - The UI displaying the generated structured analysis (root cause, policy reference, suggested operator action).
- **What is said:**
  - *"Now we trigger the AI. The agent retrieves context using sandboxed, read-only tools to analyze the discrepancy. It highlights that the settlement fee contract was violated, and suggests adjusting the pricing parameters."*
- **What the judge should understand:**
  - AI leverages tool-calling to research discrepancies, presenting findings in a structured, non-authoritative format.

---

## 3:45â€“4:30 (Self-Adversarial Hardening Story)
- **What is shown:**
  - CLI terminal window running `python scripts/run_benchmark.py --seeds 42,43,44,45,46`.
  - The stdout scorecard output showing 100% precision and 98% recall.
- **What is said:**
  - *"We benchmarked our system using calibration and evaluation partitions. Initial benchmarks exposed unsafe auto-matches due to date timing overlaps. We fixed the generator invariant and evaluator contamination rules, bringing unsafe auto-matches to exactly zero while keeping recall at 98â€“99%."*
- **What the judge should understand:**
  - LedgerLens was hardened through active self-adversarial validation, ensuring robust metrics.

---

## 4:30â€“5:00 (Architecture Summary)
- **What is shown:**
  - Summary slide detailing the final architecture block, GitHub repository link, and sitemap.
- **What is said:**
  - *"LedgerLens demonstrates how to integrate AI safely in enterprise finance: deterministic matching for authority, and AI for research and explanation. All code, benchmarks, and E2E E2E tests are available on our public GitHub repository. Thank you."*
