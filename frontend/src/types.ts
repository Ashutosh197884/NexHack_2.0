// Types mirroring the backend schemas (§8 contracts).
export interface QrSample {
  id: string;
  label: string;
  scenario: "benign" | "suspicious" | "malformed";
  payload: string;
  rationale: string;
}

export interface PaymentData {
  payee_vpa: string | null;
  payee_name: string | null;
  amount: number | null;
  currency: string | null;
  reference: string | null;
  note: string | null;
}

export interface QrAnalyzeResponse {
  valid: boolean;
  payment_data: PaymentData;
  qrid: string | null;
  errors: string[];
  warnings: string[];
  flags: Record<string, boolean>;
}

export interface Reason {
  code: string;
  severity: string;
  message: string;
  contribution?: number | null;
}

export interface RiskAssessResponse {
  assessment_id: string;
  transaction_id: string;
  payee_vpa: string;
  payee_name: string | null;
  amount: number;
  currency: string;
  risk_score: number;
  risk_level: "low" | "medium" | "high";
  action: "approve" | "step_up" | "block";
  reasons: Reason[];
  recommendation: string;
  probability: number;
  profile_deviation: number;
  transactional_signals: Record<string, unknown>;
  next_step_hint: string;
  is_simulated: boolean;
}

export interface SimulateResponse {
  transaction_id: string;
  status: string;
  message: string;
}

export interface TransactionOut {
  id: string;
  payee_vpa: string;
  payee_name: string | null;
  amount: number;
  currency: string;
  transaction_time: string;
  risk_score: number | null;
  risk_level: string | null;
  status: string;
  simulated_at: string | null;
}

export interface DashboardSummary {
  analyzed: number;
  cancelled: number;
  simulated_success: number;
  simulated_failure: number;
  risk_levels: Record<string, number>;
  top_reason_codes: { code: string; count: number }[];
  recent: TransactionOut[];
}

export interface HealthInfo {
  ok: boolean;
  service: string;
  environment: string;
  ml_ok: boolean;
  model_available: boolean;
}

export interface ApiError {
  error: string;
}
