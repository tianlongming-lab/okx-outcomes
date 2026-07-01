# OKX Outcomes

This repository contains a FastAPI backend (backend/) and a React + Vite frontend (frontend/).
The `add-frontend` branch includes the frontend scaffold so you can download and run the full platform locally.

Quick start (development):

1. Backend

- Create a virtualenv and install requirements:

  python -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt

- Copy `.env.example` to `.env` and fill in OKX credentials if you want order placement and signing.

- Start backend:

  uvicorn backend.main:app --reload --port 8080

2. Frontend (dev server)

- Install frontend deps:

  cd frontend
  npm install
  npm run dev

- Vite dev server proxies `/api` and `/ws` to backend (http://localhost:8080)

3. Build frontend for production and serve with backend

- Build frontend:

  cd frontend
  npm run build

- Copy build output into backend static dir (one simple option):

  # in frontend/dist run
  cp -r * ../frontend/

- Start backend and open http://localhost:8080

Notes:
- If you plan to use EIP-712 agent signing you must set `OKX_AGENT_PRIVATE_KEY` in `.env` and ensure `eth-account` and `eth-utils` are installed in backend environment.
- The FastAPI app mounts `frontend/` as static files when it exists (see backend/main.py).

