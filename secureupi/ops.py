"""
SecureUPI — operations layer for the PSP console.

Three responsibilities:
  1. RISK POLICY  — the LOW/MEDIUM/HIGH score cut-offs and the step-up block
     bar. These are operator-tunable (persisted to data/policy.json) and flow
     straight into every engine.evaluate() call.
  2. CUSTOMER PROFILES — per-customer behavioural baselines (persisted to
     data/profiles.json), seeded from the trained model and updated online as
     a customer's payments are approved. A slow-typing senior gets their OWN
     baseline, so being slow is not automatically "unusual for them".
  3. THRESHOLD EXPLORER — replays the held-out validation snapshot saved in
     the model file to show the false-positive vs catch-rate trade-off for any
     candidate policy.
"""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

from risk_engine import (CONTEXT_FEATURES, DEFAULT_POLICY, FEATURE_KEYS,
                         FLAG_KEYS, load_model, model_probability)

DATA_DIR = Path(__file__).resolve().parent / "data"
POLICY_FILE = DATA_DIR / "policy.json"
PROFILES_FILE = DATA_DIR / "profiles.json"

LOCK = threading.Lock()

# behavioural keys that define a user's typing profile (amount log & flags are
# context/signals, not "how this person types")
BEHAVIOUR_KEYS = [k for k in FEATURE_KEYS
                  if k not in FLAG_KEYS and k not in CONTEXT_FEATURES]

# --------------------------------------------------------------------------
# Risk policy
# --------------------------------------------------------------------------

def load_policy() -> dict:
    try:
        with open(POLICY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        policy = dict(DEFAULT_POLICY)
        policy.update({k: float(v) for k, v in data.items() if k in DEFAULT_POLICY})
        return _clamp_policy(policy)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_POLICY)


def _clamp_policy(p: dict) -> dict:
    low = min(max(p["low_max"], 0.0), 99.0)
    med = min(max(p["medium_max"], low + 1.0), 100.0)
    return {
        "low_max": low,
        "medium_max": med,
        "challenge_block_at": min(max(p["challenge_block_at"], 0.0), 100.0),
        "hard_gate_amount": max(p["hard_gate_amount"], 0.0),
    }


def save_policy(policy: dict) -> dict:
    cleaned = _clamp_policy(policy)
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(POLICY_FILE, "w", encoding="utf-8") as fh:
            json.dump(cleaned, fh, indent=1)
    except OSError:
        pass
    return cleaned


# --------------------------------------------------------------------------
# Customer behavioural profiles
# --------------------------------------------------------------------------

def _seeded_profiles(model: dict) -> dict:
    """Default baselines: the model's global benign profile (fast-ish average
    user) and a hand-tuned SLOW-BUT-SMOOTH senior baseline, so the demo starts
    with two clearly different customer personas."""
    gmean = model["benign_profile"]["mean"]
    gstd = model["benign_profile"]["std"]

    senior_mean = dict(gmean)
    senior_std = dict(gstd)
    senior_tuning = {
        "amount_fill_s": 4.6, "amount_corrections": 0.12, "amount_max_pause_s": 0.95,
        "pay_dwell_s": 2.2, "pin_cps": 2.65, "pin_max_pause_s": 0.6,
        "pin_resets": 0.01, "pin_hold_std_ms": 44.0, "pin_tap_offset_px": 4.1,
    }
    senior_std_tuning = {
        "amount_fill_s": 1.6, "amount_corrections": 0.3, "amount_max_pause_s": 0.5,
        "pay_dwell_s": 0.7, "pin_cps": 0.4, "pin_max_pause_s": 0.35,
        "pin_resets": 0.1, "pin_hold_std_ms": 10.0, "pin_tap_offset_px": 1.1,
    }
    for k in BEHAVIOUR_KEYS:
        senior_mean[k] = senior_tuning.get(k, gmean[k])
        senior_std[k] = senior_std_tuning.get(k, gstd[k])

    def rec(name, mean, std, n):
        # store running stats (n, mean, m2) — update in O(1) per session
        return {
            "name": name,
            "n": n,
            "mean": {k: float(mean[k]) for k in BEHAVIOUR_KEYS},
            "m2": {k: float(std[k]) ** 2 * max(n - 1, 1) for k in BEHAVIOUR_KEYS},
        }

    return {
        "Aarav Sharma": rec("Aarav Sharma", gmean, gstd, 800),
        "Ramesh Gupta": rec("Ramesh Gupta", senior_mean, senior_std, 400),
    }


def _load_profiles() -> dict:
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def ensure_profiles() -> dict:
    with LOCK:
        profiles = _load_profiles()
        if not profiles:
            profiles = _seeded_profiles(load_model())
            _flush_profiles(profiles)
        return profiles


def _flush_profiles(profiles: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as fh:
            json.dump(profiles, fh, indent=1)
    except OSError:
        pass


def profile_for(name: str) -> dict:
    """{mean, std, n} for a customer — falls back to the seeded global baseline."""
    profiles = ensure_profiles()
    rec = profiles.get(name)
    if not rec:
        rec = next((r for r in profiles.values() if r["name"] == name), None)
    if not rec:
        rec = _seeded_profiles(load_model()).get("Aarav Sharma", {})
    return _summarize(rec)


def profile_mean_for(name: str) -> dict:
    return profile_for(name)["mean"]


def _summarize(rec: dict) -> dict:
    n = int(rec["n"])
    mean = {k: float(rec["mean"].get(k, 0.0)) for k in BEHAVIOUR_KEYS}
    std = {}
    for k in BEHAVIOUR_KEYS:
        m2 = float(rec.get("m2", {}).get(k, 0.0))
        std[k] = math.sqrt(m2 / max(n - 1, 1)) if n > 1 else 1.0
    return {"name": rec["name"], "n": n, "mean": mean, "std": std}


def observe_approved(name: str, signals: dict) -> None:
    """Online (Welford) update of a customer's baseline after an approved
    session — the profile 'learns' how this person normally types."""
    if not name or not signals:
        return
    profiles = ensure_profiles()
    with LOCK:
        rec = profiles.get(name)
        if not rec:
            rec = _seeded_profiles(load_model()).get("Aarav Sharma")
            rec = dict(rec) if rec else {"name": name, "n": 0,
                                         "mean": {}, "m2": {}}
            rec["name"] = name
            profiles[name] = rec
        n = int(rec["n"])
        mean = {k: float(rec["mean"].get(k, 0.0)) for k in BEHAVIOUR_KEYS}
        m2 = {k: float(rec.get("m2", {}).get(k, 0.0)) for k in BEHAVIOUR_KEYS}
        for k in BEHAVIOUR_KEYS:
            if k not in signals:
                continue
            x = float(signals.get(k, 0.0))
            n1 = n + 1
            delta = x - mean[k]
            mean[k] += delta / n1
            m2[k] += delta * (x - mean[k])
        rec["n"] = n1
        rec["mean"] = mean
        rec["m2"] = m2
        profiles[name] = rec
        _flush_profiles(profiles)


def profiles_overview() -> list[dict]:
    """Compact list for the console's per-customer strip."""
    out = []
    for rec in ensure_profiles().values():
        s = _summarize(rec)
        out.append({
            "name": s["name"],
            "n": s["n"],
            "mean": {k: round(v, 2) for k, v in s["mean"].items()},
        })
    return out


# --------------------------------------------------------------------------
# Threshold explorer — replay the held-out validation snapshot
# --------------------------------------------------------------------------

def _as_vector(row: list, keys: list) -> dict:
    return {k: float(v) for k, v in zip(keys, row)}


def explore(low_max: float, medium_max: float) -> dict:
    """Score the saved validation sample under a candidate policy and report
    what would happen: how many normal payments auto-approve vs how many
    high-risk sessions are caught (not silently auto-approved)."""
    model = load_model()
    es = model.get("eval_set", {})
    keys = es.get("keys", FEATURE_KEYS)
    benign = es.get("benign", [])
    positive = es.get("positive", [])

    def score_of(row):
        return round(100.0 * model_probability(model, _as_vector(row, keys)))

    def classify(rows):
        low = med = high = 0
        for row in rows:
            s = score_of(row)
            if s < low_max:
                low += 1
            elif s < medium_max:
                med += 1
            else:
                high += 1
        n = max(len(rows), 1)
        return {"n": len(rows), "low": low / n, "med": med / n, "high": high / n}

    # full sweep for the trade-off curve: only the LOW cut-off changes the
    # instant-approval boundary (x = benign friction, y = risk caught)
    sweep = []
    for lv in range(0, 101, 2):
        b_low = sum(1 for row in benign if score_of(row) < lv) / max(len(benign), 1)
        p_caught = sum(1 for row in positive if score_of(row) >= lv) / max(len(positive), 1)
        sweep.append({"low_max": lv, "benign_approved": round(b_low, 4),
                      "risk_caught": round(p_caught, 4)})

    return {
        "low_max": low_max,
        "medium_max": medium_max,
        "benign": classify(benign),
        "positive": classify(positive),
        "sweep": sweep,
    }
