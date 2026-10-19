import { useEffect, useState } from "react";
import { api } from "../../services/api";
import type { DashboardSummary, TransactionOut } from "../../types";
import { formatINR, hhmm, levelColor } from "../../services/util";

export default function HistoryScreen() {
  const [txns, setTxns] = useState<TransactionOut[] | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<TransactionOut[]>("GET", "/transactions"),
      api<DashboardSummary>("GET", "/dashboard/summary"),
    ])
      .then(([t, s]) => {
        setTxns(t);
        setSummary(s);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="text-sm text-rose-700">{err}</p>;
  if (!txns || !summary) return <p className="text-sm text-slate-500">Loading…</p>;

  const counts = summary.risk_levels;

  return (
    <div className="grid gap-5">
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Simulated ✓" value={summary.simulated_success} tone="emerald" />
        <Stat label="Simulated (blocked)" value={summary.simulated_failure} tone="rose" />
        <Stat label="Cancelled" value={summary.cancelled} tone="slate" />
        <Stat label="Awaiting decision" value={summary.analyzed} tone="sky" />
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-800">Risk distribution</h2>
        <div className="mt-3 flex flex-wrap gap-3">
          <Bar label="Low" n={counts.low ?? 0} cls="bg-emerald-500" total={txns.length} />
          <Bar label="Medium" n={counts.medium ?? 0} cls="bg-amber-500" total={txns.length} />
          <Bar label="High" n={counts.high ?? 0} cls="bg-rose-500" total={txns.length} />
        </div>
        {summary.top_reason_codes.length > 0 && (
          <div className="mt-4 text-sm text-slate-600">
            <b>Top risk reasons:</b>{" "}
            {summary.top_reason_codes.map((c) => `${c.code}×${c.count}`).join(", ")}
          </div>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-200 p-4 text-lg font-semibold text-slate-800">
          Transaction history
        </h2>
        <ul>
          {txns.map((t) => (
            <li
              key={t.id}
              className="flex flex-wrap items-center gap-3 border-b border-slate-100 p-3 last:border-0"
            >
              <span className="font-mono text-sm text-slate-800">{t.payee_vpa}</span>
              <span className="text-sm font-medium text-slate-700">
                {formatINR(t.amount)}
              </span>
              {t.risk_level && (
                <span
                  className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase ${levelColor(t.risk_level)}`}
                >
                  {t.risk_level} {t.risk_score}
                </span>
              )}
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                {t.status}
              </span>
              <span className="ml-auto text-xs text-slate-400">
                {hhmm(t.transaction_time)}
              </span>
            </li>
          ))}
          {txns.length === 0 && (
            <li className="p-6 text-center text-sm text-slate-500">
              No payments analyzed yet — scan a QR.
            </li>
          )}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  const tones: Record<string, string> = {
    emerald: "text-emerald-700 border-emerald-200 bg-emerald-50",
    rose: "text-rose-700 border-rose-200 bg-rose-50",
    slate: "text-slate-700 border-slate-200 bg-slate-50",
    sky: "text-sky-700 border-sky-200 bg-sky-50",
  };
  return (
    <div className={`rounded-xl border p-4 ${tones[tone]}`}>
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-xs font-medium opacity-80">{label}</div>
    </div>
  );
}

function Bar({ label, n, cls, total }: { label: string; n: number; cls: string; total: number }) {
  const pct = total ? Math.round((n / total) * 100) : 0;
  return (
    <div className="min-w-[110px] flex-1">
      <div className="h-2 rounded bg-slate-200">
        <div className={`h-2 rounded ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-xs text-slate-600">
        {label}: {n} ({pct}%)
      </div>
    </div>
  );
}
