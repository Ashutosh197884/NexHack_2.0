# 🗺 SecureUPI — Roadmap (prototype → product)

SecureUPI is an **AI-powered, pre-authorization risk layer for UPI payments**: it
measures *how* a payment is made (amount-entry pacing, PIN rhythm, screen-share /
device-integrity context) and gives the PSP/bank an explainable **approve /
step-up / block** recommendation **before** authorization.

This repo is the **Smart India Hackathon working prototype** — zero-dependency
Python risk engine + web demo. The roadmap below is how the same architecture
becomes a deployable SDK + risk service for banks and PSPs.

> North-star guardrails for every phase:
> - **Privacy by design** — raw touch/behaviour streams never leave the device;
>   only the derived feature vector is transmitted (TLS 1.3, signed).
> - **Enforcement stays with the PSP** — SecureUPI is a *signal*, not a fraud
>   verdict, and never replaces the UPI PIN, NPCI, or bank controls.
> - **No overclaims** — we publish thresholds, model cards, and honest limits.

---

## Phase 0 — Working prototype (this repo) ✅

The current demo proves the full signal path end-to-end:

```
customer app → SDK-style capture → derived feature vector
            → risk engine (logistic regression + policy rules)
            → explainable 0–100 score → APPROVE / STEP-UP / BLOCK
            → PSP console: lifecycle, switch settlement, operator actions
```

| Done | Details |
|---|---|
| Behavioural + device risk scoring | `risk_engine.py` + trained `model/risk_model.json` (acc 98.1%, risk recall 100%) |
| Explainability | per-factor % share, measured value vs. the customer's own baseline |
| Step-up flow | two-round assessment; a calm re-entry clears friction, an anxious one blocks |
| Bank/PSP console | live monitor, fraud confirm / override, deterministic NPCI UTRs |
| Policy tuning | live LOW/HIGH/step-up cut-offs + honest validation replay |
| Per-customer profiles | learned online (Welford) so slow-but-smooth seniors aren't false-flagged |

## Phase 1 — Android SDK (Kotlin)

Real on-device capture replacing the browser simulation:

- `MotionEvent` streams during amount + PIN entry → timing, velocity, touch
  accuracy (the derived features stay on-device).
- App-lifecycle context; MediaProjection / accessibility / overlay detection
  for screen-share flags.
- Play Integrity + root checks → `integrity_fail`; keys in Android Keystore;
  `FLAG_SECURE` on sensitive screens.

**Exit criteria:** SDK emits the same 13-feature contract as the prototype and
runs a reference UPI-like app through the demo scenarios on real hardware.

## Phase 2 — On-device inference (TensorFlow Lite)

- Export the logistic-regression weights + scaler to `.tflite` (1:1 conversion,
  the feature standardization is already in the JSON).
- On-device inference returns a compact risk signal — **no behaviour leaves the
  phone** even at inference time; only the score/features cross the wire.

**Exit criteria:** byte-identical risk scores between Python and TFLite on the
held-out validation set.

## Phase 3 — Risk service (Go) behind the existing API contract

The `/api/v1/assess` contract is the stable seam:

- Go service with per-user profile persistence (PostgreSQL — the JSON store maps
  1:1 to PG tables) and short-lived session/rate-limit state (Redis).
- Signed + TLS 1.3 payloads, ECDSA device attestation, audit logging.

**Exit criteria:** same demo flow runs against the Go service with the UI
unchanged.

## Phase 4 — PSP sandbox pilot (NPCI test environment)

- Integrate with a PSP on the NPCI **test** switch; measure real step-up rates
  and friction.
- Tune the risk policy to the PSP's risk budget using the threshold-explorer
  replay (already in the console).
- Collect **opt-in labelled data** (with regulatory review) to replace the
  synthetic training set and re-train model + explainability.

## Phase 5 — Regulatory review & enterprise rollout

- Map to RBI digital-payments-security guidance and India's data-protection
  posture (derived features only, retention limits, deletion workflows).
- Containerize (Docker/Kubernetes), add observability, and offer the **B2B
  SaaS** from the pitch deck: SDK licence + support + security analytics.

---

## How to help

The prototype's honesty box (in [`secureupi/README.md`](secureupi/README.md))
is the place to start — especially if you're a PSP/bank engineer who can
pressure-test the feature contract or share de-identified behavioural data
under an opt-in pilot.

*Phase 0 lives in this repo; everything else is intentionally *not* built here —
the demo is the contract, not the product.*
