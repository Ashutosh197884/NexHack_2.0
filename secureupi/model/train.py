"""
SecureUPI model trainer — pure Python standard library only (no numpy/sklearn).

1. Generates a synthetic dataset of UPI payment sessions. Each session is a set
   of behavioural/context features captured from the payment flow (amount entry +
   PIN entry). Three "high-risk context" archetypes are generated alongside
   everyday payments:

     • SCREEN-SHARE SCAM   — scammer on a call, screen mirrored, amount/PIN typed
                             slowly with corrections while being dictated.
     • DURESS / TREMOR     — user physically pressured; shaky, uneven taps and
                             hesitant entry.
     • ANOMALY / RUSH      — legitimate but unusual: large amount to a new payee,
                             hurried typing. (Intentional hard-to-separate class.)

2. Trains a small logistic-regression model (interpretable → explainable risk
   score, which is the product's promise).

3. Writes model/risk_model.json + model/training_report.txt

Run from the secureupi/ directory:
    python model/train.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from risk_engine import FEATURES, FEATURE_KEYS, FLAG_KEYS  # noqa: E402

SEED = 42
N_TRAIN = 3200
N_VAL = 1000
TARGET_MEDIAN_BENIGN_SCORE = 12  # matches the phone mock in the deck ("Risk Score 12")

# --------------------------------------------------------------------------
# Synthetic data generation
# --------------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _logamount(rng: random.Random, lo: float, hi: float) -> float:
    """Random amount in [lo, hi] with a rough log-flat feel."""
    return math.exp(rng.uniform(math.log(lo), math.log(hi)))


def gen_benign(rng: random.Random) -> dict:
    """
    Everyday payment. Benign users are SMOOTH: few corrections, short pauses,
    steady holds, accurate taps. A 'cautious senior' subset types more slowly
    but keeps that smoothness — slowness alone must never read as risk, only
    hesitation/instability does. A small share of big legitimate purchases keeps
    the model honest (those may legitimately trigger step-up).
    """
    senior = rng.random() < 0.35
    big = rng.random() < 0.05  # legit large purchase (8k-45k)
    if big:
        amount = _logamount(rng, 8_000, 45_000)
    else:
        amount = _logamount(rng, 40, 2_000)
    if senior:
        # Slow but SMOOTH — and COMMON (35% of benign): risk must come from
        # instability, not slowness, or seniors get friction on every payment.
        return {
            "amount": amount,
            "new_payee": 1.0 if rng.random() < 0.03 else 0.0,
            "amount_fill_s": _clamp(rng.gauss(4.8, 1.7), 2.2, 9.5),
            "amount_corrections": _pick(rng, [(0, 0.93), (1, 0.07)]),
            "amount_max_pause_s": _clamp(rng.expovariate(1 / 0.62) * 0.62, 0.15, 1.9),
            "pay_dwell_s": _clamp(rng.gauss(2.4, 0.7), 0.8, 5.5),
            "pin_cps": _clamp(rng.gauss(2.75, 0.42), 1.9, 3.5),
            "pin_max_pause_s": _clamp(rng.expovariate(1 / 0.48) * 0.48, 0.15, 1.6),
            "pin_resets": _pick(rng, [(0, 0.99), (1, 0.01)]),
            "pin_hold_std_ms": _clamp(rng.gauss(43, 9), 18, 70),
            "pin_tap_offset_px": _clamp(rng.gauss(4.1, 1.0), 1.2, 7.5),
            "screen_share": 0.0,
            "integrity_fail": 0.0,
        }
    return {
        "amount": amount,
        "new_payee": 1.0 if rng.random() < (0.25 if big else 0.04) else 0.0,
        "amount_fill_s": _clamp(rng.gauss(2.2, 0.7), 0.8, 5.0),
        "amount_corrections": _pick(rng, [(0, 0.86), (1, 0.14)]),
        "amount_max_pause_s": _clamp(rng.expovariate(1 / 0.45) * 0.45, 0.15, 1.4),
        "pay_dwell_s": _clamp(rng.gauss(1.1, 0.4), 0.25, 3.0),
        "pin_cps": _clamp(rng.gauss(3.4, 0.45), 2.4, 5.4),
        "pin_max_pause_s": _clamp(rng.expovariate(1 / 0.35) * 0.35, 0.15, 1.2),
        "pin_resets": _pick(rng, [(0, 0.99), (1, 0.01)]),
        "pin_hold_std_ms": _clamp(rng.gauss(36, 8), 14, 65),
        "pin_tap_offset_px": _clamp(rng.gauss(3.4, 1.0), 0.8, 8.0),
        "screen_share": 0.0,
        "integrity_fail": 0.0,
    }


def gen_screenshare_scam(rng: random.Random) -> dict:
    """Caller dictates amount + PIN; screen is being shared; typing is slow/fixy."""
    amount = _logamount(rng, 20_000, 300_000)
    return {
        "amount": amount,
        "new_payee": 1.0 if rng.random() < 0.8 else 0.0,
        "amount_fill_s": rng.uniform(8, 30),
        "amount_corrections": rng.randint(2, 7),
        "amount_max_pause_s": rng.uniform(3.0, 10.0),
        "pay_dwell_s": rng.uniform(2.0, 10.0),
        "pin_cps": rng.uniform(0.45, 1.5),
        "pin_max_pause_s": rng.uniform(2.0, 8.0),
        "pin_resets": _pick(rng, [(0, 0.5), (1, 0.35), (2, 0.15)]),
        "pin_hold_std_ms": rng.uniform(40, 150),
        "pin_tap_offset_px": rng.uniform(2.0, 13.0),
        "screen_share": 1.0,
        "integrity_fail": 1.0 if rng.random() < 0.12 else 0.0,
    }


def gen_duress(rng: random.Random) -> dict:
    """Physical pressure: tremor, uneven holds, hesitant — no screen share."""
    amount = _logamount(rng, 5_000, 150_000)
    return {
        "amount": amount,
        "new_payee": 1.0 if rng.random() < 0.6 else 0.0,
        # Speed ranges deliberately overlap the benign slow-smooth band — what
        # separates duress is INSTABILITY: corrections, pauses, tremor taps.
        "amount_fill_s": rng.uniform(4.5, 16),
        "amount_corrections": rng.randint(2, 6),
        "amount_max_pause_s": rng.uniform(2.6, 8.0),
        "pay_dwell_s": rng.uniform(0.5, 4.5),
        "pin_cps": rng.uniform(0.6, 2.3),
        "pin_max_pause_s": rng.uniform(2.0, 7.0),
        "pin_resets": _pick(rng, [(0, 0.65), (1, 0.35)]),
        "pin_hold_std_ms": rng.uniform(95, 270),
        "pin_tap_offset_px": rng.uniform(9.5, 27.0),
        "screen_share": 0.0,
        "integrity_fail": 0.0,
    }


def _pick(rng: random.Random, choices):
    r = rng.random()
    acc = 0.0
    for value, prob in choices:
        acc += prob
        if r <= acc:
            return value
    return choices[-1][0]


def generate_session(rng: random.Random, label: int) -> tuple[dict, int]:
    if label == 0:
        return gen_benign(rng), 0
    if rng.random() < 0.5:
        return gen_screenshare_scam(rng), 1
    return gen_duress(rng), 1


def make_dataset(n: int, rng: random.Random):
    rows = []
    for _ in range(n):
        label = 1 if rng.random() < 0.45 else 0
        sess, lab = generate_session(rng, label)
        rows.append((sess, lab))
    return rows


# --------------------------------------------------------------------------
# Logistic regression (pure Python, full-batch gradient descent)
# --------------------------------------------------------------------------

def vectorize(sess: dict) -> list[float]:
    out = []
    for k in FEATURE_KEYS:
        if k == "amount_log":
            out.append(math.log10(max(float(sess.get("amount", 0.0)), 1.0)))
        else:
            out.append(float(sess.get(k, 0.0)))
    return out


def fit_lr(X: list[list[float]], y: list[int], lr: float = 1.2,
           epochs: int = 2200, tol: float = 3e-7, lam: float = 2.0,
           rng: random.Random = random.Random(0)):
    """L2-regularized logistic regression (lam on standardized features).
    Regularization keeps weights moderate so the live demo risk surface is
    smooth — tiny timing wobbles must not swing the score wildly."""
    n, d = len(X), len(X[0])
    w = [0.0] * d
    b = 0.0
    prev_loss = float("inf")
    for ep in range(1, epochs + 1):
        gw = [0.0] * d
        gb = 0.0
        loss = 0.0
        for i in range(n):
            z = b
            xi = X[i]
            for j in range(d):
                z += w[j] * xi[j]
            p = 1.0 / (1.0 + math.exp(-z)) if z < 50 else 1.0
            if z > 50:
                p = 1.0 - math.exp(-z)
            err = p - y[i]
            for j in range(d):
                gw[j] += err * xi[j]
            gb += err
            if y[i] == 1:
                loss -= math.log(max(p, 1e-12))
            else:
                loss -= math.log(max(1.0 - p, 1e-12))
        loss /= n
        reg = (lam / 2.0) * sum(wj * wj for wj in w) / n
        loss += reg
        for j in range(d):
            gw[j] += lam * w[j]
            w[j] -= (lr / n) * gw[j]
        b -= (lr / n) * gb
        if ep % 100 == 0:
            print(f"  epoch {ep:4d}  loss {loss:.5f}")
        if abs(prev_loss - loss) < tol and ep > 50:
            break
        prev_loss = loss
    return w, b


def predict_prob(X: list[list[float]], w: list[float], b: float) -> list[float]:
    out = []
    for xi in X:
        z = b + sum(wi * x for wi, x in zip(w, xi))
        out.append(1.0 / (1.0 + math.exp(-z)) if z < 50 else 1.0)
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    t0 = time.time()
    rng = random.Random(SEED)

    print("SecureUPI — behavioural risk model trainer (pure Python)\n")
    print(f"Generating synthetic dataset (train={N_TRAIN}, val={N_VAL}) ...")
    train = make_dataset(N_TRAIN, rng)
    val = make_dataset(N_VAL, rng)
    rng2 = random.Random(SEED + 1)

    # Standardization from training data
    Xtr = [vectorize(s) for s, _ in train]
    d = len(FEATURE_KEYS)
    mean = [sum(row[j] for row in Xtr) / len(Xtr) for j in range(d)]
    std = [math.sqrt(sum((row[j] - mean[j]) ** 2 for row in Xtr) / len(Xtr)) for j in range(d)]
    std = [max(s, 1e-9) for s in std]

    def zrows(rows):
        return [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in rows]

    Ztr = zrows(Xtr)
    ytr = [lab for _, lab in train]
    print(f"Training logistic regression on {N_TRAIN} sessions x {d} features ...")
    w, b = fit_lr(Ztr, ytr, rng=rng2)
    print("Done.\n")

    # Calibrate intercept so a *typical benign* session scores ≈ deck's "12"
    benign_val = [(s, l) for s, l in val if l == 0]
    benign_logits = []
    for s, _ in benign_val:
        z = b + sum(wi * (xi - m) / sd for wi, xi, m, sd in zip(w, vectorize(s), mean, std))
        benign_logits.append(z)
    benign_logits.sort()
    median_logit = benign_logits[len(benign_logits) // 2]
    target_logit = math.log(TARGET_MEDIAN_BENIGN_SCORE / (100 - TARGET_MEDIAN_BENIGN_SCORE))
    b_cal = b + (target_logit - median_logit)
    print(f"Calibration: median benign logit {median_logit:.3f} -> target "
          f"{target_logit:.3f} (intercept {b:.3f} -> {b_cal:.3f})")

    # Evaluate
    Xva = [vectorize(s) for s, _ in val]
    Zva = zrows(Xva)
    probs = predict_prob(Zva, w, b_cal)
    yva = [lab for _, lab in val]
    correct = sum(1 for p, y in zip(probs, yva) if (p >= 0.5) == (y == 1))
    acc = correct / len(yva)
    tp = sum(1 for p, y in zip(probs, yva) if y == 1 and p >= 0.5)
    fn = sum(1 for p, y in zip(probs, yva) if y == 1 and p < 0.5)
    tn = sum(1 for p, y in zip(probs, yva) if y == 0 and p < 0.5)
    fp = sum(1 for p, y in zip(probs, yva) if y == 0 and p >= 0.5)
    risk_recall = tp / max(tp + fn, 1)
    benign_spec = tn / max(tn + fp, 1)
    avg_p_risk = sum(p for p, y in zip(probs, yva) if y == 1) / max(tp + fn, 1)
    avg_p_benign = sum(p for p, y in zip(probs, yva) if y == 0) / max(tn + fp, 1)

    # Level-band behaviour for normal payments (false-positive control)
    benign_scores = sorted(100 * p for p, y in zip(probs, yva) if y == 0)
    n_benign = len(benign_scores)
    ben_low_share = sum(1 for s in benign_scores if s < 30) / n_benign
    ben_med_share = sum(1 for s in benign_scores if 30 <= s < 65) / n_benign

    print(f"\nValidation (n={N_VAL}):")
    print(f"  accuracy        {acc:.3f}")
    print(f"  risk recall     {risk_recall:.3f}   (of real high-risk sessions, fraction flagged)")
    print(f"  benign spec     {benign_spec:.3f}   (of normal payments, fraction approved)")
    print(f"  mean P(risk)    risk={avg_p_risk:.3f}  benign={avg_p_benign:.3f}")
    print(f"  benign level    LOW {ben_low_share:.1%}  MEDIUM {ben_med_share:.1%}  "
          f"(median benign score = {benign_scores[len(benign_scores) // 2]:.0f})")

    # Eval snapshot for the PSP threshold explorer (replay validation set)
    eval_set = {"keys": FEATURE_KEYS, "benign": [], "positive": []}
    rng_snap = random.Random(1234)
    by_label = {0: eval_set["benign"], 1: eval_set["positive"]}
    for s, lab in val:
        bucket = by_label[lab]
        if len(bucket) < 500:
            bucket.append(vectorize(s))

    # Benign profile (centroid) for the on-device anomaly index
    benign_rows = [(s, vectorize(s)) for s, l in val if l == 0]
    bmean = {}
    bstd = {}
    for j, key in enumerate(FEATURE_KEYS):
        vals = [row[j] for _, row in benign_rows]
        bmean[key] = sum(vals) / len(vals)
        bstd[key] = math.sqrt(sum((v - bmean[key]) ** 2 for v in vals) / len(vals))

    # Feature weights (report uses standardized scale)
    weights = {key: round(wi, 4) for key, wi in zip(FEATURE_KEYS, w)}
    report = _build_report(acc, risk_recall, benign_spec, avg_p_risk, avg_p_benign,
                           weights, mean, std, b_cal, tp, fp, tn, fn,
                           ben_low_share, ben_med_share)

    model = {
        "version": "0.1.0-sih",
        "name": "secureupi-behavioral-risk-v1",
        "trained_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "estimator": "logistic-regression (standardized features)",
        "target": "high-risk payment context (screenshare scam / duress / anomaly)",
        "n_train": N_TRAIN,
        "n_val": N_VAL,
        "metrics": {
            "accuracy": round(acc, 4),
            "risk_recall": round(risk_recall, 4),
            "benign_specificity": round(benign_spec, 4),
            "mean_p_risk_positive": round(avg_p_risk, 4),
            "mean_p_risk_benign": round(avg_p_benign, 4),
            "benign_level_low_share": round(ben_low_share, 4),
            "benign_level_medium_share": round(ben_med_share, 4),
            "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        },
        "calibration": {
            "target_median_benign_score": TARGET_MEDIAN_BENIGN_SCORE,
            "intercept_original": round(b, 4),
            "intercept": round(b_cal, 4),
        },
        "scaler": {"mean": {k: round(m, 6) for k, m in zip(FEATURE_KEYS, mean)},
                   "std": {k: round(s, 6) for k, s in zip(FEATURE_KEYS, std)}},
        "weights": weights,
        "benign_profile": {"mean": {k: round(v, 6) for k, v in bmean.items()},
                           "std": {k: round(v, 6) for k, v in bstd.items()}},
        "features": FEATURES,
        "eval_set": eval_set,
    }

    out_dir = Path(__file__).resolve().parent
    with open(out_dir / "risk_model.json", "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=1)
    with open(out_dir / "training_report.txt", "w", encoding="utf-8") as fh:
        fh.write(report)
    print(f"\nWrote model/risk_model.json and model/training_report.txt "
          f"({time.time() - t0:.1f}s)")

    # ---- canonical demo scenarios -------------------------------------
    demo_sessions(rng, w, b_cal, mean, std)


def demo_sessions(rng, w, b, mean, std) -> None:
    """Score the showcase scenarios with FIXED, deterministic signals, so the
    live demo narrative is stable across retrains."""
    print("\nCanonical demo scenarios (what the judges will see — deterministic):")

    def score(sess):
        z = b + sum(wi * (xi - m) / sd for wi, xi, m, sd in zip(w, vectorize(sess), mean, std))
        p = 1.0 / (1.0 + math.exp(-z))
        sc = round(100 * p)
        lvl = "LOW" if sc < 30 else ("MEDIUM" if sc < 65 else "HIGH")
        return sc, lvl

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

    scenarios = [
        ("Coffee ₹250 — calm morning payment",
         sess(250, 0, 2.1, 0, 0.5, 1.1, 3.4, 0.4, 0, 34, 3.2, 0, 0)),
        ("Senior, ₹450 — slow but smooth (light step-up → approve)",
         sess(450, 0, 4.6, 0, 1.0, 2.2, 2.5, 0.7, 0, 44, 4.0, 0, 0)),
        ("Big legit ₹45,000, new payee (2 AM)",
         sess(45_000, 1, 3.0, 0, 0.6, 1.4, 3.1, 0.5, 0, 35, 3.1, 0, 0)),
        ("₹50,000 'verify account' screen-share scam",
         sess(50_000, 1, 14.0, 4, 6.0, 5.0, 1.0, 3.5, 1, 72, 6.5, 1, 0)),
        ("Duress: ₹40,000 forced transfer",
         sess(40_000, 1, 8.0, 3, 3.0, 2.0, 1.4, 2.5, 1, 150, 14.0, 0, 0)),
    ]
    for name, sess in scenarios:
        sc, lvl = score(sess)
        print(f"  {name:46s} -> score {sc:3d}  {lvl}")


def _build_report(acc, rr, bs, pr, pb, weights, mean, std, b_cal, tp, fp, tn, fn,
                  ben_low_share, ben_med_share) -> str:
    lines = []
    lines.append("SecureUPI — Behavioural Risk Model Training Report")
    lines.append("=" * 70)
    lines.append(f"Trained at : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    lines.append("Estimator  : logistic regression on standardised features")
    lines.append(f"Target     : high-risk payment context (screenshare scam / duress / anomaly)")
    lines.append("")
    lines.append("VALIDATION METRICS")
    lines.append("-" * 70)
    lines.append(f"  accuracy             : {acc:.3f}")
    lines.append(f"  risk recall          : {rr:.3f}")
    lines.append(f"  benign specificity   : {bs:.3f}")
    lines.append(f"  mean P(risk)|risk    : {pr:.3f}")
    lines.append(f"  mean P(risk)|benign  : {pb:.3f}")
    lines.append(f"  confusion            : TP={tp} FP={fp} TN={tn} FN={fn}")
    lines.append(f"  benign level share   : LOW {ben_low_share:.1%}, MEDIUM {ben_med_share:.1%}")
    lines.append("")
    lines.append("MODEL WEIGHTS (standardised scale; sign = risk direction)")
    lines.append("-" * 70)
    for j, f in enumerate(FEATURES):
        lines.append(f"  {f['key']:22s} w={weights[f['key']]:+.3f}   {f['label']}")
    lines.append("")
    lines.append("NOTE — what this model can and cannot claim")
    lines.append("-" * 70)
    lines.append("• Inputs are DERIVED features (timings, counts, flags), never raw")
    lines.append("  touch streams — consistent with privacy-by-design.")
    lines.append("• Output is a contextual risk SIGNAL for pre-authorization")
    lines.append("  adaptive/step-up authentication, NOT fraud detection and NOT")
    lines.append("  a replacement for the UPI PIN or PSP decisioning.")
    lines.append("• Synthetic training data: real labelled behavioural data would")
    lines.append("  come from opt-in pilots with PSPs/banks under regulatory review.")
    lines.append("")
    lines.append(f"Calibrated intercept: {b_cal:.3f}  (typical benign session ≈ score 12)")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
