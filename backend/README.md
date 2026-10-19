# SecureUPI backend — FastAPI (Sprint 1 vertical slice)

The plan's §10 architecture, implementing the §8 API contract over the §7
database schema, with the proven prototype risk engine (`../secureupi/`) as the
scoring core behind a clean interface.

## Requirements

- Python 3.13+ (developed on 3.14)
- pip deps: see `requirements.txt`

## Run it

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010        # from backend/
```

- Health:      `GET http://127.0.0.1:8010/api/v1/health`
- API docs:    `http://127.0.0.1:8010/docs` (interactive OpenAPI)
- Sample QRs:  `GET /api/v1/qr/samples` (+ `/samples/{id}/image.svg`)

Demo users are seeded on first boot (both use password `secureupi-demo`):
`demo@secureupi.app` and `senior@secureupi.app`. Each arrives with a couple of
known recipients and transactions so history-based rules have context.

## Frontend

The React + TS + Tailwind app lives in `../frontend`. Dev server proxies
`/api/*` to `127.0.0.1:8010`:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Quickest end-to-end demo: sign in with a demo account, click *Use payload* on
the Coffee House QR → *Analyze risk* → low/approve → *Proceed to (simulated)
payment*. Then try the ₹48,000 personal-VPA QR for the high-risk path.

Switching to PostgreSQL: set `SECUREUPI_DATABASE_URL=postgresql+psycopg://…`
before the first boot.

## Configuration (env vars)

| Variable | Purpose | Default |
|---|---|---|
| `SECUREUPI_DATABASE_URL` | sqlite / postgres URL | `sqlite:///backend/secureupi.db` |
| `SECUREUPI_JWT_SECRET` | JWT signing secret (set in production!) | random per-boot |
| `SECUREUPI_JWT_TTL_MINUTES` | token lifetime | 240 |
| `SECUREUPI_CORS_ORIGINS` | comma list of allowed origins | local dev origins |
| `SECUREUPI_SEED_DEMO_USERS` | seed demo accounts | 1 |
| `SECUREUPI_RATE_LIMIT_PER_MIN` | per-IP API calls/minute | 120 |

## Tests

```bash
python -m pytest backend/tests -q
```

41 tests cover the §12 matrix: QR parsing (valid/malformed/missing fields/
unexpected params), risk-engine fusion (calm/known → low, new+large → high,
no-capture → neutral, suspicious structure), and the API/security boundaries
(401s, ownership isolation, schema validation, duplicate simulation rejection).

## Architecture map (plan § → code)

| Plan | Code |
|---|---|
| §6.1 QR intelligence | `app/services/qr_parser.py`, `qr_generator.py` |
| §6.2/6.3 Feature engine + risk fusion | `app/services/risk_engine.py` (transactional rules) + `../secureupi/risk_engine.py` (behavioural model) |
| §6.4 Explainability | reasons[] in `/risk/assess` response, persisted as `risk_factors` |
| §7 Database | `app/models.py` (six tables) |
| §8 API contract | `app/api/v1/*` |
| §10 optional ML seam | `app/ml/inference.py` (loads `../secureupi/model/risk_model.json`) |
| §11 security | PBKDF2 + JWT (`app/core/security.py`), ownership checks, rate limiter, CORS, Pydantic input caps |
