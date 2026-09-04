"""
SecureUPI — PSP/Bank operations store (demo).

Holds the *bank-side* view of every payment the phone demo produces:
one transaction per payment attempt with its SecureUPI assessment rounds
(initial + step-up), a bank lifecycle state, and an audit trail of what the
risk operator did with it.

Bank-side states:
    approved         — SecureUPI approved (or step-up round cleared)
    step_up          — issued, awaiting/executing step-up round
    blocked          — final block (needs bank review or customer report)
    fraud_reported   — blocked + confirmed as fraud (report id issued)
    overridden       — blocked but the PSP overrode & approved (with note)

The panel also supports a deterministic SAMPLE BANK DAY (clearly labelled
source='sample') so the console looks alive before the live demo runs.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
import uuid
from pathlib import Path

from risk_engine import RiskEngine

DATA_DIR = Path(__file__).resolve().parent / "data"
BANK_FILE = DATA_DIR / "bank_tx.jsonl"

LOCK = threading.Lock()

OPERATOR = "Rita · Risk Ops"
SAMPLE_SEED = 20260904
DEFAULT_CUSTOMER = {"name": "Aarav Sharma", "bank": "XYZ Bank", "device": "Pixel 8 · Android 15"}

_ORDER: list[str] = []   # insertion order of tx ids
_TX: dict[str, dict] = {}


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

def _flush() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(BANK_FILE, "w", encoding="utf-8") as fh:
            for tid in _ORDER:
                fh.write(json.dumps(_TX[tid]) + "\n")
    except OSError:
        pass


def load() -> None:
    global _ORDER, _TX
    rows = []
    try:
        with open(BANK_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        rows = []
    _TX = {r["id"]: r for r in rows}
    _ORDER = [r["id"] for r in rows]


def all_tx(limit: int = 200) -> list[dict]:
    return [_TX[i] for i in _ORDER[-limit:]][::-1]


def _tx_id(session_id: str) -> str:
    h = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:8].upper()
    return f"TXN-{h}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------
# mock NPCI/UPI switch (settlement leg)
# --------------------------------------------------------------------------

def _utr(tx_id: str) -> str:
    """Deterministic, realistic-looking 12-char UTR (N + 11 digits)."""
    h = int(hashlib.sha1((tx_id + "::utr").encode("utf-8")).hexdigest()[:10], 16)
    return "N" + f"{h % 10 ** 11:011d}"


def _latency_ms(tx_id: str) -> int:
    h = int(hashlib.sha1((tx_id + "::lat").encode("utf-8")).hexdigest()[:6], 16)
    return 140 + h % 280  # mock NPCI round-trip 140-420 ms


def _set_switch(tx: dict, force: bool = False) -> None:
    """Finalise the UPI-switch leg whenever the PSP state resolves."""
    if not force and tx.get("switch") and tx["switch"].get("status") in ("settled", "not_reached"):
        return  # already final
    if tx["state"] in ("approved", "overridden"):
        tx["switch"] = {
            "status": "settled",
            "rail": "UPI (NPCI)",
            "utr": _utr(tx["id"]),
            "ts": _now(),
            "latency_ms": _latency_ms(tx["id"]),
        }
    elif tx["state"] in ("blocked", "fraud_reported"):
        tx["switch"] = {
            "status": "not_reached",
            "rail": "UPI (NPCI)",
            "ts": _now(),
            "reason": "pre-authorization block — never sent to the switch",
        }
    else:  # still under risk review (step-up pending)
        tx["switch"] = {"status": "in_review", "rail": "UPI (NPCI)"}


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------

def _initial_state(action: str) -> str:
    return {"APPROVE": "approved", "STEP-UP": "step_up", "BLOCK": "blocked"}.get(action, "step_up")


def record_round(payload: dict, result: dict) -> dict:
    """Upsert a bank transaction for an assessment round (initial or challenge)."""
    ctx = payload.get("context", {})
    customer = payload.get("customer") or DEFAULT_CUSTOMER
    session_id = payload.get("session_id") or uuid.uuid4().hex
    step = payload.get("step", "initial")
    tid = _tx_id(session_id)

    round_ = {
        "step": step,
        "ts": _now(),
        "risk_score": result["risk_score"],
        "level": result["level"],
        "action": result["action"],
        "deviation": result["profile_deviation"],
        "contributors": result["top_contributors"][:5],
        "policy": result["policy"],
        "signals": payload.get("signals", {}),
    }

    with LOCK:
        if tid not in _TX:
            tx = {
                "id": tid,
                "session_id": session_id,
                "source": "live",
                "customer": {
                    "name": customer.get("name", DEFAULT_CUSTOMER["name"]),
                    "bank": customer.get("bank", DEFAULT_CUSTOMER["bank"]),
                    "device": customer.get("device", DEFAULT_CUSTOMER["device"]),
                },
                "merchant": ctx.get("payee_name", ""),
                "payee": ctx.get("payee", "unknown@upi"),
                "amount": round(float(ctx.get("amount", 0.0)), 2),
                "created_ts": _now(),
                "rounds": [],
                "state": "step_up",
                "audit": [],
                "report_id": None,
            }
            _TX[tid] = tx
            _ORDER.append(tid)
        else:
            tx = _TX[tid]

        tx["rounds"].append(round_)
        if step == "challenge" or len(tx["rounds"]) == 1:
            tx["state"] = _initial_state(result["action"])
            # a block from the step-up round is a candidate for a fraud report
            if step == "challenge" and result["action"] == "BLOCK":
                tx["state"] = "blocked"
        _set_switch(tx)
        _flush()
        return tx


def find_by_session(session_id: str) -> dict | None:
    tid = _tx_id(session_id)
    with LOCK:
        return _TX.get(tid)


def bank_action(txn_id: str, action: str, note: str = "") -> dict | None:
    """Operator actions on a blocked transaction."""
    with LOCK:
        tx = _TX.get(txn_id)
        if not tx:
            return None
        if action == "confirm_fraud":
            tx["state"] = "fraud_reported"
            tx["report_id"] = tx.get("report_id") or "FR-" + uuid.uuid4().hex[:6].upper()
        elif action == "override_approve":
            tx["state"] = "overridden"
            tx["switch"] = None  # a pre-auth block is lifted: payment now proceeds to NPCI
        else:
            return tx
        tx["audit"].append({
            "ts": _now(),
            "operator": OPERATOR,
            "action": action,
            "note": note,
        })
        _set_switch(tx, force=(action == "override_approve"))
        _flush()
        return tx


def customer_report(session_id: str) -> dict | None:
    """The customer's in-app 'Report to bank' on a blocked payment."""
    with LOCK:
        tx = _TX.get(_tx_id(session_id))
        if not tx:
            return None
        tx["state"] = "fraud_reported"
        tx["report_id"] = tx.get("report_id") or "FR-" + uuid.uuid4().hex[:6].upper()
        tx["audit"].append({
            "ts": _now(),
            "operator": "Customer app (Aarav)",
            "action": "customer_report",
            "note": "Reported from the UPI app after the block",
        })
        _set_switch(tx)
        _flush()
        return tx


# --------------------------------------------------------------------------
# sample bank day (deterministic, clearly labelled source='sample')
# --------------------------------------------------------------------------

def load_sample() -> int:
    engine = RiskEngine()
    rng = random.Random(SAMPLE_SEED)
    now_ts = time.time()
    rows = []

    def sess(amount, new_payee, fill, corr, apause, dwell, cps, ppause,
             resets, hold, offset, ss, ig):
        return {
            "amount": amount, "new_payee": new_payee,
            "amount_fill_s": fill, "amount_corrections": corr,
            "amount_max_pause_s": apause, "pay_dwell_s": dwell,
            "pin_cps": cps, "pin_max_pause_s": ppause, "pin_resets": resets,
            "pin_hold_std_ms": hold, "pin_tap_offset_px": offset,
            "screen_share": ss, "integrity_fail": ig,
        }

    customers = [
        ("Priya Nair", "HDFC Bank", "Pixel 7a · Android 14"),
        ("Ramesh Gupta", "State Bank of India", "Redmi Note 12 · Android 13"),
        ("Sneha Iyer", "ICICI Bank", "iPhone 15 · iOS 17"),
        ("Kiran Rao", "Kotak Mahindra", "Samsung M34 · Android 14"),
        ("Meena Pillai", "Canara Bank", "iPhone 13 · iOS 16"),
        ("Arjun Mehta", "Axis Bank", "OnePlus Nord · Android 14"),
        ("Farida Khan", "HDFC Bank", "Pixel 6a · Android 13"),
        ("Dev Sharma", "IDFC First Bank", "Nothing Phone 2 · Android 14"),
    ]

    # (merchant, vpa, amount, minutes_ago, kind)
    plan = [
        ("Coffee House", "coffeehouse@upi", 250, 118, "ok"),
        ("Kirana Store", "kirana.store@upi", 460, 112, "ok"),
        ("BigBasket", "bigbasket@ybl", 1845, 104, "ok"),
        ("Priya Sharma", "savings@okhdfcbank", 450, 97, "ok"),
        ("Jio Recharge", "recharge@jio", 299, 88, "ok"),
        ("Urban Nidhi Finance", "urbannidhi@icici", 45000, 76, "stepup"),
        ("Electricity Board", "electricity@ybl", 2320, 61, "ok"),
        ("Apollo Pharmacy", "apollo@okaxis", 640, 55, "ok"),
        ("Cash Back Office", "cashback.office@hdfcbank", 35000, 43, "fraud"),
        ("RBI Refund Desk", "refund.verify@icici", 50000, 31, "fraud"),
        ("Swiggy", "swiggy@ybl", 380, 24, "ok"),
        ("Sharma Ji Rent", "rent@okhdfcbank", 12000, 18, "ok"),
        ("VIP Tours", "viptours@icici", 28000, 9, "stepup"),
        ("Tax Recovery Cell", "tax.recovery@sbi", 45000, 4, "blocked"),
    ]

    kind_to_vector = {
        # calm everyday payment
        "ok": lambda a, np: sess(a, np, 2.0, 0, 0.4, 1.0, 3.3, 0.4, 0, 35, 3.0, 0, 0),
        # calm big transfer to a new payee (step-up expected)
        "stepup": lambda a, np: sess(a, 1, 2.9, 0, 0.6, 1.5, 3.0, 0.5, 0, 36, 3.1, 0, 0),
        # screenshare-style scam (block expected)
        "fraud": lambda a, np: sess(a, 1, 13.0, 4, 5.5, 5.0, 1.0, 3.2, 1, 170, 12.0, 1, 0),
        # duress-style scam (block expected)
        "blocked": lambda a, np: sess(a, 1, 8.5, 3, 3.2, 2.0, 1.3, 2.4, 1, 150, 15.0, 0, 0),
    }

    calm_challenge = sess(1, 0, 2.2, 0, 0.5, 0.9, 3.2, 0.4, 0, 36, 3.0, 0, 0)
    fraud_challenge = sess(1, 0, 8.0, 2, 3.0, 1.0, 1.2, 2.2, 1, 160, 12.0, 1, 0)   # still sharing screen
    duress_challenge = sess(1, 0, 7.0, 2, 2.6, 1.0, 1.3, 2.0, 1, 190, 16.0, 0, 0)  # no screen share, tremor

    for i, (merchant, vpa, amount, mins_ago, kind) in enumerate(plan):
        customer = customers[i % len(customers)]
        vector = kind_to_vector[kind](amount, 0)
        res = engine.evaluate(dict(vector), amount=amount)
        rng.random()  # keep stream deterministic across future edits

        created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts - mins_ago * 60))
        rounds = [{
            "step": "initial", "ts": created,
            "risk_score": res["risk_score"], "level": res["level"],
            "action": res["action"], "deviation": res["profile_deviation"],
            "contributors": res["top_contributors"][:5],
            "policy": res["policy"], "signals": {k: v for k, v in vector.items()
                                                 if k not in ("amount", "amount_log")},
        }]
        state = _initial_state(res["action"])
        report_id = None
        audit = []

        if kind in ("fraud", "blocked") and res["action"] == "STEP-UP":
            chal = fraud_challenge if kind == "fraud" else duress_challenge
            res2 = engine.evaluate(dict(chal), step="challenge", amount=amount)
            rounds.append({
                "step": "challenge",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts - (mins_ago - 1) * 60)),
                "risk_score": res2["risk_score"], "level": res2["level"],
                "action": res2["action"], "deviation": res2["profile_deviation"],
                "contributors": res2["top_contributors"][:5],
                "policy": res2["policy"], "signals": {},
            })
            state = "blocked"
            if kind == "fraud":
                state = "fraud_reported"
                report_id = "FR-" + uuid.UUID(int=rng.getrandbits(128)).hex[:6].upper()
                audit.append({"ts": rounds[-1]["ts"], "operator": OPERATOR,
                              "action": "confirm_fraud",
                              "note": "Screen-share active + dictated entry — fraud confirmed"})
        elif kind == "stepup" and res["action"] == "STEP-UP":
            res2 = engine.evaluate(dict(calm_challenge), step="challenge", amount=amount)
            rounds.append({
                "step": "challenge",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts - (mins_ago - 1) * 60)),
                "risk_score": res2["risk_score"], "level": res2["level"],
                "action": res2["action"], "deviation": res2["profile_deviation"],
                "contributors": res2["top_contributors"][:5],
                "policy": res2["policy"], "signals": {},
            })
            state = "approved"

        tx = {
            "id": "SMP-" + uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper(),
            "session_id": "sample-" + uuid.UUID(int=rng.getrandbits(128)).hex[:8],
            "source": "sample",
            "customer": {"name": customer[0], "bank": customer[1], "device": customer[2]},
            "merchant": merchant, "payee": vpa,
            "amount": float(amount),
            "created_ts": created,
            "rounds": rounds,
            "state": state,
            "audit": audit,
            "report_id": report_id,
        }
        _set_switch(tx)
        rows.append(tx)

    with LOCK:
        # replace existing sample rows
        global _ORDER, _TX
        kept = [tid for tid in _ORDER if _TX[tid]["source"] != "sample"]
        _ORDER = kept
        _TX = {tid: _TX[tid] for tid in kept}
        for tx in rows:
            _TX[tx["id"]] = tx
            _ORDER.append(tx["id"])
        _flush()
        return len(rows)


def clear_sample() -> int:
    with LOCK:
        kept = [tid for tid in _ORDER if _TX[tid]["source"] != "sample"]
        removed = len(_ORDER) - len(kept)
        global _TX
        _ORDER[:] = kept
        _TX = {tid: _TX[tid] for tid in kept}
        _flush()
        return removed
