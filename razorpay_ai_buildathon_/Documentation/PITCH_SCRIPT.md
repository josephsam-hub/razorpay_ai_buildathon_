# 5-Minute Pitch Script

**Title:** LedgerLens â€” Evidence-First AI Finance Controller
**Track:** Track 04 â€” AI Finance Controller
**Target Duration:** 4:40 - 4:55

---

## 0:00â€“0:30 â€” THE HOOK

**Visual:** Operator Console, displaying a clean dashboard state. A text slide on screen shows the central thesis.

**Narration:**
> "What happens when you let an AI agent decide whether money reconciles?
>
> We decided not to.
>
> Naive AI reconcilers write matches directly to financial ledgers, introducing hallucination risk, lack of compliance trails, and single-point failure modes when APIs crash.
>
> LedgerLens establishes a strict deterministic boundary around the AI: local algorithms own matching and exception decisions. The AI operates strictly as a read-only advisor, analyzing anomalies through sandboxed, read-only tools. Rules decide financial truth; AI investigates the exceptions."

---

## 0:30â€“1:05 â€” THE PROBLEM

**Visual:** Diagram showing Payment $\rightarrow$ Settlement $\rightarrow$ Bank Statement $\rightarrow$ Ledger flows.

**Narration:**
> "In transaction reconciliation, four source systems must balance. Order payments, settlement payouts, statement entries, and ledger postings frequently disagree due to timing delays, fee structures, and narration variations.
>
> Standard automated matching works for clean data, but when discrepancies occur, a human operator is left searching through raw CSV statements, gateway policies, and unallocated banks. This manual exception analysis is expensive, slow, and prone to oversight."

---

## 1:05â€“1:45 â€” WHAT WE BUILT

**Visual:** System architecture blueprint showing the safety interface dividing the deterministic reconciler and AI agent.

**Narration:**
> "To solve this, we built LedgerLens. It divides the reconciliation loop into separate authority domains:
>
> First, raw data is normalized into canonical Decimal formats.
>
> Second, our matching engine executes validation rules V001 through V004, and composite scoring metrics CS001 through CS004.
>
> Third, every outcome is packaged into an immutable EvidenceCard documenting scores and rule traces.
>
> If a match violates invariants, it is assigned an anomaly code and routed to human review. Only here is the AI agent invokedâ€”non-authoritativelyâ€”to research the exception."

---

## 1:45â€“2:25 â€” LIVE PRODUCT DEMO

**Visual:** Live React Operator Console. Operator drags and drops the JSON batch and clicks "Run Reconciliation".

**Narration:**
> "Letâ€™s look at the operational console. We drag and drop our transactional payload representing 100 payments.
>
> We click 'Run Reconciliation'. Matching executes locally in milliseconds. The dashboard updates immediately: 50% are auto-matched, and the remainder are routed to exception queues.
>
> The operator sees a structured distribution of errors: timing anomalies, amount mismatches, and orphan bank statement entries. No command typing, no waitingâ€”just instant results."

---

## 2:25â€“3:05 â€” EVIDENCE-FIRST EXCEPTION

**Visual:** UI focusing on the "Unresolved Exceptions" list. Operator selects an amount mismatch anomaly.

**Narration:**
> "Instead of trusting a black-box AI score, the operator opens an exception to inspect the EvidenceCard.
>
> Here we see an amount mismatch: payment gross was 98.00, but statement clearing shows 100.00. Rule V002 was violated.
>
> The EvidenceCard shows exactly which validation checks passed, which composite metrics were triggered, and the computed matching scores. This provides a transparent, auditable trail. The operator knows exactly why the engine abstained from matching."

---

## 3:05â€“3:40 â€” AI INVESTIGATION

**Visual:** Operator clicks "Investigate exception with AI". The console log shows tool execution calls.

**Narration:**
> "Now, we trigger the AI investigator. The agent invokes sandboxed APIs: retrieving the EvidenceCard, pulling target pricing rules, and checking unallocated statements.
>
> In seconds, it explains: the gateway fee was altered, causing a 2.00 variance.
>
> Crucially, this analysis is purely advisory. The AI cannot mutate matching decisions, write to ledgers, or modify database fields. The transaction remains safely in review. The AI researches the problem, but the rules preserve financial truth."

---

## 3:40â€“4:25 â€” THE WOW MOMENT: WE ATTACKED OUR OWN SYSTEM

**Visual:** Terminal showing CLI execution of `run_benchmark.py --seeds 42,43,44,45,46`. Slide showing before/after metrics.

**Narration:**
> "Then, we attacked our own reconciler.
>
> We ran multi-seed benchmarking. On Seeds 45 and 103, we found unsafe auto-matches: date mismatch delays accidentally equaled V003 timing clearance buffers, causing false positives. Furthermore, batch contamination from corrupt settlements dropped recall to ~55%.
>
> We did not tweak parameters to look good. We fixed the generator timing invariant and implemented batch contamination metrics in the evaluator. Rerunning independent partitions confirmed that unsafe auto-matches fell to exactly zero, while recall rose to 98%â€“99%."

---

## 4:25â€“4:45 â€” FINAL RESULTS

**Visual:** Scorecard table summarizing calibration and evaluation metrics.

**Narration:**
> "These are the measured metrics from our evaluated partitions:
>
> Across both calibration and evaluation seed sets, our Auto-Match Precision is 100% and unsafe auto-matches are zero.
>
> Auto-Match Recall ranges from 98% to 99%.
>
> Our local reconciliation engine throughput clocks at over 10,000 payments per second, proving that high performance and absolute safety are achievable together."

---

## 4:45â€“5:00 â€” CLOSING

**Visual:** Final slide showing the architecture summary and sitemap links.

**Narration:**
> "LedgerLens does not replace accounting judgment with a chat prompt. It secures deterministic reconciliation with a bounded, sandboxed AI investigator.
>
> Rules decide financial truth. AI explains the exceptions. And when our system failed our own tests, we hardened it before submitting.
>
> LedgerLens: an AI finance controller that knows exactly where AI should not be trusted."
