# Yozigo Movie Tickets

A single-screen movie booking app built with React, TypeScript, Vite, FastAPI, and SQL. Customers can browse movies, choose seats, hold up to six seats for five minutes, run a simulated payment, and review bookings. Cinema staff can manage movies, shows, and bookings.

## Database and deployment layout

- **Local development:** SQLite at `backend/movie_tickets.sqlite3` by default. The file is created on first API startup.
- **Vercel production:** PostgreSQL through `DATABASE_URL` (a pooled Neon or other managed PostgreSQL connection string). Serverless function files are temporary, so SQLite is only for local use.
- Versioned migrations in `backend/migrations/` create the matching schema for either database. Seat claims have a unique `(show_id, seat_label)` key; holds and booking conversions run in a transaction. PostgreSQL writes use an advisory lock so simultaneous seat requests across function instances are serialized.
- Vercel Services deploy the Vite frontend and FastAPI backend separately under one domain. `/api/*` routes to FastAPI; other paths route to the frontend. The seat picker refreshes availability every three seconds.

## Run locally

Prerequisites: Python 3.10+, Node.js 20.19+ or 22.12+, and npm.

1. Copy `.env.example` to `.env` and set `JWT_SECRET` to a private random value of at least 32 characters. Leave `DATABASE_URL` empty for SQLite.

   ```powershell
   Copy-Item .env.example .env
   # Edit .env and replace the JWT_SECRET placeholder.
   ```

2. Install and start the API:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python seed.py
   python -m uvicorn app:app --reload --port 8000
   ```

3. In a second terminal, install and start the frontend from `frontend/`:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

   Open `http://localhost:5173`. The Vite dev server proxies `/api` to the API on port 8000.

The local seed creates these evaluation accounts:

- Customer: `customer@example.com` / `Customer123!`
- Administrator: `admin@example.com` / `Admin123!`

It also creates two sample movies and upcoming shows. These predictable credentials are for local evaluation only; production seeding requires an administrator password supplied through environment variables.

## Deploy to Vercel

1. Set the Vercel project Framework Preset to **Services**. Keep this repository root as the project root. `vercel.json` defines a Vite frontend service in `frontend/` and a FastAPI service in `backend/`.
2. Connect a managed PostgreSQL database (the Neon Marketplace resource is already attached to this project). Confirm `DATABASE_URL` is available to the backend service.
3. Set a newly generated `JWT_SECRET` in Vercel Production Environment Variables. Do not reuse the local secret.
4. Run `vercel --prod` from the repository root. FastAPI applies the PostgreSQL migration on startup. Seed an initial admin and sample catalog once if the database is empty.
5. For initial production seeding, set `DATABASE_URL`, `INITIAL_ADMIN_EMAIL`, and `INITIAL_ADMIN_PASSWORD` in a secure local shell, then run:

   ```powershell
   cd backend
   python -m pip install -r requirements.txt
   python seed.py
   ```

   Use an admin password of at least 12 characters. Customers can register through the app. Keep production values out of source control and chat.

## Realtime seat availability

The seat picker polls the API every three seconds, so holds, releases, and bookings from other sessions appear shortly after they happen. Vercel Functions also support streaming/SSE, but this app does not need a long-lived WebSocket for the assignment seat map. The database transaction and unique seat claim remain authoritative when two customers choose at nearly the same time.

## Tests and build

Run backend integration tests from `backend/`:

```powershell
python -m unittest -v
```

Build the frontend from `frontend/`:

```powershell
cd frontend
npm run build
```

## Scope notes

- Payment is simulated; no real payment processor is connected.
- Optional cancellation and aggregate occupancy/revenue reports are not implemented.
- Local SQLite and production PostgreSQL share the same schema and booking rules.
