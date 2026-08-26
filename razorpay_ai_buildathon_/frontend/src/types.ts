// LedgerLens Type Definitions

export interface Merchant {
  merchant_id: string;
  name: string;
  city: string;
  settlement_tier: "T1" | "T2" | "T3";
  settlement_cycle_days: number;
  fee_rate: string; // Decimal
  currency: string;
}

export interface Payment {
  payment_id: string;
  merchant_id: string;
  amount: string; // Decimal
  currency: string;
  payment_date: string; // YYYY-MM-DD
  gateway_ref: string;
  status: "CAPTURED" | "REFUNDED" | "FAILED";
}

export interface Settlement {
  settlement_id: string;
  merchant_id: string;
  payment_ids: string[];
  settlement_date: string; // YYYY-MM-DD
  gross_amount: string; // Decimal
  fee_amount: string; // Decimal
  net_amount: string; // Decimal
  settlement_ref: string;
  status: "INITIATED" | "PROCESSED" | "FAILED";
}

export interface BankEntry {
  bank_entry_id: string;
  merchant_id: string;
  settlement_ref: string;
  credit_amount: string; // Decimal
  value_date: string; // YYYY-MM-DD
  bank_ref: string;
  narration: string;
}

export interface LedgerEntry {
  ledger_entry_id: string;
  merchant_id: string;
  payment_id: string;
  settlement_id: string;
  bank_entry_id: string;
  allocated_amount: string; // Decimal
  posting_date: string; // YYYY-MM-DD
  account_code: string;
  status: "DRAFT" | "POSTED" | "RECONCILED";
  reconciled_flag: boolean;
}

export interface ReconciliationRunRequest {
  merchants: Merchant[];
  payments: Payment[];
  settlements: Settlement[];
  bank_entries: BankEntry[];
  ledger_entries: LedgerEntry[];
  batch_id?: string;
}

export interface MatchEvidence {
  rule_id: string;
  rule_description: string;
  matched: boolean;
  field_name: string;
  expected_value: string | null;
  observed_value: string | null;
  score_contribution: string; // Decimal
}

export interface ValidationFinding {
  rule_id: string;
  rule_description: string;
  passed: boolean;
  severity: "INFO" | "WARNING" | "ERROR";
  expected_relationship: string;
  observed_relationship: string;
  delta: string | null;
  affected_record_ids: string[];
  discrepancy_code: string | null;
}

export interface EvidenceCard {
  audit_id: string;
  payment_id: string;
  decision: "AUTO_MATCH" | "HUMAN_REVIEW" | "ABSTAIN";
  confidence: string; // Decimal
  matched_settlement_id: string | null;
  matched_bank_entry_id: string | null;
  matched_ledger_entry_id: string | null;
  evidence: MatchEvidence[];
  rules_triggered: string[];
  stage_reached: "exact" | "composite" | "no_match";
  discrepancy_codes: string[];
  notes: string;
  amount_delta: string | null; // Decimal
  date_delta_days: number | null;
  fee_delta: string | null; // Decimal
  alternative_candidate_ids: string[];
  validation_findings: ValidationFinding[];
  processed_at: string; // datetime ISO
}

export interface ReconciliationDecision {
  payment_id: string;
  decision: "AUTO_MATCH" | "HUMAN_REVIEW" | "ABSTAIN";
  confidence: string; // Decimal
  exception_codes: string[];
  audit_id: string;
}

export interface OrphanRecord {
  orphan_id: string;
  entity_type: "bank_entry" | "settlement" | "ledger_entry";
  entity_id: string;
  unmatched_ref: string;
  exception_code: string;
  notes: string;
}

export interface BatchReconciliationResult {
  batch_id: string;
  total_records: number;
  auto_matched: number;
  human_review: number;
  abstained: number;
  decisions: ReconciliationDecision[];
  evidence_cards: EvidenceCard[];
  orphan_records: OrphanRecord[];
  match_rate: string; // Decimal
  exception_rate: string; // Decimal
  processed_at: string; // datetime ISO
}

export interface ExceptionRecord {
  payment_id: string;
  exception_code: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  message: string;
  timestamp: string; // datetime ISO
  evidence_summary: string;
}

export interface ReconciliationRunResponse {
  reconciliation_result: BatchReconciliationResult;
  exceptions: ExceptionRecord[];
}

export interface InvestigationRunRequest extends ReconciliationRunRequest {
  target_payment_id: string;
}

export interface InvestigationReport {
  payment_id: string;
  batch_id: string;
  status: "AVAILABLE" | "UNAVAILABLE" | "INVALID_OUTPUT";
  reconciliation_confidence: string; // Decimal
  investigation_confidence: string | null; // Decimal
  agent_explanation: string | null;
  suggested_actions: string[];
  root_cause:
    | "AMOUNT_MISMATCH"
    | "DATE_WINDOW_VIOLATION"
    | "DUPLICATE_TRANSACTION"
    | "MISSING_RECORD"
    | "FEE_CONTRACT_VARIANCE"
    | "ORPHAN_RECORD"
    | "UNKNOWN"
    | null;
  violated_rules: string[];
}

export interface InvestigationRunResponse {
  deterministic_reconciliation: BatchReconciliationResult;
  exceptions: ExceptionRecord[];
  investigation_report: InvestigationReport;
}
