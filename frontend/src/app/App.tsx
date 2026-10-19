import { useEffect, useState } from "react";
import ScannerScreen from "../features/qr-scanner/ScannerScreen";
import ReviewScreen from "../features/payment-review/ReviewScreen";
import ResultScreen from "../features/risk-assessment/ResultScreen";
import HistoryScreen from "../features/dashboard/HistoryScreen";
import { api, getToken, setToken, ApiHttpError } from "../services/api";
import type {
  HealthInfo,
  QrAnalyzeResponse,
  RiskAssessResponse,
} from "../types";

type Phase = "scan" | "review" | "result" | "history";

export default function App() {
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [phase, setPhase] = useState<Phase>("scan");
  const [payload, setPayload] = useState<string | null>(null);
  const [analyzed, setAnalyzed] = useState<QrAnalyzeResponse | null>(null);
  const [assessment, setAssessment] = useState<RiskAssessResponse | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [authErr, setAuthErr] = useState<string | null>(null);

  useEffect(() => {
    api<HealthInfo>("GET", "/health").then(setHealth).catch(() => {});
  }, [authed]);

  async function handlePayload(p: string) {
    const a = await api<QrAnalyzeResponse>("POST", "/qr/analyze", {
      qr_payload: p,
    });
    setPayload(p);
    setAnalyzed(a);
    setPhase("review");
  }

  function onAssessed(result: RiskAssessResponse) {
    setAssessment(result);
    setPhase("result");
  }

  function reset() {
    setPayload(null);
    setAnalyzed(null);
    setAssessment(null);
    setPhase("scan");
  }

  async function login(email: string, password: string) {
    setAuthErr(null);
    try {
      const t = await api<{ access_token: string }>("POST", "/auth/login", {
        email,
        password,
      });
      setToken(t.access_token);
      setAuthed(true);
      setPhase("scan");
    } catch (e) {
      const msg =
        e instanceof ApiHttpError && e.status === 401
          ? "Invalid email or password."
          : "Login failed — is the backend running?";
      setAuthErr(msg);
    }
  }

  function logout() {
    setToken(null);
    setAuthed(false);
    setPhase("scan");
  }

  if (!authed) return <LoginScreen onSubmit={login} error={authErr} health={health} />;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between p-4">
          <div>
            <h1 className="text-xl font-bold text-slate-800">
              Secure<span className="text-sky-600">UPI</span>
            </h1>
            <p className="text-xs text-slate-500">
              Scan. Analyze. Verify. Pay safely. — AI risk layer around UPI
            </p>
          </div>
          <nav className="flex items-center gap-2 text-sm">
            <button
              onClick={() => setPhase("scan")}
              className={navClass(phase === "scan")}
            >
              Scan QR
            </button>
            <button
              onClick={() => setPhase("history")}
              className={navClass(phase === "history")}
            >
              History
            </button>
            <span className="hidden rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800 sm:inline">
              {health?.ml_ok ? "model live" : "rules-only mode"}
            </span>
            <button
              onClick={logout}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-slate-50"
            >
              Sign out
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-4xl p-6">
        {phase === "scan" && (
          <ScannerScreen onPayload={handlePayload} />
        )}
        {phase === "review" && payload && analyzed && (
          <ReviewScreen
            payload={payload}
            analyzed={analyzed}
            onAssessed={onAssessed}
            onBack={reset}
          />
        )}
        {phase === "result" && assessment && (
          <ResultScreen
            result={assessment}
            onDone={() => setPhase("history")}
            onScannedAgain={reset}
          />
        )}
        {phase === "history" && <HistoryScreen />}
      </main>

      <footer className="border-t border-slate-200 bg-white py-3 text-center text-xs text-slate-500">
        Prototype only — every payment is <b>simulated</b>; no real money ever
        moves and UPI PINs are never collected.
      </footer>
    </div>
  );
}

function navClass(active: boolean) {
  return active
    ? "rounded-lg bg-sky-600 px-3 py-1.5 font-medium text-white"
    : "rounded-lg border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-slate-50";
}

function LoginScreen({
  onSubmit,
  error,
  health,
}: {
  onSubmit(email: string, password: string): void;
  error: string | null;
  health: HealthInfo | null;
}) {
  const [email, setEmail] = useState("demo@secureupi.app");
  const [password, setPassword] = useState("");
  const [registering, setRegistering] = useState(false);
  const [name, setName] = useState("");
  const [localErr, setLocalErr] = useState<string | null>(null);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <div className="w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-2xl font-bold text-slate-800">
          Secure<span className="text-sky-600">UPI</span>
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          AI-powered UPI payment risk. Demo accounts — password{" "}
          <code className="rounded bg-slate-100 px-1">secureupi-demo</code>:
        </p>
        <ul className="mt-2 text-xs text-slate-500">
          <li>demo@secureupi.app · senior@secureupi.app</li>
        </ul>
        <form
          className="mt-4 grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (registering) {
              void (async () => {
                setLocalErr(null);
                try {
                  await api("POST", "/auth/register", {
                    name: name || "New User",
                    email,
                    password,
                  });
                } catch (ee) {
                  setLocalErr(String(ee));
                  return;
                }
                onSubmit(email, password);
              })();
            } else {
              onSubmit(email, password);
            }
          }}
        >
          {registering && (
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Your name"
              className="rounded-lg border border-slate-300 p-2 focus:border-sky-500 focus:outline-none"
            />
          )}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-lg border border-slate-300 p-2 focus:border-sky-500 focus:outline-none"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={registering ? "min 8 chars" : "password"}
            className="rounded-lg border border-slate-300 p-2 focus:border-sky-500 focus:outline-none"
          />
          <button
            type="submit"
            className="rounded-lg bg-sky-600 p-2.5 font-medium text-white hover:bg-sky-700"
          >
            {registering ? "Create account & sign in" : "Sign in"}
          </button>
        </form>
        <button
          onClick={() => setRegistering((r) => !r)}
          className="mt-3 text-sm text-sky-600 hover:underline"
        >
          {registering ? "Back to sign in" : "New here? Create an account"}
        </button>
        {(error || localErr) && (
          <p className="mt-2 text-sm text-rose-700">{error ?? localErr}</p>
        )}
        {health && !health.ok && (
          <p className="mt-2 text-xs text-amber-700">
            Backend says NOT ok — check `backend/README.md`.
          </p>
        )}
      </div>
    </div>
  );
}
