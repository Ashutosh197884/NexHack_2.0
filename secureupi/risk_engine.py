"""
SecureUPI Risk Engine — core scoring module.

Loads the trained behavioral model (plain JSON), scores a payment session,
and produces an *explainable* risk result:
    risk_score (0-100) + level + recommended action + top contributing factors.

The full pipeline mirrors what the production Android SDK would do:
raw touch/interaction streams stay on-device; only this small derived
feature vector ever reaches the risk engine.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

# --------------------------------------------------------------------------
# Feature schema — single source of truth, shared with the trainer and UI.
# --------------------------------------------------------------------------

FEATURES: list[dict] = [
    {
        "key": "amount_log", "label": "Payment amount", "unit": "log10(₹)",
        "kind": "continuous", "direction": "higher",
        "description": "Larger transfers are inherently higher-stakes contexts.",
    },
    {
        "key": "new_payee", "label": "First payment to payee", "unit": "yes/no",
        "kind": "flag", "direction": "higher",
        "description": "No transaction history with this VPA.",
    },
    {
        "key": "amount_fill_s", "label": "Amount entry time", "unit": "s",
        "kind": "continuous", "direction": "higher",
        "description": "Seconds to key in the amount — slow, hesitant entry is a coercion signal.",
    },
    {
        "key": "amount_corrections", "label": "Amount corrections", "unit": "count",
        "kind": "continuous", "direction": "higher",
        "description": "Times the amount was edited/deleted while typing (misread instructions?).",
    },
    {
        "key": "amount_max_pause_s", "label": "Longest typing pause", "unit": "s",
        "kind": "continuous", "direction": "higher",
        "description": "Longest idle gap while entering the amount (waiting for the caller?).",
    },
    {
        "key": "pay_dwell_s", "label": "Review time before Pay", "unit": "s",
        "kind": "continuous", "direction": "higher",
        "description": "Time between finishing the amount and pressing Pay.",
    },
    {
        "key": "pin_cps", "label": "PIN entry speed", "unit": "digits/s",
        "kind": "continuous", "direction": "lower",
        "description": "Digits of the UPI PIN tapped per second.",
    },
    {
        "key": "pin_max_pause_s", "label": "Longest PIN pause", "unit": "s",
        "kind": "continuous", "direction": "higher",
        "description": "Longest gap between PIN digits (PIN being dictated?).",
    },
    {
        "key": "pin_resets", "label": "PIN re-entries", "unit": "count",
        "kind": "continuous", "direction": "higher",
        "description": "Times the PIN pad was cleared and started again.",
    },
    {
        "key": "pin_hold_std_ms", "label": "Tap-hold variability", "unit": "ms",
        "kind": "continuous", "direction": "higher",
        "description": "Std-dev of key-press durations — stress/tremor makes holds uneven.",
    },
    {
        "key": "pin_tap_offset_px", "label": "Tap accuracy offset", "unit": "px",
        "kind": "continuous", "direction": "higher",
        "description": "Avg distance from key centre at press — drops when hands shake.",
    },
    {
        "key": "screen_share", "label": "Screen-share / remote view", "unit": "yes/no",
        "kind": "flag", "direction": "higher",
        "description": "MediaProjection / accessibility / overlay capture detected during flow.",
    },
    {
        "key": "integrity_fail", "label": "Device integrity failure", "unit": "yes/no",
        "kind": "flag", "direction": "higher",
        "description": "Play Integrity verdict failed (rooted, emulator, tampered app).",
    },
]

FEATURE_KEYS: list[str] = [f["key"] for f in FEATURES]
LABELS: dict[str, str] = {f["key"]: f["label"] for f in FEATURES}
UNITS: dict[str, str] = {f["key"]: f["unit"] for f in FEATURES}
FLAG_KEYS: set[str] = {f["key"] for f in FEATURES if f["kind"] == "flag"}

# --------------------------------------------------------------------------
# Decision policy
# --------------------------------------------------------------------------

LEVEL_LOW = "LOW"
LEVEL_MEDIUM = "MEDIUM"
LEVEL_HIGH = "HIGH"

# --------------------------------------------------------------------------
# Risk policy — these thresholds are POLICY, not science. The PSP operator can
# tune them from the bank console; the threshold-explorer replays the
# validation set to show the false-positive vs catch-rate trade-off.
# --------------------------------------------------------------------------

DEFAULT_POLICY: dict = {
    "low_max": 30.0,          # score < low_max  -> LOW  (instant approve)
    "medium_max": 65.0,       # score < medium_max -> MEDIUM, else HIGH
    "challenge_block_at": 45.0,  # step-up round: score >= this -> BLOCK
    "hard_gate_amount": 10_000.0,  # screenshare + this amount at step-up -> never approve
}

# Back-compat aliases for module-level imports
LOW_MAX = DEFAULT_POLICY["low_max"]
MEDIUM_MAX = DEFAULT_POLICY["medium_max"]
CHALLENGE_BLOCK_AT = DEFAULT_POLICY["challenge_block_at"]
HARD_GATE_SCREENSHARE_AMOUNT = DEFAULT_POLICY["hard_gate_amount"]

# Context features that are NOT part of a user's behavioural profile
CONTEXT_FEATURES = {"amount_log"}  # flags are also skipped in deviation below

# On a step-up challenge the amount is NOT re-entered, so round-1 context AND
# amount-entry behaviour are stale state, not fresh re-authentication signals.
# Round 2 must score only the PIN re-entry (+ device flags) — exactly what the
# demo actually re-measures — so these keys are frozen at the model's benign
# mean (see evaluate()).
CHALLENGE_FROZEN = ("amount_log", "new_payee", "amount_fill_s",
                    "amount_corrections", "amount_max_pause_s", "pay_dwell_s")

ACTIONS = {
    "approve": "APPROVE",
    "step_up": "STEP-UP",
    "block": "BLOCK",
}


class ModelNotLoadedError(RuntimeError):
    pass


def _default_model_path() -> Path:
    env = os.environ.get("SECUREUPI_MODEL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "model" / "risk_model.json"


def load_model(path: str | Path | None = None):
    p = Path(path) if path else _default_model_path()
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _sigmoid(z: float) -> float:
    if z >= 0:
        e = math.exp(-z)
        return 1.0 / (1.0 + e)
    e = math.exp(z)
    return e / (1.0 + e)


def standardize(model: dict, vector: dict[str, float]) -> dict[str, float]:
    """z-score every feature against the training distribution."""
    mean = model["scaler"]["mean"]
    std = model["scaler"]["std"]
    out = {}
    for k in FEATURE_KEYS:
        x = float(vector.get(k, 0.0))
        s = max(float(std[k]), 1e-9)
        out[k] = (x - float(mean[k])) / s
    return out


def model_probability(model: dict, vector: dict[str, float]) -> float:
    """P(high-risk context) from the logistic-regression model."""
    z = float(model["calibration"]["intercept"])
    zsc = standardize(model, vector)
    w = model["weights"]
    for k in FEATURE_KEYS:
        z += float(w[k]) * zsc[k]
    return _sigmoid(z)


def contributions(model: dict, vector: dict[str, float]) -> list[dict]:
    """
    Per-feature contribution to the log-odds (explainable risk score).
    Positive = pushes toward HIGH RISK. Returns them sorted by strength.
    """
    zsc = standardize(model, vector)
    w = model["weights"]
    mean = model["scaler"]["mean"]
    std = model["scaler"]["std"]
    raw = {}
    for k in FEATURE_KEYS:
        x = float(vector.get(k, 0.0))
        cont = float(w[k]) * zsc[k]
        if abs(cont) < 1e-9:
            continue
        raw[k] = {
            "key": k,
            "label": LABELS[k],
            "unit": UNITS[k],
            "value": x,
            "baseline": float(mean[k]),
            "baseline_std": float(std[k]),
            "contribution": round(cont, 3),
            "direction": FEATURES[_idx(k)]["direction"],
        }
    return sorted(raw.values(), key=lambda c: abs(c["contribution"]), reverse=True)


def _idx(key: str) -> int:
    return FEATURE_KEYS.index(key)


def profile_deviation(model: dict, vector: dict[str, float],
                      profile: dict | None = None) -> float:
    """
    How far this session sits from the user's *benign* behavioural profile, as
    RMS standardised distance over their behavioural features. `profile` may
    override the global benign profile with a learned per-customer baseline
    ({'mean': {...}, 'std': {...}}) — so a slow-typing senior is compared with
    their OWN history, not with the global average.
    """
    bm = dict(model["benign_profile"]["mean"])
    bs = dict(model["benign_profile"]["std"])
    if profile:
        for k in profile.get("mean", {}):
            if k in bm:
                bm[k] = float(profile["mean"][k])
        for k in profile.get("std", {}):
            if k in bs:
                bs[k] = float(profile["std"][k])
    total, n = 0.0, 0
    for k in FEATURE_KEYS:
        if k in FLAG_KEYS or k in CONTEXT_FEATURES:
            continue  # flags + amount are explicit context, not profile drift
        s = max(float(bs.get(k, 1.0)), 1e-9)
        total += ((float(vector.get(k, 0.0)) - float(bm.get(k, 0.0))) / s) ** 2
        n += 1
    return round(math.sqrt(total / max(n, 1)), 2)


def _fmt_contribution(c: dict) -> dict:
    """Human-readable contribution; `share` (filled by evaluate) is the factor's
    share of the total positive risk drivers pushing the gauge up."""
    v = c["value"]
    if isinstance(v, float) and not v.is_integer():
        v = round(v, 2)
    if c["key"] in FLAG_KEYS:
        value_txt = "YES" if float(v) else "no"
    else:
        value_txt = f"{v} {c['unit']}".replace(".0 ", " ")
    baseline = c["baseline"]
    if not isinstance(baseline, float) or baseline.is_integer():
        baseline = int(baseline)
    else:
        baseline = round(baseline, 2)
    contrib = float(c["contribution"])
    return {
        "key": c["key"],
        "label": c["label"],
        "value": value_txt,
        "baseline": f"typical {baseline} {c['unit']}".replace(".0 ", " "),
        "share": contrib,  # share filled in by evaluate (share of risk drivers)
    }


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

class RiskEngine:
    def __init__(self, model: dict | None = None, policy: dict | None = None):
        self.model = model or load_model()
        self.policy = dict(DEFAULT_POLICY)
        if policy:
            self.policy.update({k: float(v) for k, v in policy.items() if k in DEFAULT_POLICY})

    def set_policy(self, policy: dict) -> None:
        for k, v in policy.items():
            if k in self.policy:
                self.policy[k] = float(v)

    def evaluate(self, vector: dict[str, float], *, step: str = "initial",
                 amount: float = 0.0, screen_share: bool | None = None,
                 integrity_fail: bool | None = None,
                 policy: dict | None = None,
                 profile: dict | None = None) -> dict:
        """
        Evaluate one payment attempt.

        vector         : derived behavioural/context features (all 13 keys optional;
                         missing -> baseline/0 which is fine).
        step           : 'initial' first assessment, or 'challenge' step-up re-entry.
        amount         : raw amount in INR (used by hard rules).
        screen_share / integrity_fail : overrides if caller prefers to pass raw signals.
        """
        vector = dict(vector)
        if amount > 0 and "amount_log" not in vector or vector.get("amount_log") is None:
            vector["amount_log"] = round(math.log10(max(amount, 1.0)), 4)
        if screen_share is not None:
            vector["screen_share"] = 1.0 if screen_share else 0.0
        if integrity_fail is not None:
            vector["integrity_fail"] = 1.0 if integrity_fail else 0.0

        # On a step-up challenge, round 2 judges the re-authentication BEHAVIOUR
        # only. The context (amount, payee) was accepted as "needs step-up", not
        # denied — and the amount is not re-entered on the challenge screen, so
        # any amount-entry features in the payload are stale round-1 state.
        # Freeze them at the model's BENIGN mean (not the scaler mean, which is
        # inflated by the balanced risk class): that is risk-neutral for a
        # typical legitimate session, and round 2 scores the fresh PIN re-entry
        # + device flags alone.
        if step == "challenge":
            vector = dict(vector)
            bmean = self.model["benign_profile"]["mean"]
            for k in CHALLENGE_FROZEN:
                vector[k] = float(bmean[k])

        eff = dict(self.policy)
        if policy:
            eff.update({k: float(v) for k, v in policy.items() if k in self.policy})
        low_max, med_max = eff["low_max"], eff["medium_max"]
        block_at = eff["challenge_block_at"]
        hard_gate = eff["hard_gate_amount"]

        p = model_probability(self.model, vector)
        score = round(100.0 * p)
        raw_pos = [c for c in contributions(self.model, vector) if c["contribution"] > 0]
        total_pos = sum(c["contribution"] for c in raw_pos) or 1.0
        contribs = []
        for c in raw_pos:
            item = _fmt_contribution(c)
            share = c["contribution"] / total_pos * 100.0
            item["share"] = round(share, 1)
            contribs.append(item)
        dev = profile_deviation(self.model, vector, profile=profile)
        level, msgs, force_block = self._apply_policy(vector, score, amount, step,
                                                      low_max=low_max, med_max=med_max,
                                                      hard_gate=hard_gate)

        if step == "challenge":
            if score >= block_at or force_block:
                action = ACTIONS["block"]
                msgs.append("Step-up re-authentication still shows high behavioural risk — blocked.")
            else:
                action = ACTIONS["approve"]
                msgs.append("Context accepted for step-up; calm re-authentication cleared it — approved.")
        else:
            action = {
                LEVEL_LOW: ACTIONS["approve"],
                LEVEL_MEDIUM: ACTIONS["step_up"],
                LEVEL_HIGH: ACTIONS["step_up"],
            }[level]
            if level == LEVEL_HIGH:
                msgs.append("High risk — step-up authentication required before authorization.")

        return {
            "risk_score": score,
            "level": level,
            "action": action,
            "probability": round(p, 4),
            "top_contributors": contribs[:5],
            "policy": msgs,
            "profile_deviation": dev,
            "step": step,
            "policy_config": eff,
        }

    def _apply_policy(self, vector: dict, score: int, amount: float, step: str,
                      low_max: float, med_max: float, hard_gate: float) -> tuple[str, list[str], bool]:
        """Deterministic rules layered on top of the model score.
        Returns (level, messages, force_block) — force_block is a policy gate
        (e.g. active screen-share at step-up) that overrides any score cut-off."""
        level = LEVEL_LOW if score < low_max else (LEVEL_MEDIUM if score < med_max else LEVEL_HIGH)
        policy: list[str] = []
        force_block = False

        ss = bool(vector.get("screen_share", 0))
        ig = bool(vector.get("integrity_fail", 0))

        if ig:
            policy.append("Device integrity failure — Play Integrity verdict not met.")
            level = _max_level(level, LEVEL_MEDIUM)
            if score < 50 and amount >= 5_000:
                policy.append("Policy: integrity failure + sizable transfer caps risk at MEDIUM at minimum.")
        if ss:
            policy.append("Screen-share / remote-view detected during the payment flow.")
            level = _max_level(level, LEVEL_MEDIUM)
        if step == "challenge" and ss and amount >= hard_gate:
            policy.append("Hard gate: active screen-share during step-up on a large transfer → blocked.")
            level = LEVEL_HIGH
            force_block = True
        return level, policy, force_block

    def level_for_score(self, score: float) -> str:
        low, med = self.policy["low_max"], self.policy["medium_max"]
        return LEVEL_LOW if score < low else (LEVEL_MEDIUM if score < med else LEVEL_HIGH)


def _max_level(a: str, b: str) -> str:
    order = {LEVEL_LOW: 0, LEVEL_MEDIUM: 1, LEVEL_HIGH: 2}
    return a if order[a] >= order[b] else b


def model_score(model: dict, vector: dict[str, float]) -> float:
    """Raw 0-100 score for one vector — used by the threshold explorer replay."""
    return round(100.0 * model_probability(model, vector))


# --------------------------------------------------------------------------
# Convenience vector builder from wire payloads (see server.py)
# --------------------------------------------------------------------------

def vector_from_payload(payload: dict) -> tuple[dict[str, float], float]:
    """Flatten the demo SDK payload into the 13-feature model vector."""
    sig = payload.get("signals", {})
    det = payload.get("detections", {})
    ctx = payload.get("context", {})
    amount = float(ctx.get("amount", 0.0))

    vector: dict[str, float] = {
        "amount_log": round(math.log10(max(amount, 1.0)), 4),
        "new_payee": 1.0 if ctx.get("new_payee") else 0.0,
        "amount_fill_s": float(sig.get("amount_fill_s", 0.0)),
        "amount_corrections": float(sig.get("amount_corrections", 0.0)),
        "amount_max_pause_s": float(sig.get("amount_max_pause_s", 0.0)),
        "pay_dwell_s": float(sig.get("pay_dwell_s", 0.0)),
        "pin_cps": float(sig.get("pin_cps", 0.0)),
        "pin_max_pause_s": float(sig.get("pin_max_pause_s", 0.0)),
        "pin_resets": float(sig.get("pin_resets", 0.0)),
        "pin_hold_std_ms": float(sig.get("pin_hold_std_ms", 0.0)),
        "pin_tap_offset_px": float(sig.get("pin_tap_offset_px", 0.0)),
        "screen_share": 1.0 if det.get("screen_share") else 0.0,
        "integrity_fail": 1.0 if det.get("integrity_fail") else 0.0,
    }
    return vector, amount
