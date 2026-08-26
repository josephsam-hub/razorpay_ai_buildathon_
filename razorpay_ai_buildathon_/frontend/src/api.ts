import type {
  ReconciliationRunRequest,
  ReconciliationRunResponse,
  InvestigationRunRequest,
  InvestigationRunResponse,
} from "./types";

const API_BASE = window.location.port === "5173" ? "http://localhost:8000" : "";

export async function runReconciliation(
  payload: ReconciliationRunRequest
): Promise<ReconciliationRunResponse> {
  const response = await fetch(`${API_BASE}/api/v1/reconciliation/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let errorDetail = "";
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || JSON.stringify(errJson);
    } catch {
      errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export async function investigateException(
  payload: InvestigationRunRequest
): Promise<InvestigationRunResponse> {
  const response = await fetch(`${API_BASE}/api/v1/reconciliation/investigate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let errorDetail = "";
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || JSON.stringify(errJson);
    } catch {
      errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}
