import { useState } from "react";
import type { SimulateResponse } from "../../types";
import type { RiskAssessResponse } from "../../types";
import { api } from "../../services/api";
import { formatINR, levelColor, scoreGradient } from "../../services/util";

interface Props {
  result: RiskAssessResponse;
  onDone(): void;
  onScannedAgain(): void;
}

const ACTION_LABEL: Record<string, string> = {
  approve: "APPROVE",
  step_up: "STEP-UP",
  block: "BLOCK",
};

export default function ResultScreen({ result, onDone, onScannedAgain }: Props) {
  const [sim, setSim] = useState<SimulateResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function simulate(confirm: boolean) {
    setBusy(true);
    setErr(null);
    try {
      if (!confirm) {
        // cancel flow
        await api("POST", `/transactions/${result.transaction_id}/cancel`);
        setSim({
          transaction_id: result.transaction_id,
          status: "CANCELLED",
          message: "Payment cancelled. Nothing was charged.",
        });
      } else {
        setSim(
          await api<SimulateResponse>(
            "POST",
            `/transactions/${result.transaction_id}/simulate`,
            { user_decision: "confirm" }
          )
        );
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const score = result.risk_score;
  const canSimulate =
    !sim && result.action !== "block" && result.risk_level !== "high";

  return (
    <div className="mx-auto max-w-xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">3 · Risk result</h2>
          <p className="text-sm text-slate-500">
            {formatINR(result.amount)} to{" "}
            <span className="font-mono">{result.payee_vpa}</span>
          </p>
        </div>
        <div className="text-right">
          <div className="text-4xl font-bold" style={{ color: scoreGradient(score) }}>
            {score}
          </div>
          <div className="text-xs text-slate-500">risk score / 100</div>
        </div>
      </div>

      <div className="mt-2 h-2 w-full rounded bg-slate-200">
        <div
          className="h-2 rounded"
          style={{ width: `${score}%`, background: scoreGradient(score) }}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-2 py-0.5 text-sm font-semibold uppercase ${levelColor(result.risk_level)}`}
        >
          {result.risk_level} risk
        </span>
        <span className="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold tracking-wide text-white">
          {ACTION_LABEL[result.action] ?? result.action}
        </span>
        <span className="text-xs text-slate-500">{result.next_step_hint}</span>
      </div>

      <p className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
        {result.recommendation}
      </p>

      <div className="mt-4">
        <h3 className="text-sm font-semibold text-slate-700">Why this score?</h3>
        <ul className="mt-2 grid gap-2">
          {result.reasons.map((r, i) => (
            <li
              key={`${r.code}-${i}`}
              className="rounded-lg border border-slate-200 p-2 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-500">{r.code}</span>
                <span className="text-[10px] font-bold uppercase text-slate-400">
                  {r.severity}
                </span>
              </div>
              <div className="text-slate-800">{r.message}</div>
            </li>
          ))}
          {result.reasons.length === 0 && (
            <li className="text-sm text-slate-500">No elevated risk factors flagged.</li>
          )}
        </ul>
      </div>

      {err && (
        <p className="mt-3 rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
          {err}
        </p>
      )}

      {sim === null && result.action !== "block" && (
        <div className="mt-5 flex gap-3">
          <button
            onClick={() => simulate(false)}
            disabled={busy}
            className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Cancel payment
          </button>
          {canSimulate && (
            <button
              onClick={() => simulate(true)}
              disabled={busy}
              className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {busy ? "Processing…" : "Proceed to (simulated) payment"}
            </button>
          )}
        </div>
      )}

      {sim !== null && (
        <div
          className={`mt-5 rounded-lg border p-4 text-center ${
            sim.status === "SIMULATED_SUCCESS"
              ? "border-emerald-300 bg-emerald-50"
              : "border-slate-300 bg-slate-50"
          }`}
        >
          <div className="text-2xl">
            {sim.status === "SIMULATED_SUCCESS" ? "✅" : "🛑"}
          </div>
          <div className="mt-1 font-semibold text-slate-800">{sim.status}</div>
          <div className="mt-1 text-sm text-slate-600">{sim.message}</div>
        </div>
      )}

      {result.action === "block" && sim === null && (
        <p className="mt-5 rounded-lg border border-rose-300 bg-rose-50 p-3 text-center text-sm font-medium text-rose-800">
          Risk policy would block this payment before authorization — simulation
          is not offered. No money ever moves in SecureUPI's web MVP.
        </p>
      )}

      <div className="mt-5 flex justify-between text-sm">
        <button
          onClick={onScannedAgain}
          className="rounded-lg border border-slate-300 px-4 py-2 font-medium text-slate-700 hover:bg-slate-50"
        >
          Scan another QR
        </button>
        <button
          onClick={onDone}
          className="rounded-lg bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-900"
        >
          View history
        </button>
      </div>
    </div>
  );
}
