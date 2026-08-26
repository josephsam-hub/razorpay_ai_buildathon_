# Pitch Shot List

This document outlines the visual timeline, screen targets, actions, and narration beats for the 5-minute LedgerLens pitch.

---

| Timestamp | Screen / Layout | Operator / CLI Action | Narration Beat | What the Judge Should Notice |
|---|---|---|---|---|
| **0:00 - 0:15** | Landing view of React Operator Console | Hover over clean dashboard metrics | *"What happens when you let an AI decide whether money reconciles? We decided not to."* | Clean, professional UI layout with live API status. |
| **0:15 - 0:30** | Text slide detailing the "Core Thesis" | No interaction | *"Naive AI reconcilers write matches directly to ledgers, risking errors. LedgerLens enforces rule authority."* | The non-authoritative AI boundary concept. |
| **0:30 - 0:45** | Flow diagram: Payments $\rightarrow$ Payouts $\rightarrow$ Clearings | No interaction | *"In reconciliation, four source systems must balance. Records disagree due to timing delays and fees."* | Clear finance-ops problem statement (Track 04). |
| **0:45 - 1:05** | UI list of transaction sources | Scroll through Payment and statement list | *"discrepancies leave humans searching through raw statements. This manual analysis is slow and expensive."* | Real-world corporate accounting exception problem. |
| **1:05 - 1:25** | System Architecture Block slide | No interaction | *"We built LedgerLens. First, raw data is normalized. Second, the engine checks validation rules."* | Deterministic-first matching pipeline. |
| **1:25 - 1:45** | EvidenceCard & Anomaly routing diagram | Hover over V001â€“V004 rule boxes | *"Every outcome creates an EvidenceCard. Discrepancies get anomaly codes and route to human review."* | Rule trace logging and exception queues. |
| **1:45 - 2:05** | React Dashboard main view | Drag-and-drop batch JSON file into the drop zone | *"Letâ€™s look at the console. We drag and drop our transactional payload representing 100 payments."* | File drop zones and local parsing indicators. |
| **2:05 - 2:25** | React Dashboard main view | Click **"Run Reconciliation"** | *"Reconciliation runs locally in milliseconds. 50% match automatically, others route to exception queues."* | Fast state transitions and visual graphs update. |
| **2:25 - 2:45** | UI "Unresolved Exceptions" panel | Click on transaction with code `E002` (Amount Mismatch) | *"Instead of trusting a black-box AI score, the operator opens an exception to inspect the EvidenceCard."* | Categorized exception list with filter badges. |
| **2:45 - 3:05** | EvidenceCard detail modal | Scroll through matching scores and triggered rules | *"Here we see an amount mismatch: payment was 98.00, statement was 100.00. Rule V002 was violated."* | Logical audit trails documenting computed scores. |
| **3:05 - 3:20** | Anomaly detail view | Click **"Investigate Exception with AI"** | *"Now, we trigger the AI investigator. The agent uses sandboxed APIs to retrieve rules and orphans."* | AI retrieval logs executing in the console interface. |
| **3:20 - 3:40** | AI Analysis report card | Scroll through cause and recommendation notes | *"In seconds, it explains: the fee contract was violated. This report is advisory; matching decisions remain locked."* | AI operates strictly as an advisor, cannot mutate data. |
| **3:40 - 4:00** | Terminal Console | Run calibration benchmark command | *"Then, we attacked our own reconciler. Multi-seed benchmarks exposed timing overlaps on Seeds 45/103."* | Execution of the local script `run_benchmark.py`. |
| **4:00 - 4:25** | Metrics comparison slide | Highlight before/after recall values | *"We fixed the timing delay invariants and batch contamination logic, bringing unsafe matches to exactly zero."* | Real engineering discovery and metrics correction. |
| **4:25 - 4:45** | Scorecard results table slide | Hover over Precision and Recall score rows | *"Across both calibration and evaluation seed sets, Precision is 100%, and recall ranges from 98% to 99%."* | Verified 99% recall and 10k/sec local throughput. |
| **4:45 - 5:00** | Architecture sitemap and closing slide | No interaction | *"LedgerLens secures deterministic matching with sandboxed AI. Rules decide financial truth; AI explains the exceptions."* | Strong compliance-ready closing statement. |
