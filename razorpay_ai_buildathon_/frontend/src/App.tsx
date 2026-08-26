import React, { useState, useRef, useEffect } from "react";
import "./App.css";
import * as api from "./api";
import type {
  ReconciliationRunRequest,
  ReconciliationRunResponse,
  BatchReconciliationResult,
  ExceptionRecord,
  EvidenceCard,
  ReconciliationDecision,
  InvestigationReport,
  OrphanRecord
} from "./types";

// Safety cleansing function to prevent sending forbidden evaluation/corruption metadata
function cleanPayloadForApi(rawJson: any): any {
  const forbiddenKeys = new Set([
    "ground_truth",
    "corruption_events",
    "applied_seed",
    "corruption_id",
    "original_value",
    "observed_value",
    "corruption_type",
    "target_entity",
    "target_record_id"
  ]);

  function cleanObj(obj: any): any {
    if (obj === null || obj === undefined) return obj;
    if (Array.isArray(obj)) {
      return obj.map(cleanObj);
    }
    if (typeof obj === "object") {
      const cleaned: any = {};
      for (const [k, v] of Object.entries(obj)) {
        if (!forbiddenKeys.has(k)) {
          cleaned[k] = cleanObj(v);
        }
      }
      return cleaned;
    }
    return obj;
  }

  return cleanObj(rawJson);
}

// Visual layout helper for currency formatting
function formatCurrency(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined) return "-";
  const num = typeof amount === "string" ? parseFloat(amount) : amount;
  if (isNaN(num)) return String(amount);
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2
  }).format(num);
}

// Visual layout helper for percentage formatting
function formatPercent(rate: string | number | null | undefined): string {
  if (rate === null || rate === undefined) return "-";
  const num = typeof rate === "string" ? parseFloat(rate) : rate;
  if (isNaN(num)) return String(rate);
  return `${(num * 100).toFixed(1)}%`;
}

export default function App() {
  // State variables
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [batchData, setBatchData] = useState<ReconciliationRunRequest | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [cleansedMessage, setCleansedMessage] = useState<string | null>(null);

  // API Response States
  const [loadingReconciliation, setLoadingReconciliation] = useState<boolean>(false);
  const [reconciliationResponse, setReconciliationResponse] = useState<ReconciliationRunResponse | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  // Selected Payment details for investigation
  const [selectedPaymentId, setSelectedPaymentId] = useState<string | null>(null);

  // Investigation States
  const [loadingInvestigation, setLoadingInvestigation] = useState<boolean>(false);
  const [investigationReport, setInvestigationReport] = useState<InvestigationReport | null>(null);
  const [investigationError, setInvestigationError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"evidence" | "orphans">("evidence");

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Check API health status on mount
  useEffect(() => {
    async function checkHealth() {
      try {
        const API_BASE = window.location.port === "5173" ? "http://localhost:8000" : "";
        const res = await fetch(`${API_BASE}/health`);
        if (res.ok) {
          const data = await res.json();
          setApiOnline(data.status === "ok");
        } else {
          setApiOnline(false);
        }
      } catch {
        setApiOnline(false);
      }
    }
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  // Handle Drag & Drop events
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      processFile(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      processFile(file);
    }
  };

  // Process and validate the uploaded JSON file
  const processFile = (file: File) => {
    if (file.type !== "application/json" && !file.name.endsWith(".json")) {
      setValidationError("Invalid file format. Please upload a JSON file.");
      setBatchData(null);
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
    setValidationError(null);
    setCleansedMessage(null);
    setReconciliationResponse(null);
    setSelectedPaymentId(null);
    setInvestigationReport(null);

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const result = e.target?.result;
        if (typeof result !== "string") {
          throw new Error("Failed to read file content.");
        }

        const json = JSON.parse(result);

        // Core array structure validations
        const requiredKeys = ["merchants", "payments", "settlements", "bank_entries", "ledger_entries"];
        const missingKeys = requiredKeys.filter((key) => !Array.isArray(json[key]));

        if (missingKeys.length > 0) {
          throw new Error(
            `JSON structure is invalid. Missing required arrays: ${missingKeys.join(", ")}`
          );
        }

        if (json.payments.length === 0) {
          throw new Error("The payments array cannot be empty. Please provide a valid batch.");
        }

        // Float validation on frontend side before hitting API
        const checkFloatInObj = (obj: any): boolean => {
          if (typeof obj === "number" && !Number.isInteger(obj)) {
            return true;
          }
          if (Array.isArray(obj)) {
            return obj.some(checkFloatInObj);
          }
          if (obj !== null && typeof obj === "object") {
            return Object.values(obj).some(checkFloatInObj);
          }
          return false;
        };

        if (checkFloatInObj(json)) {
          throw new Error("Financial amounts must be represented as strings or integers. Float values are forbidden.");
        }

        // Check if metadata contains forbidden keys that will be auto-cleansed
        const hasForbidden = (obj: any): boolean => {
          const forbiddenKeys = ["ground_truth", "corruption_events", "applied_seed", "corruption_id"];
          if (obj !== null && typeof obj === "object") {
            if (Array.isArray(obj)) {
              return obj.some(hasForbidden);
            }
            for (const k of Object.keys(obj)) {
              if (forbiddenKeys.includes(k)) return true;
              if (hasForbidden(obj[k])) return true;
            }
          }
          return false;
        };

        const metadataFound = hasForbidden(json);
        const cleansed = cleanPayloadForApi(json);

        setBatchData(cleansed);
        if (metadataFound) {
          setCleansedMessage("Evaluation/Ground-Truth metadata was detected and auto-cleansed from the payload for safety.");
        }
      } catch (err: any) {
        setValidationError(err.message || "Failed to parse JSON file.");
        setBatchData(null);
        setSelectedFile(null);
      }
    };
    reader.readAsText(file);
  };

  const removeFile = () => {
    setSelectedFile(null);
    setBatchData(null);
    setValidationError(null);
    setCleansedMessage(null);
    setReconciliationResponse(null);
    setSelectedPaymentId(null);
    setInvestigationReport(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  // POST to API /api/v1/reconciliation/run
  const triggerReconciliation = async () => {
    if (!batchData) return;

    setLoadingReconciliation(true);
    setApiError(null);
    setReconciliationResponse(null);
    setSelectedPaymentId(null);
    setInvestigationReport(null);

    try {
      const response = await api.runReconciliation(batchData);
      setReconciliationResponse(response);
    } catch (err: any) {
      setApiError(err.message || "Reconciliation request failed. Please check the backend connection.");
    } finally {
      setLoadingReconciliation(false);
    }
  };

  // POST to API /api/v1/reconciliation/investigate
  const triggerInvestigation = async (paymentId: string) => {
    if (!batchData) return;

    setSelectedPaymentId(paymentId);
    setLoadingInvestigation(true);
    setInvestigationError(null);
    setInvestigationReport(null);

    try {
      const invPayload = {
        ...batchData,
        target_payment_id: paymentId,
      };
      const response = await api.investigateException(invPayload);
      setInvestigationReport(response.investigation_report);
    } catch (err: any) {
      setInvestigationError(err.message || "Exception investigation request failed.");
    } finally {
      setLoadingInvestigation(false);
    }
  };

  // Helper selectors derived from response data
  const result: BatchReconciliationResult | null = reconciliationResponse?.reconciliation_result || null;
  const exceptions: ExceptionRecord[] = reconciliationResponse?.exceptions || [];

  // Find currently selected payment details
  const selectedDecision: ReconciliationDecision | undefined = result?.decisions.find((d) => d.payment_id === selectedPaymentId);
  const selectedEvidence: EvidenceCard | undefined = result?.evidence_cards.find((c) => c.payment_id === selectedPaymentId);
  const selectedPaymentInfo = batchData?.payments.find((p) => p.payment_id === selectedPaymentId);

  return (
    <div className="console-container">
      {/* 1. Header Section */}
      <header className="console-header">
        <div className="brand-section">
          <div className="brand-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
              <path d="m9 12 2 2 4-4"/>
            </svg>
          </div>
          <div>
            <h1 className="brand-title">LedgerLens</h1>
            <p className="brand-subtitle">AI Finance Controller</p>
          </div>
        </div>

        <div className="status-badge">
          <span className={`indicator ${apiOnline ? "online" : "offline"}`} />
          <span>API Status: {apiOnline ? "ONLINE" : apiOnline === false ? "OFFLINE" : "CHECKING..."}</span>
        </div>
      </header>

      <div className="console-workspace">
        {/* Left Sidebar - File Loader and Status Controls */}
        <aside className="workspace-sidebar">
          <div className="console-panel">
            <h2 className="panel-title">Batch Ingestion</h2>

            {!selectedFile ? (
              <div
                className={`dropzone-container ${dragActive ? "drag-active" : ""}`}
                onDragEnter={handleDrag}
                onDragOver={handleDrag}
                onDragLeave={handleDrag}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <input
                  type="file"
                  ref={fileInputRef}
                  className="file-input"
                  accept=".json"
                  onChange={handleFileChange}
                />
                <div className="upload-icon">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                </div>
                <p className="upload-text">Drag & drop batch or <strong>browse</strong></p>
                <p className="upload-hint">JSON format only</p>
              </div>
            ) : (
              <div className="file-details">
                <div className="file-header">
                  <span className="file-name" title={selectedFile.name}>{selectedFile.name}</span>
                  <button className="btn-remove-file" onClick={removeFile} title="Remove File">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18"/>
                      <line x1="6" y1="6" x2="18" y2="18"/>
                    </svg>
                  </button>
                </div>

                {batchData && (
                  <div className="file-meta-grid">
                    <div className="meta-item">
                      <span>Payments</span>
                      <span>{batchData.payments.length}</span>
                    </div>
                    <div className="meta-item">
                      <span>Settlements</span>
                      <span>{batchData.settlements.length}</span>
                    </div>
                    <div className="meta-item">
                      <span>Bank Lines</span>
                      <span>{batchData.bank_entries.length}</span>
                    </div>
                    <div className="meta-item">
                      <span>Ledger Rows</span>
                      <span>{batchData.ledger_entries.length}</span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {cleansedMessage && (
              <div className="validation-error" style={{ borderLeftColor: "#3b82f6", background: "rgba(59,130,246,0.08)", color: "#93c5fd" }}>
                {cleansedMessage}
              </div>
            )}

            {validationError && (
              <div className="validation-error">
                {validationError}
              </div>
            )}

            {batchData && (
              <div style={{ marginTop: "16px" }}>
                <button
                  className="btn-action"
                  onClick={triggerReconciliation}
                  disabled={loadingReconciliation || !apiOnline}
                >
                  {loadingReconciliation ? (
                    <>
                      <span className="spinner" style={{ width: "16px", height: "16px", borderWidth: "2px" }} />
                      Reconciling...
                    </>
                  ) : (
                    <>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="23 4 23 10 17 10" />
                        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
                      </svg>
                      Run Reconciliation
                    </>
                  )}
                </button>
              </div>
            )}
          </div>

          {/* Connection API Error Banner */}
          {apiError && (
            <div className="api-error-banner">
              <div>
                <strong>Reconciliation Error:</strong>
                <p style={{ fontSize: "0.75rem", marginTop: "4px" }}>{apiError}</p>
              </div>
              <button className="btn-close-banner" onClick={() => setApiError(null)}>&times;</button>
            </div>
          )}

          {/* Left Column - Orphan Records View */}
          {result && (
            <div className="console-panel orphans-panel" style={{ flexGrow: 1, minHeight: 0 }}>
              <h2 className="panel-title">
                Unmatched Orphans
                <span className="badge-severity LOW" style={{ fontSize: "0.6875rem" }}>
                  {result.orphan_records.length} Found
                </span>
              </h2>

              {result.orphan_records.length === 0 ? (
                <p style={{ fontSize: "0.8125rem", color: "var(--text-muted)", fontStyle: "italic" }}>
                  No orphan records detected in this batch.
                </p>
              ) : (
                <div className="orphans-list">
                  {result.orphan_records.map((orphan: OrphanRecord) => (
                    <div className="orphan-card" key={orphan.orphan_id}>
                      <div className="orphan-meta">
                        <span className="orphan-type">{orphan.entity_type.replace("_", " ")}</span>
                        <span className="orphan-code">{orphan.exception_code}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span className="orphan-id">{orphan.entity_id}</span>
                        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Ref: {orphan.unmatched_ref}</span>
                      </div>
                      {orphan.notes && (
                        <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "4px" }}>
                          {orphan.notes}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>

        {/* Main Console Area */}
        <main className="workspace-main">
          {apiOnline === false && (
            <div className="offline-warning-banner">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
              <span><strong>Console Offline:</strong> Backend connection was lost. Operational actions and investigations are temporarily suspended.</span>
            </div>
          )}
          {/* 3. Overview Metrics Grid */}
          {result ? (
            <div className="metrics-grid">
              <div className="metric-card">
                <span className="metric-label">Total Payments</span>
                <span className="metric-value">{result.total_records}</span>
                <span className="metric-footer">Anchor elements</span>
              </div>
              <div className="metric-card" style={{ borderLeft: "3px solid var(--color-success)" }}>
                <span className="metric-label">Auto Matched</span>
                <span className="metric-value" style={{ color: "var(--color-success)" }}>
                  {result.auto_matched}
                </span>
                <span className="metric-footer">Confidence = 1.00</span>
              </div>
              <div className="metric-card" style={{ borderLeft: "3px solid var(--color-warning)" }}>
                <span className="metric-label">Human Review</span>
                <span className="metric-value" style={{ color: "var(--color-warning)" }}>
                  {result.human_review}
                </span>
                <span className="metric-footer">Operator review needed</span>
              </div>
              <div className="metric-card" style={{ borderLeft: "3px solid var(--color-danger)" }}>
                <span className="metric-label">Abstained</span>
                <span className="metric-value" style={{ color: "var(--color-danger)" }}>
                  {result.abstained}
                </span>
                <span className="metric-footer">Safe fallback trigger</span>
              </div>
              <div className="metric-card">
                <span className="metric-label">Auto Match Rate</span>
                <span className="metric-value" style={{ color: "var(--color-info)" }}>
                  {formatPercent(result.match_rate)}
                </span>
                <span className="metric-footer">Exception: {formatPercent(result.exception_rate)}</span>
              </div>
            </div>
          ) : (
            <div className="empty-state" style={{ height: "100px", borderStyle: "solid" }}>
              <p>Ingest a batch file and click "Run Reconciliation" to populate the matching metrics.</p>
            </div>
          )}

          {/* Main workspace section with exception table and detail panel */}
          {reconciliationResponse && (
            <div className="dashboard-body-grid">
              {/* Left Column: Exception Queue */}
              <section className="queue-section">
                <div className="panel-title" style={{ marginBottom: 0 }}>
                  <span>Exception Queue & Match Trail</span>
                  <span className="badge-severity HIGH" style={{ background: "var(--color-warning-bg)", color: "var(--color-warning)" }}>
                    {exceptions.length} exceptions detected
                  </span>
                </div>

                <div className="queue-table-container">
                  <table className="queue-table">
                    <thead>
                      <tr>
                        <th>Payment ID</th>
                        <th>Decision</th>
                        <th>Exception Code</th>
                        <th>Amount</th>
                        <th>Severity</th>
                        <th style={{ textAlign: "center" }}>Investigation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result?.decisions.map((decision) => {
                        const pm = batchData?.payments.find((p) => p.payment_id === decision.payment_id);
                        const isException = decision.decision !== "AUTO_MATCH";
                        const isSelected = selectedPaymentId === decision.payment_id;

                        // Select primary exception details from the exceptions list
                        const exRecord = exceptions.find((e) => e.payment_id === decision.payment_id);

                        return (
                          <tr
                            key={decision.payment_id}
                            className={isSelected ? "selected" : ""}
                            onClick={() => setSelectedPaymentId(decision.payment_id)}
                          >
                            <td style={{ fontWeight: 600 }}>{decision.payment_id}</td>
                            <td>
                              <span className={`badge-decision ${decision.decision}`}>
                                {decision.decision}
                              </span>
                            </td>
                            <td>
                              {decision.exception_codes.length > 0 ? (
                                <span style={{ color: "var(--color-danger)", fontWeight: 700 }}>
                                  {decision.exception_codes.join(", ")}
                                </span>
                              ) : (
                                <span style={{ color: "var(--text-muted)" }}>-</span>
                              )}
                            </td>
                            <td className="currency-amount">
                              {formatCurrency(pm?.amount)}
                            </td>
                            <td>
                              {exRecord ? (
                                <span className={`badge-severity ${exRecord.severity}`}>
                                  {exRecord.severity}
                                </span>
                              ) : (
                                <span style={{ color: "var(--color-success)", fontSize: "0.75rem", fontWeight: 600 }}>CLEAN</span>
                              )}
                            </td>
                            <td style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                              {isException ? (
                                <button
                                  className="investigate-btn"
                                  onClick={() => triggerInvestigation(decision.payment_id)}
                                  disabled={loadingInvestigation || !apiOnline}
                                >
                                  Investigate
                                </button>
                              ) : (
                                <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>N/A</span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* Right Column: Investigation Sidebar Panel */}
              <section className="investigation-panel-container">
                <div className="console-panel" style={{ flexGrow: 1, display: "flex", flexDirection: "column" }}>
                  <h3 className="panel-title">Inspection & Audit Trail</h3>

                  {selectedPaymentId ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                      {/* Tab selector */}
                      <div className="tab-container">
                        <button
                          className={`tab-btn ${activeTab === "evidence" ? "active" : ""}`}
                          onClick={() => setActiveTab("evidence")}
                        >
                          Deterministic Card
                        </button>
                        <button
                          className={`tab-btn ${activeTab === "orphans" ? "active" : ""}`}
                          onClick={() => setActiveTab("orphans")}
                        >
                          Matching Context
                        </button>
                      </div>

                      {activeTab === "evidence" && (
                        <>
                          {/* Visually Isolated: DETERMINISTIC RECONCILIATION FACTS */}
                          <div className="deterministic-facts-panel">
                            <h4 className="inv-section-title deterministic">
                              Deterministic Matching Facts (Authoritative)
                            </h4>

                            <div className="meta-list" style={{ marginBottom: "14px" }}>
                              <div className="meta-row">
                                <span>Target Payment ID</span>
                                <span>{selectedPaymentId}</span>
                              </div>
                              <div className="meta-row">
                                <span>Reconciliation Decision</span>
                                <span>
                                  {selectedDecision ? (
                                    <span className={`badge-decision ${selectedDecision.decision}`}>
                                      {selectedDecision.decision}
                                    </span>
                                  ) : "-"}
                                </span>
                              </div>
                              <div className="meta-row">
                                <span>Deterministic Confidence</span>
                                <span className="value-highlight">
                                  {selectedDecision ? parseFloat(selectedDecision.confidence).toFixed(2) : "-"}
                                </span>
                              </div>

                              {selectedEvidence && (
                                <>
                                  <div className="meta-row">
                                    <span>Audit Tracker ID</span>
                                    <span style={{ fontFamily: "monospace" }}>{selectedEvidence.audit_id}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Gateway Reference</span>
                                    <span>{selectedPaymentInfo?.gateway_ref || "-"}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Date Delta (days)</span>
                                    <span className="value-highlight">
                                      {selectedEvidence.date_delta_days !== null ? selectedEvidence.date_delta_days : "N/A"}
                                    </span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Amount Delta (INR)</span>
                                    <span className="value-highlight" style={{ color: selectedEvidence.amount_delta && parseFloat(selectedEvidence.amount_delta) !== 0 ? "var(--color-danger)" : "var(--color-success)" }}>
                                      {selectedEvidence.amount_delta ? formatCurrency(selectedEvidence.amount_delta) : "N/A"}
                                    </span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Fee Delta (INR)</span>
                                    <span className="value-highlight">
                                      {selectedEvidence.fee_delta ? formatCurrency(selectedEvidence.fee_delta) : "N/A"}
                                    </span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Matched Settlement ID</span>
                                    <span>{selectedEvidence.matched_settlement_id || "None"}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Matched Bank Line ID</span>
                                    <span>{selectedEvidence.matched_bank_entry_id || "None"}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Matched Ledger Row ID</span>
                                    <span>{selectedEvidence.matched_ledger_entry_id || "None"}</span>
                                  </div>
                                </>
                              )}
                            </div>

                            {selectedEvidence && selectedEvidence.evidence.length > 0 && (
                              <div style={{ marginTop: "12px" }}>
                                <p style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-secondary)", marginBottom: "6px" }}>
                                  Rule Evaluation Trace:
                                </p>
                                <div className="evidence-card evidence-trail">
                                  {selectedEvidence.evidence.map((ev, i) => (
                                    <div className="evidence-step" key={i}>
                                      <div className="step-header">
                                        <span className="step-rule">{ev.rule_id}</span>
                                        <span className={`step-matched ${ev.matched ? "pass" : "fail"}`}>
                                          {ev.matched ? "PASS" : "FAIL"}
                                        </span>
                                      </div>
                                      <p className="step-desc">{ev.rule_description}</p>
                                      {(ev.expected_value || ev.observed_value) && (
                                        <div className="step-values">
                                          <div className="value-pair">
                                            Expected: <span>{ev.expected_value || "null"}</span>
                                          </div>
                                          <div className="value-pair">
                                            Observed: <span>{ev.observed_value || "null"}</span>
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </>
                      )}

                      {activeTab === "orphans" && (
                        <div className="meta-list">
                          <h4 className="inv-section-title deterministic">Alternative Candidates & Findings</h4>
                          {selectedEvidence && selectedEvidence.alternative_candidate_ids.length > 0 ? (
                            <div>
                              <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginBottom: "6px" }}>
                                Competing settlement/bank lines considered:
                              </p>
                              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "14px" }}>
                                {selectedEvidence.alternative_candidate_ids.map((cid) => (
                                  <span key={cid} className="value-highlight">{cid}</span>
                                ))}
                              </div>
                            </div>
                          ) : (
                            <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", fontStyle: "italic", marginBottom: "14px" }}>
                              No alternative matching candidates were found.
                            </p>
                          )}

                          {selectedEvidence && selectedEvidence.validation_findings.length > 0 && (
                            <div>
                              <p style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-secondary)", marginBottom: "6px" }}>
                                Invariant Violations (Findings):
                              </p>
                              <div className="orphans-list">
                                {selectedEvidence.validation_findings.map((f, i) => (
                                  <div className="orphan-card" key={i} style={{ borderLeft: `3px solid var(--color-${f.severity === "ERROR" ? "danger" : "warning"})` }}>
                                    <div className="orphan-meta">
                                      <span className="orphan-type">{f.rule_id}</span>
                                      <span className={`badge-severity ${f.severity}`}>{f.severity}</span>
                                    </div>
                                    <p style={{ fontSize: "0.75rem", fontWeight: 600 }}>{f.rule_description}</p>
                                    <p style={{ fontSize: "0.72rem", color: "var(--text-secondary)" }}>
                                      Expected: {f.expected_relationship} | Observed: {f.observed_relationship}
                                    </p>
                                    {f.delta && <p style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}>Delta: {f.delta}</p>}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Visually Isolated: AI AGENT INVESTIGATION */}
                      <div className="ai-investigation-panel" style={{ borderTop: "1px solid var(--border-color)", paddingTop: "16px" }}>
                        <h4 className="inv-section-title ai">
                          AI Agent Investigation Report (Non-Authoritative)
                        </h4>

                        {loadingInvestigation && (
                          <div className="loading-overlay">
                            <span className="spinner" />
                            <span>Orchestrating agent investigation tools...</span>
                          </div>
                        )}

                        {investigationError && (
                          <div className="validation-error">
                            {investigationError}
                          </div>
                        )}

                        {investigationReport && (
                          <div className="inv-report-container">
                            <div className="meta-list">
                              <div className="meta-row">
                                <span>Agent Status</span>
                                <span>
                                  <span className={`badge-decision ${investigationReport.status === "AVAILABLE" ? "AUTO_MATCH" : "ABSTAIN"}`}>
                                    {investigationReport.status}
                                  </span>
                                </span>
                              </div>

                              {investigationReport.status === "AVAILABLE" && (
                                <>
                                  <div className="meta-row">
                                    <span>Root Cause Class</span>
                                    <span className="cause-badge">{investigationReport.root_cause || "UNKNOWN"}</span>
                                  </div>
                                  <div className="meta-row">
                                    <span>Agent Confidence</span>
                                    <span className="value-highlight">
                                      {investigationReport.investigation_confidence ? parseFloat(investigationReport.investigation_confidence).toFixed(2) : "N/A"}
                                    </span>
                                  </div>
                                  {investigationReport.violated_rules.length > 0 && (
                                    <div className="meta-row">
                                      <span>Violated Rules</span>
                                      <span>{investigationReport.violated_rules.join(", ")}</span>
                                    </div>
                                  )}
                                </>
                              )}
                            </div>

                            {investigationReport.agent_explanation && (
                              <div style={{ marginTop: "10px" }}>
                                <p style={{ fontSize: "0.75rem", fontWeight: 700, color: "#c084fc", marginBottom: "6px" }}>
                                  Agent Analysis Explanation:
                                </p>
                                <p className="inv-explanation">
                                  {investigationReport.agent_explanation}
                                </p>
                              </div>
                            )}

                            {investigationReport.suggested_actions.length > 0 && (
                              <div style={{ marginTop: "10px" }}>
                                <p style={{ fontSize: "0.75rem", fontWeight: 700, color: "#c084fc", marginBottom: "6px" }}>
                                  Suggested Remediation Actions:
                                </p>
                                <ol className="suggested-actions-list">
                                  {investigationReport.suggested_actions.map((act, idx) => (
                                    <li key={idx}>{act}</li>
                                  ))}
                                </ol>
                              </div>
                            )}
                          </div>
                        )}

                        {!loadingInvestigation && !investigationReport && !investigationError && (
                          <div className="empty-state" style={{ height: "120px", borderStyle: "dashed" }}>
                            <p>Click "Investigate" in the exception queue to trigger LLM root cause analysis.</p>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="empty-state">
                      <div className="empty-state-icon">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round">
                          <circle cx="12" cy="12" r="10" />
                          <line x1="12" y1="16" x2="12" y2="12" />
                          <line x1="12" y1="8" x2="12.01" y2="8" />
                        </svg>
                      </div>
                      <p>Select a payment transaction from the queue list to review its matching details, rule validation trail, and AI agent investigation status.</p>
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
