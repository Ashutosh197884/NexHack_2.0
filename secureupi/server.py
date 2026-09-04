"""
SecureUPI — demo server (Python standard library only, no pip installs).

Serves:
  • the demo web UI  (GET  /)
  • risk assessment  (POST /api/v1/assess)
  • risk-event log   (GET  /api/v1/events, POST /api/v1/events/reset)
  • model card       (GET  /api/v1/model)
  • health           (GET  /api/v1/health)

Run from the secureupi/ directory:
    python server.py [port]        (default 8077)
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bank  # noqa: E402
import ops  # noqa: E402
from risk_engine import RiskEngine, vector_from_payload  # noqa: E402

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
EVENTS_FILE = DATA_DIR / "events.jsonl"

DATA_DIR.mkdir(exist_ok=True)

POLICY = ops.load_policy()
ENGINE = RiskEngine(policy=POLICY)
MODEL = ENGINE.model
PROFILE_TYPICAL_KEYS = ["amount_fill_s", "amount_corrections", "amount_max_pause_s",
                        "pay_dwell_s", "pin_cps", "pin_max_pause_s", "pin_resets",
                        "pin_hold_std_ms", "pin_tap_offset_px"]

# In-memory ring of recent risk events + persistent JSONL append
_lock = threading.Lock()
_events: deque = deque(maxlen=400)


def _append_event(ev: dict) -> None:
    _events.appendleft(ev)
    try:
        with open(EVENTS_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev) + "\n")
    except OSError:
        pass


def _load_persisted(limit: int = 200):
    out = []
    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return out[-limit:][::-1]


def _model_card() -> dict:
    m = MODEL
    metrics = m["metrics"]
    weights = []
    for f in m["features"]:
        w = m["weights"][f["key"]]
        if abs(w) < 1e-4:
            continue
        weights.append({
            "key": f["key"], "label": f["label"], "weight": round(w, 3),
            "direction": f["direction"], "description": f["description"],
        })
    weights.sort(key=lambda x: -abs(x["weight"]))
    return {
        "version": m["version"],
        "trained_at_utc": m["trained_at_utc"],
        "n_train": m["n_train"],
        "n_val": m["n_val"],
        "accuracy": metrics["accuracy"],
        "risk_recall": metrics["risk_recall"],
        "benign_specificity": metrics["benign_specificity"],
        "benign_level_low_share": metrics["benign_level_low_share"],
        "confusion": metrics["confusion"],
        "weights": weights,
        "feature_count": len(m["features"]),
        "benign_profile": {k: round(v, 3) for k, v in m["benign_profile"]["mean"].items()},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "SecureUPI/0.1"

    # -- helpers ---------------------------------------------------------

    def _send(self, code: int, body: bytes | str, ctype: str = "application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj))

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    # -- routing ---------------------------------------------------------

    def do_OPTIONS(self):
        self._send(204, b"")

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/v1/health":
            return self._json({"ok": True, "service": "secureupi-risk-engine", "time": time.time()})
        if path == "/api/v1/model":
            return self._json(_model_card())
        if path == "/api/v1/events":
            with _lock:
                events = list(_events)
            if not events:
                events = _load_persisted()
            return self._json({"events": events})
        if path == "/api/v1/bank/transactions":
            return self._json({"transactions": bank.all_tx()})
        if path == "/api/v1/policy":
            return self._json({"policy": ops.load_policy()})
        if path == "/api/v1/profiles":
            return self._json({"profiles": ops.profiles_overview()})
        if path == "/api/v1/policy/explore":
            q = self._query()
            low = float(q.get("low", POLICY["low_max"]))
            med = float(q.get("med", POLICY["medium_max"]))
            return self._json(ops.explore(low, med))
        if path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        self._serve_static(path)

    def _serve_static(self, path: str):
        if path in ("/", ""):
            rel = WEB_DIR / "index.html"
        elif path == "/bank":
            rel = WEB_DIR / "bank.html"
        else:
            rel = (WEB_DIR / path.lstrip("/")).resolve()
            # no directory traversal
            if not str(rel).startswith(str(WEB_DIR.resolve())):
                return self._json({"error": "forbidden"}, 403)
        if not rel.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(rel.suffix.lower(), "application/octet-stream")
        body = rel.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/v1/assess":
            return self._assess()
        if path == "/api/v1/events/reset":
            with _lock:
                _events.clear()
            try:
                EVENTS_FILE.unlink()
            except OSError:
                pass
            return self._json({"ok": True})
        if path == "/api/v1/policy":
            global POLICY
            body = self._read_json()
            POLICY = ops.save_policy({
                "low_max": float(body.get("low_max", POLICY["low_max"])),
                "medium_max": float(body.get("medium_max", POLICY["medium_max"])),
                "challenge_block_at": float(body.get("challenge_block_at", POLICY["challenge_block_at"])),
                "hard_gate_amount": float(body.get("hard_gate_amount", POLICY["hard_gate_amount"])),
            })
            ENGINE.set_policy(POLICY)
            return self._json({"ok": True, "policy": POLICY})
        if path == "/api/v1/bank/actions":
            body = self._read_json()
            tx = bank.bank_action(body.get("txn_id", ""), body.get("action", ""), body.get("note", ""))
            if not tx:
                return self._json({"error": "transaction not found"}, 404)
            return self._json({"ok": True, "transaction": tx})
        if path == "/api/v1/bank/report":
            body = self._read_json()
            tx = bank.customer_report(body.get("session_id", ""))
            if not tx:
                return self._json({"error": "no live transaction for session"}, 404)
            return self._json({"ok": True, "transaction": tx})
        if path == "/api/v1/bank/load-sample":
            n = bank.load_sample()
            return self._json({"ok": True, "loaded": n})
        if path == "/api/v1/bank/clear-sample":
            n = bank.clear_sample()
            return self._json({"ok": True, "removed": n})
        return self._json({"error": "not found"}, 404)

    def _assess(self):
        payload = self._read_json()
        try:
            vector, amount = vector_from_payload(payload)
            step = payload.get("step", "initial")
            if step not in ("initial", "challenge"):
                step = "initial"
            customer = (payload.get("customer") or {}).get("name", "Aarav Sharma")
            profile = ops.profile_for(customer)
            result = ENGINE.evaluate(vector, step=step, amount=amount, profile=profile)
        except Exception as exc:  # defensive: never 500 on a demo
            return self._json({"error": f"engine error: {exc}"}, 400)

        bank_tx = bank.record_round(payload, result)
        result["bank"] = {"txn_id": bank_tx["id"], "state": bank_tx["state"],
                          "switch": bank_tx.get("switch", {})}
        # personalised "your typical" baselines from the customer's own profile
        result["profile_typical"] = {
            k: round(profile["mean"].get(k, 0.0), 3) for k in PROFILE_TYPICAL_KEYS
        }
        result["profile_name"] = profile.get("name", customer)
        result["profile_n"] = profile.get("n", 0)
        # learn from approved behaviour (the baseline adapts per customer)
        if result["action"] == "APPROVE" and bank_tx["source"] == "live":
            ops.observe_approved(customer, payload.get("signals", {}))

        ctx = payload.get("context", {})
        event = {
            "session_id": payload.get("session_id") or uuid.uuid4().hex[:8],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "payee": ctx.get("payee", "unknown@upi"),
            "amount": round(float(ctx.get("amount", 0.0)), 2),
            "step": step,
            "risk_score": result["risk_score"],
            "level": result["level"],
            "action": result["action"],
            "top_contributor": result["top_contributors"][0]["label"] if result["top_contributors"] else "",
            "profile_deviation": result["profile_deviation"],
        }
        with _lock:
            _append_event(event)
        result["event"] = event
        return self._json(result)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8077
    bank.load()
    ops.ensure_profiles()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"SecureUPI demo server on http://127.0.0.1:{port}")
    print(f"  model v{MODEL['version']} trained {MODEL['trained_at_utc']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
