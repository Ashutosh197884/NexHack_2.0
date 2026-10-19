"""Optional ML module — behind a stable interface per plan §10.

The trained model artifact ("model card" output) lives in the prototype's
`secureupi/model/risk_model.json` and is loaded through the same code path the
production demo uses (`secureupi.risk_engine.RiskEngine`). Nothing here may
hard-fail the app: if the artifact is missing the API still runs with the
rule-based engine and reports `ml_ok=False`.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

# The proven engine + trained artifact live in ../secureupi (repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from secureupi import risk_engine as legacy  # noqa: E402  (proven engine)

_lock = threading.Lock()
_engine = None


def get_engine() -> "legacy.RiskEngine":
    global _engine
    with _lock:
        if _engine is None:
            _engine = legacy.RiskEngine()
        return _engine


def is_available() -> bool:
    try:
        get_engine()
        return True
    except Exception:  # noqa: BLE001 — ML must be optional (plan §10)
        return False


def model_card() -> dict:
    m = get_engine().model
    metrics: dict = m["metrics"]
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
        "feature_count": len(m["features"]),
    }
