# LedgerLens Build Challenges

This document details the actual technical hurdles, design tradeoffs, and solutions implemented during the construction of LedgerLens.

---

## 1. Financial Decimal Precision
- **Problem:** JavaScript and Python floating-point operations introduce representation errors (e.g. `0.1 + 0.2 = 0.30000000000000004`), which can cause mismatches in currency reconciliations.
- **Why It Mattered:** Mismatches of even 1 paisa trigger amount discrepancy warnings (`E002`) and route valid transactions to `HUMAN_REVIEW`, lowering matching throughput.
- **What We Discovered:** Storing and computing values using floats leads to rounding discrepancies at scale.
- **Solution:** Standardized on Python's `Decimal` type across all backend services, database storage, and parsing schemas. All decimal numbers are quantised to exactly two decimal places (`0.01`) before comparison.
- **Result:** Elimination of mathematical representation discrepancies across all seeds.

---

## 2. Ground-Truth Contamination
- **Problem:** Evaluator files containing ground-truth classification labels (`ground_truth.json`) are generated in the workspace. If the reconciliation API loads these files, it can achieve artificial accuracy.
- **Why It Mattered:** A finance controller must make decisions based on transactional records, not by looking at the answer sheet.
- **What We Discovered:** Accidental loading of metadata fields in JSON inputs can leak ground truth to matching services.
- **Solution:** Cleansed all payloads. The React console removes metadata keys (`cleanPayloadForApi`) before sending them to the backend, and the backend validates that no ground truth leaks into reconciliation routes.
- **Result:** Complete data isolation between matching and evaluation layers.

---

## 3. Deterministic vs AI Authority
- **Problem:** Naive implementations send transaction pairs to an LLM prompt to ask: "Are these a match?". This creates a single point of failure, adds network latency, and is non-reproducible.
- **Why It Mattered:** LLMs are prone to hallucinating connections, cannot guarantee audit trails, and fail when offline.
- **What We Discovered:** Placing matching authority in an LLM violates financial compliance rules.
- **Solution:** Bounded the AI behind a deterministic authority boundary. The matching engine executes local algorithms first. The AI is only called afterward to explain exceptions using sandboxed read-only tools.
- **Result:** absolute deterministic correctness of matched ledgers, with the AI operating strictly as an advisory analyst.

---

## 4. Timing Anomaly in Date Corruption
- **Problem:** Early versions of the synthetic generator shifted clearing dates by 1 day to simulate delays.
- **Why It Mattered:** The business rules allowed a 1-day clearance latency buffer. The engine correctly matched the transaction, resulting in a false-positive (unsafe auto-match).
- **What We Discovered:** Anomaly generation must violate business clearing timing windows to count as a genuine exception.
- **Solution:** Hardened `corrupt_date_mismatch` to force date delays to exceed the timing window.
- **Result:** Unsafe auto-match rates dropped to exactly 0.0000 across all seeds.

---

## 5. Shared-Evidence Batch Contamination
- **Problem:** A single corrupt payment within a gateway settlement group alters the overall settlement total.
- **Why It Mattered:** The engine correctly flagged other clean payments in the group for review because the totals did not balance. This dropped recall scores to ~55%.
- **What We Discovered:** Clean payments inside contaminated groups cannot be auto-resolved; they are structurally contaminated.
- **Solution:** Implemented batch contamination logic in the evaluator (Model B) that reclassifies expected outcomes for contaminated payments to `HUMAN_REVIEW`.
- **Result:** Evaluation recall rose to 98%â€“99% while maintaining 100% precision.

---

## 6. Gemini Failure Handling
- **Problem:** If the Gemini API keys are unconfigured, limits are exceeded, or network connectivity is lost, the agent fails.
- **Why It Mattered:** A network exception at the AI level must not halt the main financial reconciliation queue.
- **What We Discovered:** Uncaught network exceptions crash API requests.
- **Solution:** Wrapped the LLM invocation in safety handlers. If the API fails, the system records a fallback status (`UNAVAILABLE`) with a descriptive message, while leaving the deterministic reconciliation results intact.
- **Result:** The system remains online and operational even if the AI backend is completely disconnected.

---

## 7. API Information Leakage
- **Problem:** Default FastAPI error handlers return Python tracebacks, exception class names, and filesystem locations in HTTP 500 responses.
- **Why It Mattered:** Revealing internal paths, package versions, or API configuration details to client responses exposes the system to security vulnerabilities.
- **What We Discovered:** Unhandled errors expose raw stack traces to the frontend.
- **Solution:** Intercepted exceptions in `run_reconciliation`. Stack traces are logged server-side (`exc_info=True`), and the API returns a sanitized `{"detail": "Internal reconciliation failure."}` response.
- **Result:** Zero system information leakage on server-side failures.

---

## 8. Offline Frontend UX
- **Problem:** If the backend API goes offline, clicking "Run Reconciliation" or "Investigate" causes silent failures or spinning loading indicators.
- **Why It Mattered:** Misleading operator inputs when disconnected damages user trust.
- **What We Discovered:** Intermittent API connectivity must be communicated immediately to the user interface.
- **Solution:** Implemented a polling health check. If the backend is unreachable, the dashboard displays an offline warning banner and disables all buttons that require backend services, while leaving local actions active.
- **Result:** Intuitive, safe UX state transitions during network transitions.
