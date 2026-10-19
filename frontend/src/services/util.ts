import type { QrSample } from "../types";

export function formatINR(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function levelColor(level: string): string {
  switch (level) {
    case "low":
      return "bg-emerald-100 text-emerald-800 border-emerald-300";
    case "medium":
      return "bg-amber-100 text-amber-800 border-amber-300";
    case "high":
      return "bg-rose-100 text-rose-800 border-rose-300";
    default:
      return "bg-slate-100 text-slate-700 border-slate-300";
  }
}

export function scoreGradient(score: number): string {
  // 0 → emerald, mid → amber, 100 → rose (bar fill, not text-only signal)
  const hue = 145 - (score / 100) * 125;
  return `hsl(${hue} 70% 45%)`;
}

export function scenarioBadge(scenario: QrSample["scenario"]): string {
  switch (scenario) {
    case "benign":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "suspicious":
      return "bg-amber-50 text-amber-700 border-amber-200";
    case "malformed":
      return "bg-rose-50 text-rose-700 border-rose-200";
  }
}

/** Time formatting with locale fallback. */
export function hhmm(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleTimeString();
}
