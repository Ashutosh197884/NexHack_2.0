# 🛡 SecureUPI — SIH working prototype

A runnable demo of **SecureUPI**: an AI-powered security layer that sits *around*
an existing UPI app and evaluates whether a payment looks risky **before** it is
authorized — then lets the bank/PSP **approve, step-up, or block**.

This folder is the prototype behind the `SecureUPI_SIH_Presentation.pptx` deck.
It implements the full signal path the deck describes:

```
User → SDK captures interaction behaviour (amount + PIN entry, device context)
     → feature vector (derived only — raw streams never leave the device)
     → Risk Engine (logistic-regression model + policy rules)
     → risk score 0–100, level (LOW/MEDIUM/HIGH), action (APPROVE/STEP-UP/BLOCK)
     → explainable "why?" (per-factor share of the risk drivers)
```

**Zero dependencies — pure Python standard library.** No pip install, no venv,
no npm, works offline. The model is trained by a script and stored as JSON.

---

## Quickstart

```bash
cd secureupi
python server.py            # serves the demo UI + API on http://127.0.0.1:8077
```

Open <http://127.0.0.1:8077> in a browser. Done.

Two pages:
| Page | URL | What it is |
|---|---|---|
| **Payment demo** | `/` | the customer's UPI app — run the scenarios |
| **PSP Operations Console** | `/bank` (link in the top bar) | the bank side: live transaction monitor, SecureUPI risk drill-down, operator actions, **NPCI/UPI-switch settlement**, a **risk-policy tuner** (threshold explorer) and **per-customer behavioural profiles** |

Optional: retrain the behavioural model (takes ~8 s, writes `model/risk_model.json`
+ `model/training_report.txt`):

```bash
python model/train.py
```

Server API:
| Endpoint | Purpose |
|---|---|
| `POST /api/v1/assess` | score one payment attempt (see payload below) |
| `GET /api/v1/model` | model card (metrics, learned signal weights, benign profile) |
| `GET /api/v1/events` | risk-event log ("Security Analytics") |
| `POST /api/v1/events/reset` | clear the log |
| `GET /api/v1/bank/transactions` | bank-side transaction lifecycle (rounds, state, **switch leg**, audit) |
| `POST /api/v1/bank/actions` | operator action: `confirm_fraud` / `override_approve` |
| `POST /api/v1/bank/report` | customer app "report to bank" for a blocked session |
| `POST /api/v1/bank/load-sample` | seed a deterministic simulated bank day (source=`sample`) |
| `POST /api/v1/bank/clear-sample` | remove simulated rows |
| `GET /api/v1/policy` · `POST /api/v1/policy` | read / tune the risk policy (LOW/HIGH cut-offs, step-up block bar) |
| `GET /api/v1/policy/explore?low=&med=` | validation replay: false-positive vs catch-rate trade-off for a candidate policy |
| `GET /api/v1/profiles` | per-customer learned behavioural baselines |
| `GET /api/v1/health` | liveness |

`POST /api/v1/assess` now also returns `profile_typical` (that customer's own
learned baselines for the signal grid) and the bank/switch leg of the payment.

### Assess payload

```jsonc
{
  "session_id": "s-abc123",           // same id for round 1 + round 2
  "step": "initial",                  // "initial" | "challenge" (step-up round)
  "context": { "amount": 50000, "payee": "refund.verify@icici", "new_payee": true },
  "signals": {                        // derived behavioural features (SDK side)
    "amount_fill_s": 13.5, "amount_corrections": 3, "amount_max_pause_s": 6.0,
    "pay_dwell_s": 4.6, "pin_cps": 1.1, "pin_max_pause_s": 3.0, "pin_resets": 1,
    "pin_hold_std_ms": 180, "pin_tap_offset_px": 8.0
  },
  "detections": { "screen_share": true, "integrity_fail": false }
}
```

Returns `risk_score`, `level`, `action`, `top_contributors` (label, measured
value, typical baseline, share of risk drivers), `policy` (rule hits),
`profile_deviation`, plus an `event` row for the log.

---

## The 60-second demo script (what judges see)

The UI has six scenario buttons that **simulate real user behaviour** (paced
typing, hesitations, corrections, tremor-like taps) so every score is produced
live from the simulated SDK signals — nothing is hard-coded on the client.

**Act 0 — the PSP console.** Before the payment demo, open the **PSP Operations
Console** (`/bank`) and press **"Load sample bank day"** so the console looks
like a real bank ops desk (rows are clearly labelled SIMULATED). Then run the
scenarios below on the payment demo page — every attempt lands **live** in the
console.

| # | Scenario | Expected outcome |
|---|---|---|
| 1 | ☕ **Coffee ₹250 (calm)** | Score low (single digits — varies slightly with typing jitter) · **LOW → APPROVE instantly** — matches the "Low risk" phone in the deck |
| 2 | 👧 **Senior ₹450 (slow but smooth)** | Score ~50–60 · **STEP-UP → approve** after a calm re-entry — slow but *steady* typing is compared with Ramesh's OWN baseline (auto-switches the persona) |
| 3 | 🌙 **2 AM ₹45,000 to a new payee** | **STEP-UP → approve** — big unusual payment gets friction, calm re-authentication clears it |
| 4 | 💀 **“Verify account” ₹50,000 scam** | Score ~100 · **STEP-UP → BLOCK** — screen-share active + dictated, hesitant PIN entry (a mid-entry PIN restart is captured as a real re-entry signal); hard gate refuses even the second attempt |
| 5 | 👮 **Duress ₹40,000** | Score high · **BLOCK** after anxious re-entry — coercion signals (uneven tap-holds, big offsets) even with no screen-share |
| 6 | 👋 **Try it yourself** | Type an amount, tap any 4-digit PIN (demo PIN: **7241**, any works) — calm rhythm → approve; hesitation/tremor → step-up |

**Act 3 — the bank handles it (on `/bank`).** When a payment is blocked, the
console pops a review banner and the row shows `BLOCKED` with two operator
actions — the whole point of the deck's "enforcement stays with the PSP":

- **Confirm fraud** → issues a fraud report id (`FR-…`), moves the row to
  `FRAUD REPORTED`, appends the audit trail. (The phone's **"Report to bank"**
  button does the same from the customer side.)
- **Override** → the PSP overrides the block after verifying the customer
  (row → `OVERRIDDEN`, audit notes "manual override").

**Act 4 — settlement.** Every row's **Settlement** column shows where the
payment ended on the NPCI/UPI switch:

- `NPCI ✓ N…UTR…` — settled: approved (or overridden) payments get a
  deterministic 12-digit **UTR** and mock switch round-trip latency;
- `not sent · pre-auth block` — a SecureUPI block means the payment never
  reached the switch;
- `in risk review` — held by the PSP while a step-up is pending.

An **UPI Switch card** in the drill-down drawer shows the full leg (rail,
status, UTR, timestamp, round-trip ms), so the lifecycle reads end to end:
*SecureUPI assess → PSP decision → switch settlement/failure*.

**Act 5 — tune the policy (⚙ Risk policy).** The console operator can drag the
LOW / HIGH cut-offs and the step-up block bar **live**; a validation replay
graph shows the honest trade-off (higher LOW bar → fewer normal frictions but
more fraud slips through; default: ~86% of normal payments auto-approve, 100%
of the held-out high-risk set is caught at ≥ step-up). Save applies the policy
server-side — the next payment on the phone demo uses the new cut-offs. The
policy lives in `data/policy.json` (see honesty box: thresholds are policy,
not science).

**Act 6 — per-customer profiles.** Switch the persona dropdown on the payment
demo (Aarav — fast; Ramesh — slow-but-smooth senior). Each customer has a
learned baseline, so Ramesh's slow typing is judged against *his own* history,
not the global average — the signal grid shows "your typical ≈" values that
follow the selected persona, and the console's customer strip shows each
customer's step-up rate and blocked count.

Click any row for the drill-down: both SecureUPI rounds (scores, levels,
explainable risk drivers, policy hits, derived signals, profile deviation) and
the full audit timeline. KPIs at the top update live: payments monitored, ₹
protected by blocks, step-up clear rate, reports filed.

While the payment plays, the right-hand console shows: the live risk gauge,
**why** the score is what it is (per-factor %), the derived signal vector vs the
user's typical profile, an SDK telemetry ticker, the risk-event log, and the
model card. Judges can ask "why did it block?" and you point at the screen.

**The pitch line to remember (also in the deck):** SecureUPI does *not* detect
fraud and does *not* replace the UPI PIN, NPCI, banks or PSPs. It generates
contextual behavioural + device risk signals before authorization and enables
adaptive / step-up authentication. The prototype implements exactly that.

---

## Bank-side lifecycle (why the demo is credible)

Every live payment is a **bank transaction with a lifecycle**, persisted to
`data/bank_tx.jsonl` (delete it to reset):

```
assess (round 1)  →  approved | step_up | blocked
challenge round   →  approved | blocked
operator          →  confirm_fraud (fraud report FR-…) | override_approve
customer app      →  report to bank (same as confirm_fraud)

switch leg (NPCI/UPI):
  approved / overridden  →  SETTLED with UTR + latency
  blocked / fraud_reported →  NOT SENT (never reached the switch)
  step_up (pending)      →  IN RISK REVIEW
```

`bank.py` owns this store, the **switch leg** (deterministic UTRs), and the
sample-day generator (`source='sample'` rows never appear in the payment
demo's own event log, so honest "live" telemetry stays clean).

`ops.py` owns the tunable **risk policy** (`data/policy.json`), the
**per-customer profiles** (`data/profiles.json` — seeded from the model's
benign distribution plus a hand-tuned senior baseline, then updated online
with Welford's algorithm whenever a customer's payment is approved), and the
**threshold-explorer replay** over the held-out validation set saved inside
`model/risk_model.json`.

## How the pieces map to the deck

| Deck claim | Where it lives in the prototype |
|---|---|
| SDK observes touch behaviour, interaction patterns | `web/app.js` — real capture of amount-entry timing/corrections and PIN taps (hold, offset, pauses, re-entries) |
| Screen-sharing / root-integrity indicators | "Simulated SDK detections" toggles + `screen_share`/`integrity_fail` flags; described for real Android in the roadmap |
| On-device / privacy-first: only derived signals leave | The wire payload contains **only the derived feature vector**, never raw streams (footer text in the UI) |
| Behaviour Engine + AI Risk Engine generate the score | `model/risk_model.json` (trained logistic regression) + `risk_engine.py` (scoring, explainability, policy) |
| Explainable risk score | `top_contributors` with measured value vs typical baseline and % share |
| Approve / Step-up / Block | `risk_engine.py` decision policy + the phone overlays |
| User profiles / risk history | `benign_profile` anomaly index (`profile_deviation`) + risk-event log persisted to `data/events.jsonl` |
| PostgreSQL / Redis (production) | prototype uses JSON + memory; schema maps 1:1 to PG tables / Redis short-lived state in the roadmap |
| Go/Rust backend, TFLite, Docker/K8s | deliberately *not* used in the prototype — see roadmap; the API contract is the stable seam |

---

## Honesty box — say this to judges

- **Bank console = demo simulation.** There is no real auth on `/bank`; the
  operator, customers, and the sample bank day are simulated and labelled as
  such. What is real: the SecureUPI assessment, the lifecycle, and the actions
  — that is the architecture the deck claims (risk signals in, PSP decides).


- **Synthetic training data.** The model was trained on generated sessions
  (everyday payments, screenshare-scam archetype, duress archetype, big-legit
  purchases) because labelled real behaviour is unavailable pre-pilot. Real
  data would come from opt-in PSP/bank pilots under regulatory review. We show
  the metrics (accuracy 98%, risk recall 100%, ~86–97% of normal payments stay
  LOW) and the calibration clearly in the model card and training report.
- **Web demo ≠ on-device SDK.** In the browser we simulate the derived features
  that a real Android SDK would produce. A mouse is mapped to touch-realistic
  offsets; scenario buttons stand in for scripted behaviour.
- **No overclaims.** The engine emits a risk *signal*; it is not "fraud
  detection", it cannot "know" someone is coerced, and enforcement decisions
  belong to the bank/PSP. (See the deck's own disclaimers — keep them.)
- **Thresholds are policy.** LOW/MEDIUM/HIGH cut-offs and the step-up block bar
  are tunable **live from the console** (⚙ Risk policy → validation replay
  shows the false-positive/catch-rate trade-off). The defaults live in
  `risk_engine.py`; a real PSP tunes them to its own risk budget.

---

## Roadmap from prototype → product

1. **Android SDK (Kotlin)** — real capture: `MotionEvent` streams during
   amount/PIN entry (timing, velocity, touch accuracy), app-lifecycle context,
   MediaProjection/accessibility/overlay detection for screen-share, Play
   Integrity + root checks, keys in Android Keystore, `FLAG_SECURE`.
2. **Export model to TensorFlow Lite** — the logistic-regression weights + scaler
   convert 1:1 to a `.tflite` file (the feature standardization is already in the
   JSON); keep the *same* 13-feature contract so on-device inference can return
   a compact risk signal with no behaviour leaving the phone.
3. **Risk service (Go)** behind the existing `/api/v1/assess` contract — add
   per-user profile persistence (PostgreSQL), short-lived session/rate-limit
   state (Redis), signed + TLS 1.3 payloads, ECDSA device attestation.
4. **Pilot** with a PSP sandbox on the NPCI test environment: measure real
   step-up rates, tune thresholds, collect opt-in labelled data to replace the
   synthetic training set, and iterate model + explainability.
5. **Regulatory review + enterprise rollout** (RBI digital-payments-security
   guidance, data-protection posture: derived features only, retention limits),
   then Docker/Kubernetes deployment and the B2B SaaS offering (SDK licence +
   support + security analytics) from the deck.

---

## Project layout

```
secureupi/
  README.md            ← this file
  server.py            ← zero-dependency demo server (static UI + API)
  risk_engine.py       ← feature schema, scoring, explainability, policy
  ops.py               ← risk-policy store, per-customer profiles, threshold explorer
  bank.py              ← bank transaction store + NPCI/UPI switch leg + sample day
  model/
    train.py           ← synthetic data generator + LR trainer (pure Python)
    risk_model.json    ← trained model + validation snapshot (generated)
    training_report.txt
  web/                 ← demo UI (plain HTML/CSS/JS, no build step)
    index.html · app.js · styles.css      ← payment demo (phone)
    bank.html · bank.js · bank.css        ← PSP operations console
  data/events.jsonl    ← runtime risk-event log (gitignored)
  data/bank_tx.jsonl   ← bank transactions (gitignored)
  data/policy.json     ← tuned risk policy (gitignored)
  data/profiles.json   ← learned per-customer baselines (gitignored)
```

Retrain model → `python model/train.py` · Re-run server → `python server.py`.
