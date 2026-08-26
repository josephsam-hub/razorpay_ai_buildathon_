# Phase 4 â€” AI Investigation Layer

## Problem
When a transaction is routed to human review due to amount, timing, or narration discrepancies, a human operator must manually search through policies, ledger logs, and orphan statement lines. This process is time-consuming. We wanted to leverage AI to automate this research, but without introducing hallucination risk into matching decisions.

## What We Built
- Built a sandboxed AI investigation tool (`AgentInvestigationService`) powered by Gemini.
- Created read-only tool APIs (`fetch_payment_evidence`, `fetch_policy_rules`, `list_batch_orphans`) that the agent must use to retrieve context.
- Implemented structured output validation and error sanitization boundaries.

## How It Works
- **Request:** The operator requests an investigation on an unresolved exception.
- **Tool-Calling:** The agent is provided with read-only tools to retrieve the deterministic `EvidenceCard`, review relevant business rules, and check unallocated statement entries.
- **Advisory Report:** The agent synthesizes this data into a structured report (`InvestigationReport`) detailing the root cause, business policy reference, and a suggested operator resolution.

## Why This Architecture is Safer
The AI is completely separated from the matching engine. It has **no access to database write APIs**, cannot modify decision fields, and cannot alter reconciliation confidence levels. If the AI returns an incorrect analysis, the matching ledger remains completely unaffected, and the transaction is still securely held in the review queue.

## Failure / Challenge
- **Challenge:** If the Gemini API keys are unconfigured, limits are exceeded, or network connectivity is lost, the agent crashes, which could halt the user interface.
- **Diagnosis:** Uncaught API exceptions during model calls blocked execution threads.
- **Resolution:** Implemented fallback boundaries. If the AI call fails, the system logs the trace and returns a structured report with status `UNAVAILABLE` and a generic explanation note, keeping the core matching results fully online.

## Evidence
- Bounded investigation client: [`investigation.py`](../../backend/app/services/investigation.py).
- Anomaly mapping utilities: [`exception_mapping.py`](../../backend/app/core/evaluation/exception_mapping.py).
- Unit tests verifying agent fallback behaviors in `backend/tests/reconciliation/test_agent_investigation.py`.

## What This Unlocked
Provided operators with automated research cards, accelerating discrepancy resolution times while preserving safety.

## Judge Takeaway
AI is a powerful research assistant, not a financial ledger decider. Bounding the agent behind read-only APIs ensures auditability and eliminates the risk of AI hallucinations corrupting financial truth.
