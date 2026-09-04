# 🛡 NexHack 2.0 — SecureUPI

> **AI-powered, pre-authorization risk layer for UPI payments** — a working prototype for the **Smart India Hackathon** (Team SlothCode, DPG College).

SecureUPI is an AI security layer that sits **around** an existing UPI app and evaluates whether a payment looks risky **before** it is authorized — then lets the bank/PSP **approve, step-up, or block**. This repo contains the full working prototype plus the pitch deck.

<p align="left">
  <img alt="Python 3" src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white&style=flat">
  <img alt="Zero dependencies" src="https://img.shields.io/badge/dependencies-zero-2ea44f?style=flat">
  <img alt="UI" src="https://img.shields.io/badge/UI-vanilla%20HTML%2FCSS%2FJS-f1e05a?style=flat">
  <img alt="Status" src="https://img.shields.io/badge/status-working%20prototype-orange?style=flat">
  <img alt="Docs" src="https://img.shields.io/badge/docs-secureupi%2FREADME-blue?style=flat&logo=markdown">
  <img alt="Topic" src="https://img.shields.io/badge/Smart%20India%20Hackathon-NexHack%202.0-6f42c1?style=flat">
</p>

---

## Why it exists (the one-minute pitch)

Today a UPI transaction can succeed even when the *legitimate* user has been manipulated into paying a fraudster. SecureUPI adds **pre-authorization behavioural + device risk assessment**:

1. An SDK-style layer measures *how* you interact — amount-entry pacing, hesitations, corrections, tremor-like PIN taps, screen-share and device-integrity context.
2. A risk engine turns those derived signals into an **explainable 0–100 risk score**.
3. The PSP decides **approve / step-up / block** — enforcement stays with the bank.

It is an **SDK + backend risk engine for banks/PSPs** — *not* another UPI app. It never replaces the UPI PIN, NPCI, or the bank's own controls.

> ⚠️ Honest framing (we say this to judges too): SecureUPI does **not** "detect fraud" and cannot "know" someone is coerced. It generates contextual risk signals before authorization and enables adaptive/step-up authentication. The prototype implements exactly that — nothing more, nothing less.

---

## 🎬 Demo script for evaluators

The prototype is a two-screen demo: the **customer's phone UPI app** and the **PSP Operations Console** (the bank side). Everything below is live — no recordings, no hard-coded scores.

### Run it

```bash
cd secureupi
python server.py          # zero dependencies — no pip install, no venv, no npm
```

Then open two tabs:

| Page | URL | What you see |
|---|---|---|
| 📱 Payment demo (phone) | <http://127.0.0.1:8077> | A UPI app; six scenario buttons that **simulate real user behaviour** (paced typing, hesitations, corrections, tremor) |
| 🏦 PSP Operations Console | <http://127.0.0.1:8077/bank> | The bank ops desk: live transaction monitor, risk drill-down, NPCI/UPI-switch settlement, policy tuner |

*Act 0 — set the stage:* on the console press **"Load sample bank day"**, then run the scenarios on the phone — every attempt lands **live** in the console.

### The six scenarios (what judges should try)

| # | Scenario | Expected outcome |
|---|---|---|
| 1 | ☕ **Coffee ₹250 (calm)** | Score ~8–12 · **LOW → APPROVE instantly** |
| 2 | 👧 **Senior ₹450 (slow but smooth)** | Score ~50–60 · **STEP-UP → approve** after a calm re-entry — slow but *steady* typing is compared with the senior customer's **own baseline**, not the global average |
| 3 | 🌙 **2 AM ₹45,000 to a new payee** | **STEP-UP → approve** — big unusual payment gets friction, calm re-authentication clears it |
| 4 | 💀 **"Verify account" ₹50,000 scam** | Score ~100 · **STEP-UP → BLOCK** — screen-share active + dictated, hesitant PIN entry; the hard gate refuses even the second attempt |
| 5 | 👮 **Duress ₹40,000** | Score high · **BLOCK** after anxious re-entry — coercion signals even with no screen-share |
| 6 | 👋 **Try it yourself** | Type an amount and any 4-digit PIN (demo PIN: **7241**) — calm rhythm → approve; hesitation/tremor → step-up |

### The bank side (Act 3–6, on `/bank`)

- **Blocked payment → operator actions.** The console pops a review banner; the operator can **Confirm fraud** (issues an `FR-…` report, audit-trailed) or **Override** after verifying the customer. The phone's **"Report to bank"** button does the same from the customer side.
- **Settlement column shows the NPCI/UPI-switch leg end to end:** approved payments get a deterministic 12-digit **UTR** + mock round-trip latency; blocked ones are `not sent · pre-auth block` (never reached the switch); step-ups sit `in risk review`.
- **⚙ Risk policy tuner.** Drag the LOW/HIGH cut-offs and the step-up block bar **live**; a validation replay shows the honest trade-off (default: ~86% of normal payments auto-approve, 100% of the held-out high-risk set is caught at ≥ step-up). Save applies server-side — the next payment on the phone uses the new thresholds.
- **Per-customer profiles.** Switch the persona dropdown (Aarav — fast; Ramesh — slow-but-smooth senior): each customer's typing is judged against *their own* learned history (Welford online updates), and the console shows each customer's step-up rate and blocked count.
- **Tap any row** for the drill-down: both SecureUPI rounds (scores, explainable risk drivers, derived signals, profile deviation) and the full audit timeline. KPIs update live: payments monitored, ₹ protected by blocks, step-up clear rate, reports filed.

**"Why did it block?"** — point at the screen: each score breaks down into per-factor % share, measured value vs. the customer's typical baseline, and the policy rules that fired.

---

## What's in the repo

| Item | Description |
|---|---|
| `SecureUPI_SIH_Presentation.pptx` | Final pitch deck |
| `SentinelUPI_SIH_Presentation.pptx` | Template/branding variant of the same deck |
| `secureupi/` | **Working prototype** — zero-dependency risk engine, phone UPI-pay demo, and PSP operations console |

### How the prototype maps to the deck claims

| Deck claim | Where it lives |
|---|---|
| SDK observes touch behaviour & interaction patterns | `web/app.js` — real capture of amount-entry timing/corrections and PIN taps |
| Screen-share / root-integrity indicators | Simulated SDK-detection toggles → `screen_share` / `integrity_fail` flags |
| On-device, privacy-first: only derived signals leave | wire payload carries only the derived feature vector, never raw streams |
| AI Risk Engine generates an explainable score | `model/risk_model.json` (trained logistic regression) + `risk_engine.py` |
| Approve / Step-up / Block | `risk_engine.py` decision policy + the phone overlays |
| Risk history, behavioural profiles, policy | `ops.py`, `bank.py` — risk-event log, per-customer baselines, tunable thresholds |

**Full documentation** — API contract, complete demo walkthrough, deck→code map, honesty box, and the prototype→product roadmap — lives in **[`secureupi/README.md`](secureupi/README.md)**.

---

## Technical snapshot

- **Backend:** pure Python standard library (`http.server` + JSON) — no packages, works offline.
- **Model:** logistic regression trained by `secureupi/model/train.py` on synthetic sessions (everyday, screen-share scam, duress, big-legit archetypes); weights + scaler exported as JSON, validated on a held-out set (model card + training report included).
- **Frontend:** plain HTML/CSS/JS — no build step.
- **Runtime state:** risk events, bank transactions, policy, and profiles persist to JSONL/JSON under `secureupi/data/` (gitignored; delete to reset).
- **Why not Django/React/Go/TFLite yet?** Deliberately. The prototype is the *contract*; the roadmap (Android SDK, TFLite export, Go risk service, PostgreSQL/Redis) is in `secureupi/README.md`.

---

*Team SlothCode · Smart India Hackathon (NexHack 2.0) — prototype demo. SecureUPI generates contextual risk signals before authorization; it does not detect fraud, does not replace the UPI PIN, and enforcement stays with the PSP/bank.*
