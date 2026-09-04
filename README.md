# 🛡 NexHack 2.0 — SecureUPI (Smart India Hackathon)

**SecureUPI is an AI-powered security layer that sits *around* an existing UPI
app and evaluates whether a payment looks risky *before* it is authorized** —
then lets the bank/PSP **approve, step-up, or block**.

This repo contains the SIH working prototype plus the pitch deck:

| Item | Description |
|---|---|
| `SecureUPI_SIH_Presentation.pptx` | Final pitch deck (Team SlothCode, DPG College) |
| `SentinelUPI_SIH_Presentation.pptx` | Template/branding variant of the same deck |
| `secureupi/` | **Working prototype** — zero-dependency (pure Python stdlib + plain HTML/CSS/JS) risk engine, phone UPI-pay demo, and PSP operations console |

## The idea in one line

Today a UPI transaction can succeed even when the *legitimate* user has been
manipulated into paying a fraudster. SecureUPI adds **pre-authorization
behavioural + device risk assessment**: an on-device-style SDK measures how you
enter the amount and PIN (pacing, hesitations, tremor-like taps, screen-share
and integrity context), a risk engine turns that into an explainable 0–100
score, and the PSP decides **approve / step-up / block**. It is an SDK +
backend risk engine for banks/PSPs — *not* another UPI app, and it never
replaces the UPI PIN, NPCI, or the bank's own controls.

## Run the prototype

```bash
cd secureupi
python server.py          # serves on http://127.0.0.1:8077
```

- **Payment demo** — `http://127.0.0.1:8077/` — run the six behaviour
  scenarios (coffee → approve, senior → step-up → approve, “verify account”
  scam → block, …).
- **PSP Operations Console** — `http://127.0.0.1:8077/bank` — live transaction
  monitor, SecureUPI risk drill-down, NPCI/UPI-switch settlement (UTRs),
  operator actions (confirm fraud / override), a live risk-policy tuner, and
  per-customer behavioural profiles.

Full documentation (API, demo script, deck→code mapping, honesty box, product
roadmap): **[`secureupi/README.md`](secureupi/README.md)**.

---

*Team SlothCode · Smart India Hackathon — prototype demo. SecureUPI generates
contextual risk signals before authorization; it does not detect fraud,
does not replace the UPI PIN, and enforcement stays with the PSP/bank.*
