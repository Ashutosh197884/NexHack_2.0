import { useState } from "react";
import { api } from "../../services/api";
import type { QrAnalyzeResponse, RiskAssessResponse } from "../../types";
import { formatINR } from "../../services/util";

interface Props {
  payload: string;
  analyzed: QrAnalyzeResponse;
  onAssessed(result: RiskAssessResponse): void;
  onBack(): void;
}

export default function ReviewScreen({ payload, analyzed, onAssessed, onBack }: Props) {
  const pd = analyzed.payment_data;
  const hasAmount = pd.amount != null;
  const [amount, setAmount] = useState(pd.amount != null ? String(pd.amount) : "");
  const [intended, setIntended] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function assess() {
    const amt = parseFloat(amount);
    if (!(amt > 0)) {
      setError("Enter the amount you intend to pay.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api<RiskAssessResponse>("POST", "/risk/assess", {
        payee_vpa: pd.payee_vpa,
        payee_name: pd.payee_name ?? undefined,
        amount: amt,
        currency: pd.currency ?? "INR",
        qr_payload: payload,
        intended_recipient: intended.trim() ? intended.trim() : undefined,
      });
      onAssessed(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-800">2 · Review payment</h2>

      {analyzed.valid ? (
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-slate-500">Payee VPA</dt>
          <dd className="font-mono font-medium text-slate-800">{pd.payee_vpa}</dd>
          <dt className="text-slate-500">Payee name</dt>
          <dd className="text-slate-800">{pd.payee_name ?? "—"}</dd>
          <dt className="text-slate-500">QR amount</dt>
          <dd className="text-slate-800">{hasAmount ? formatINR(pd.amount!) : "not embedded"}</dd>
          {pd.reference && (
            <>
              <dt className="text-slate-500">Reference</dt>
              <dd className="font-mono text-slate-800">{pd.reference}</dd>
            </>
          )}
          {pd.note && (
            <>
              <dt className="text-slate-500">Note</dt>
              <dd className="text-slate-800">{pd.note}</dd>
            </>
          )}
        </dl>
      ) : (
        <>
          <p className="mt-3 rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">
            This QR is <b>not a valid UPI payment QR</b> — it will never be
            treated as a pay-able payment.
          </p>
          <ul className="mt-2 list-inside list-disc text-sm text-rose-700">
            {analyzed.errors.map((e) => (
              <li key={e} className="font-mono">{e}</li>
            ))}
          </ul>
        </>
      )}

      {analyzed.warnings.length > 0 && (
        <ul className="mt-3 grid gap-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          {analyzed.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}

      {analyzed.valid && (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">
                Amount to pay {hasAmount && "(from QR)"}
              </span>
              <input
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 p-2 focus:border-sky-500 focus:outline-none"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">
                Who you meant to pay <i>(optional)</i>
              </span>
              <input
                value={intended}
                onChange={(e) => setIntended(e.target.value)}
                placeholder="someone@upi"
                className="mt-1 w-full rounded-lg border border-slate-300 p-2 focus:border-sky-500 focus:outline-none"
              />
            </label>
          </div>

          {error && (
            <p className="mt-3 rounded border border-rose-300 bg-rose-50 p-2 text-sm text-rose-700">
              {error}
            </p>
          )}

          <div className="mt-5 flex gap-3">
            <button
              onClick={assess}
              disabled={busy}
              className="flex-1 rounded-lg bg-sky-600 px-4 py-2.5 font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {busy ? "Analyzing risk…" : "Analyze risk →"}
            </button>
            <button
              onClick={onBack}
              className="rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Scan different QR
            </button>
          </div>
        </>
      )}
    </div>
  );
}
