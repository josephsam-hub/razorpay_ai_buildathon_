# Phase 5 â€” Operator Dashboard

## Problem
A financial controller system needs an intuitive user interface. Operators must be able to upload batches, execute matching, inspect evidence rules, check exception lists, and trigger AI analysis without writing commands.

## What We Built
- Built an interactive single-page console UI utilizing React and TypeScript.
- Implemented file drop targets supporting drag-and-drop batch imports.
- Created visualizations for summary metrics (match rate, exception distributions).
- Integrated inline review modules showing EvidenceCards and AI investigation responses.

## How It Works
- The frontend connects to the backend API (`/api/v1/reconciliation/run` and `/investigate`).
- If API calls fail, the interface transitions operational states dynamically to prevent operator errors.

## Failure / Challenge
- **Challenge:** If the backend went offline during transaction execution or exception analysis, the UI showed silent spinning loaders, damaging trust.
- **Diagnosis:** A disconnected API caused unresolved fetch promises.
- **Resolution:** Added a polling health checker. If the backend is unreachable, the dashboard renders an offline warning banner, disables the "Run Reconciliation" and "Investigate" buttons, while keeping local features active.

## Evidence
- Frontend Console code: [`App.tsx`](../../frontend/src/App.tsx) and styling rules in [`App.css`](../../frontend/src/App.css).
- Offline-safe state rendering components.

## What This Unlocked
Allowed the end-to-end finance-ops loop to be demonstrated visually and tested interactively by operators.

## Judge Takeaway
User interfaces must match backend resilience. Enforcing state transitions and connection status checks in the UI protects operators from running actions during system disconnects.
