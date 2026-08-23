# LedgerLens

**Evidence-First AI Finance Controller**
Razorpay AI Buildathon 2026 — Track 04

> Build an agent that closes one finance-ops loop across a 50+ record synthetic batch,
> reporting match rate, measured accuracy, throughput, and unresolved exceptions.

---

## Architecture

```
Payment → Settlement → Bank → Ledger reconciliation
```

Three levels of intelligence:
1. **Deterministic** — exact ID/amount/currency/date matching
2. **Statistical** — fuzzy/probabilistic matching
3. **Agentic** — LLM investigates only what deterministic logic cannot resolve

The LLM is never the source of financial truth.

---

## Project Structure

```
ledgerlens/
├── backend/          Python · FastAPI · Pydantic · PostgreSQL
├── frontend/         React · TypeScript · Vite
├── data/
│   ├── synthetic/    Generated test batches (ground truth included)
│   └── ground_truth/ Evaluation labels
├── scripts/          Developer utilities
├── .env.example      Root env template — copy to .env for Docker Compose
├── docker-compose.yml
└── AGENTS.md         Engineering rules — read this first
```

---

## Local Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker + Docker Compose

### 1. Environment variables

```bash
# Root .env — required for docker-compose (PostgreSQL password)
cp .env.example .env

# Backend .env — required for the FastAPI app (DATABASE_URL)
cp backend/.env.example backend/.env
```

Open both `.env` files and replace every `CHANGE_ME` with a real value.
Use the **same password** in both files.

> ⚠️ Never commit `.env` files. They are git-ignored.

### 2. Backend

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install ".[dev]"

# Start the development server
uvicorn app.main:app --reload --port 8000
```

Health check: http://localhost:8000/health
API docs:     http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:5173

### 4. Database (Docker)

```bash
# Ensure root .env exists and POSTGRES_PASSWORD is set (step 1 above)
docker compose up -d postgres
```

PostgreSQL listens on `127.0.0.1:5432` (localhost only).

### 5. Tests

```bash
cd backend
pytest tests/ -v
```

---

## Engineering Rules

See [AGENTS.md](./AGENTS.md) — all contributors must read this.

---

## Phase Status

- [x] Phase 0 — Repository setup & Git sync
- [x] Phase 1 — Project foundation skeleton
- [x] Phase 2 — Synthetic data generator + domain models
- [ ] Phase 3 — Deterministic reconciliation engine
- [ ] Phase 4 — Agent investigation layer
- [ ] Phase 5 — Frontend dashboard
