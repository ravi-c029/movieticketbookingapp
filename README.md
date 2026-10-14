# Yozigo Movie Tickets

A single-screen movie ticket booking app built with React, TypeScript, Vite, FastAPI, and SQL. Customers can browse movies, choose seats, hold up to six seats for five minutes, run a simulated payment, and review bookings. Cinema staff can manage movies, shows, and bookings.

## Database and deployment layout

- **Local development:** SQLite at `backend/movie_tickets.sqlite3` by default. The file is created on first API startup.
- **Vercel production:** PostgreSQL through `DATABASE_URL` (a pooled Neon or other managed PostgreSQL connection string). Vercel function files are temporary, so SQLite is only for local use.
- The versioned migrations in `backend/migrations/` create the matching schema for either database. Seat claims have a unique `(show_id, seat_label)` key; holds and booking conversions run in a transaction. PostgreSQL writes use an advisory lock so simultaneous seat requests across function instances are serialized.
- The Vite app and FastAPI backend deploy together. Vercel serves the React build and invokes FastAPI as a Python Function. Seat availability is refreshed every three seconds while the seat picker is open.

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

3. In a second terminal at the project root, install and start the frontend:

   ```powershell
   npm install
   npm run dev
   ```

   Open `http://localhost:5173`. Vite proxies `/api` to the API on port 8000.

The local seed creates these evaluation accounts:

- Customer: `customer@example.com` / `Customer123!`
- Administrator: `admin@example.com` / `Admin123!`

It also creates two sample movies and upcoming shows. These predictable credentials are for local evaluation only; production seeding uses an administrator password supplied through environment variables.

## Deploy to Vercel

1. Install the Vercel CLI (`npm install -g vercel` if needed), sign in with `vercel login`, then run `vercel` from the project root and follow the prompts to create the project. Keep the project root as the Vercel root directory.
2. In the linked Vercel project, create a managed PostgreSQL database (for example Neon from the Vercel Marketplace) and copy its pooled connection URL.
3. In Vercel Project Settings → Environment Variables, set:
   - `DATABASE_URL`: pooled PostgreSQL URL, including SSL options provided by the database provider.
   - `JWT_SECRET`: a newly generated random secret of at least 32 characters. Do not reuse the local secret.
4. Run `vercel --prod` from the project root. FastAPI applies the PostgreSQL migration on startup. The application will have no movies or admin account until the initial seed is run once.
5. For the initial production seed, set `DATABASE_URL`, `JWT_SECRET`, `INITIAL_ADMIN_EMAIL`, and `INITIAL_ADMIN_PASSWORD` in a secure local shell from the Vercel and database dashboards. Use an admin password of at least 12 characters, then run:

   ```powershell
   cd backend
   python -m pip install -r requirements.txt
   python seed.py
   ```

   This creates the initial admin account and sample movie/show catalog; customers can register through the app. Keep these production values out of source control and chat. Redeploy is not needed after seeding.

This workspace is not linked to a Vercel project yet. Once the project and database are connected to your account and environment variables are set, `vercel --prod` creates the public deployment URL. Do not configure a Vercel serverless deployment with a local SQLite file; its writes would not be durable between invocations.

## Realtime seat availability

The seat picker polls the API every three seconds. It updates held, released, and booked seats across sessions without maintaining a long-lived server process. Vercel Functions support streaming/SSE as well, but this app does not need a persistent WebSocket connection for the assignment's seat map. The database transaction and unique seat claim remain the authority when two customers choose at nearly the same time.

## Tests and build

Run backend integration tests from `backend/`:

```powershell
python -m unittest -v
```

Build the frontend from the repository root:

```powershell
npm run build
```

## Scope notes

- Payment is simulated; no real payment processor is connected.
- Optional cancellation and aggregate occupancy/revenue reports are not implemented.
- Local SQLite and production PostgreSQL share the same schema and booking rules.
