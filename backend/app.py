from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator


ROOT = Path(__file__).resolve().parent
for _line in (ROOT.parent / ".env").read_text(encoding="utf-8").splitlines() if (ROOT.parent / ".env").exists() else []:
    _key, _separator, _value = _line.partition("=")
    _key = _key.strip().lstrip("\ufeff")
    if _separator and _key and not _key.startswith("#"):
        os.environ.setdefault(_key, _value.strip().strip("'\""))
DB_PATH = Path(os.environ.get("DATABASE_PATH", ROOT / "movie_tickets.sqlite3"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
JWT_SECRET = os.environ.get("JWT_SECRET", "")
TOKEN_SECONDS = 60 * 60 * 24
HOLD_SECONDS = 5 * 60
ROWS = "ABCDEFGH"
SEATS = [f"{row}{number}" for row in ROWS for number in range(1, 11)]
SEAT_COUNT = len(SEATS)
WRITE_LOCK_KEY = 881273


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A timezone is required")
    return parsed.astimezone(timezone.utc)


class PostgresConnection:
    def __init__(self, connection: Any):
        self.connection = connection

    @staticmethod
    def _sql(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> Any:
        return self.connection.execute(self._sql(query), parameters)

    def executemany(self, query: str, parameters: list[tuple[Any, ...]]) -> Any:
        return self.connection.cursor().executemany(self._sql(query), parameters)

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> PostgresConnection:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool | None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return None


def connect() -> Any:
    if USE_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row

        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
        return PostgresConnection(raw)
    conn = sqlite3.connect(DB_PATH if DB_PATH.is_absolute() else ROOT / DB_PATH, timeout=15, isolation_level=None, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool | None:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


@contextmanager
def transaction(lock_key: int | None = None) -> Iterator[Any]:
    conn = connect()
    try:
        conn.execute("BEGIN" if USE_POSTGRES else "BEGIN IMMEDIATE")
        if USE_POSTGRES and lock_key is not None:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (lock_key,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    if not USE_POSTGRES:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        migration = "001_postgres.sql" if USE_POSTGRES else "001_initial.sql"
        applied = conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (migration,)).fetchone()
        if not applied:
            if USE_POSTGRES:
                conn.execute("SELECT pg_advisory_xact_lock(?)", (99183017,))
                applied = conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (migration,)).fetchone()
                if not applied:
                    sql = (ROOT / "migrations" / migration).read_text(encoding="utf-8")
                    conn.executescript(sql)
                    conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES(?,?) ON CONFLICT(version) DO NOTHING", (migration, iso(utc_now())))
                conn.commit()
            else:
                sql = (ROOT / "migrations" / migration).read_text(encoding="utf-8")
                conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nINSERT INTO schema_migrations(version, applied_at) VALUES('{migration}', '{iso(utc_now())}');\nCOMMIT;")
    finally:
        conn.close()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(derived)}"


def check_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = _b64(hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt + "=="), int(rounds)))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def issue_token(user: sqlite3.Row) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": user["id"], "role": user["role"], "exp": int(time.time()) + TOKEN_SECONDS}, separators=(",", ":")).encode())
    signed = f"{header}.{payload}"
    signature = _b64(hmac.new(JWT_SECRET.encode(), signed.encode(), hashlib.sha256).digest())
    return f"{signed}.{signature}"


def current_user(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        token = authorization[7:]
        head, payload, signature = token.split(".")
        signed = f"{head}.{payload}"
        expected = _b64(hmac.new(JWT_SECRET.encode(), signed.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
        if int(claims["exp"]) <= int(time.time()) or not claims.get("sub"):
            raise ValueError
        with connect() as conn:
            row = conn.execute("SELECT id, name, email, role FROM users WHERE id=?", (claims["sub"],)).fetchone()
        if not row or row["role"] != claims.get("role"):
            raise ValueError
        return dict(row)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token") from exc


def require_admin(user: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


class RegisterInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[-1] or any(char.isspace() for char in normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[-1] or any(char.isspace() for char in normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class HoldInput(BaseModel):
    seats: list[str] = Field(min_length=1, max_length=6)


class PaymentInput(BaseModel):
    outcome: str

    @field_validator("outcome")
    @classmethod
    def valid_outcome(cls, value: str) -> str:
        if value not in {"success", "failure"}:
            raise ValueError("Outcome must be success or failure")
        return value


class MovieInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    poster_url: str = ""
    language: str = Field(min_length=1, max_length=60)
    duration_minutes: int = Field(gt=0, le=600)
    rating: str
    description: str = ""

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, value: str) -> str:
        if value not in {"U", "UA", "A"}:
            raise ValueError("Rating must be U, UA or A")
        return value


class ShowInput(BaseModel):
    movie_id: str
    starts_at: str
    ticket_price: int = Field(gt=0)


def movie_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


app = FastAPI(title="Yozigo Movie Tickets API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","), allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])


def provision_initial_admin() -> None:
    email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    if not email and not password:
        return
    if not email or len(password) < 12:
        raise RuntimeError("Set both INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD (at least 12 characters)")

    with transaction(lock_key=99183018 if USE_POSTGRES else None) as conn:
        existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        password_hash = hash_password(password)
        if existing:
            conn.execute("UPDATE users SET name=?,password_hash=?,role='admin' WHERE id=?", ("Cinema Admin", password_hash, existing["id"]))
        else:
            conn.execute("INSERT INTO users(id,name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), "Cinema Admin", email, password_hash, "admin", iso(utc_now())))


@app.on_event("startup")
def startup() -> None:
    if len(JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters; copy .env.example to .env")
    if os.environ.get("VERCEL_ENV") in {"production", "preview"} and not USE_POSTGRES:
        raise RuntimeError("DATABASE_URL must point to PostgreSQL on Vercel; serverless files are not persistent")
    initialize_database()
    provision_initial_admin()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterInput) -> dict[str, Any]:
    try:
        with transaction() as conn:
            user_id = str(uuid.uuid4())
            conn.execute("INSERT INTO users(id,name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (user_id, body.name, str(body.email).lower(), hash_password(body.password), "customer", iso(utc_now())))
            user = conn.execute("SELECT id,name,email,role FROM users WHERE id=?", (user_id,)).fetchone()
        return {"token": issue_token(user), "user": dict(user)}
    except Exception as exc:
        if not isinstance(exc, sqlite3.IntegrityError) and exc.__class__.__name__ not in {"IntegrityError", "UniqueViolation"}:
            raise
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc


@app.post("/api/auth/login")
def login(body: LoginInput) -> dict[str, Any]:
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=?", (str(body.email).lower(),)).fetchone()
    if not user or not check_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"token": issue_token(user), "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}


@app.post("/api/auth/logout")
def logout(_: dict[str, str] = Depends(current_user)) -> dict[str, str]:
    return {"message": "Logged out"}


@app.get("/api/movies")
def list_movies() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM movies ORDER BY title").fetchall()
        return [movie_dict(row) for row in rows]


@app.get("/api/movies/{movie_id}")
def get_movie(movie_id: str) -> dict[str, Any]:
    with connect() as conn:
        movie = conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        now = iso(utc_now())
        shows = conn.execute("""SELECT s.*, m.duration_minutes,
            ?-(SELECT COUNT(*) FROM seat_claims sc
                WHERE sc.show_id=s.id AND (sc.booking_id IS NOT NULL OR sc.expires_at>?)) AS available_seats
            FROM shows s JOIN movies m ON m.id=s.movie_id
            WHERE s.movie_id=? AND s.starts_at>? ORDER BY s.starts_at""", (SEAT_COUNT, now, movie_id, now)).fetchall()
    return {"movie": movie_dict(movie), "shows": [movie_dict(row) for row in shows]}


@app.get("/api/shows/{show_id}/seats")
def seat_map(show_id: str) -> dict[str, Any]:
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        show = conn.execute("SELECT s.*,m.title FROM shows s JOIN movies m ON m.id=s.movie_id WHERE s.id=?", (show_id,)).fetchone()
        if not show:
            raise HTTPException(status_code=404, detail="Show not found")
        now = iso(utc_now())
        conn.execute("DELETE FROM seat_claims WHERE show_id=? AND expires_at IS NOT NULL AND expires_at<=?", (show_id, now))
        rows = conn.execute("SELECT seat_label,hold_id,booking_id FROM seat_claims WHERE show_id=?", (show_id,)).fetchall()
    claims = {row["seat_label"]: ("booked" if row["booking_id"] else "held") for row in rows}
    return {"show": dict(show), "seats": [{"label": seat, "status": claims.get(seat, "available")} for seat in SEATS]}


@app.post("/api/shows/{show_id}/holds", status_code=201)
def create_hold(show_id: str, body: HoldInput, user: dict[str, str] = Depends(current_user)) -> dict[str, Any]:
    if len(set(body.seats)) != len(body.seats):
        raise HTTPException(status_code=422, detail="Seat list contains duplicates")
    invalid = sorted(set(body.seats) - set(SEATS))
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid seat: {invalid[0]}")
    seats = sorted(body.seats, key=lambda label: (label[0], int(label[1:])))
    now = utc_now()
    expires = iso(now + timedelta(seconds=HOLD_SECONDS))
    hold_id = str(uuid.uuid4())
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        show = conn.execute("SELECT * FROM shows WHERE id=?", (show_id,)).fetchone()
        if not show:
            raise HTTPException(status_code=404, detail="Show not found")
        conn.execute("DELETE FROM seat_claims WHERE show_id=? AND expires_at IS NOT NULL AND expires_at<=?", (show_id, iso(now)))
        conflict = conn.execute(f"SELECT seat_label FROM seat_claims WHERE show_id=? AND seat_label IN ({','.join('?' for _ in seats)}) LIMIT 1", (show_id, *seats)).fetchone()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Seat {conflict['seat_label']} is no longer available")
        conn.execute("INSERT INTO holds(id,user_id,show_id,expires_at,created_at,status) VALUES(?,?,?,?,?,'active')", (hold_id, user["id"], show_id, expires, iso(now)))
        conn.executemany("INSERT INTO seat_claims(show_id,seat_label,hold_id,booking_id,expires_at) VALUES(?,?,?,NULL,?)", [(show_id, seat, hold_id, expires) for seat in seats])
    return {"id": hold_id, "show_id": show_id, "seats": seats, "expires_at": expires, "ticket_price": show["ticket_price"], "total": show["ticket_price"] * len(seats)}


@app.get("/api/holds/{hold_id}")
def inspect_hold(hold_id: str, user: dict[str, str] = Depends(current_user)) -> dict[str, Any]:
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        hold = conn.execute("SELECT * FROM holds WHERE id=?", (hold_id,)).fetchone()
        if not hold or hold["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Hold not found")
        hold_status = hold["status"]
        if hold_status == "active" and hold["expires_at"] <= iso(utc_now()):
            conn.execute("UPDATE holds SET status='expired' WHERE id=?", (hold_id,))
            conn.execute("DELETE FROM seat_claims WHERE hold_id=?", (hold_id,))
            hold_status = "expired"
        seats = [row["seat_label"] for row in conn.execute("SELECT seat_label FROM seat_claims WHERE hold_id=? ORDER BY seat_label", (hold_id,))]
    return {"id": hold_id, "show_id": hold["show_id"], "expires_at": hold["expires_at"], "status": hold_status, "seats": seats}


@app.post("/api/holds/{hold_id}/payment")
def pay(hold_id: str, body: PaymentInput, user: dict[str, str] = Depends(current_user)) -> dict[str, Any]:
    now = utc_now()
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        hold = conn.execute("SELECT h.*,s.ticket_price FROM holds h JOIN shows s ON s.id=h.show_id WHERE h.id=?", (hold_id,)).fetchone()
        if not hold or hold["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Hold not found")
        if hold["status"] != "active":
            raise HTTPException(status_code=409, detail="This hold is no longer active")
        if hold["expires_at"] <= iso(now):
            conn.execute("UPDATE holds SET status='expired' WHERE id=? AND status='active'", (hold_id,))
            conn.execute("DELETE FROM seat_claims WHERE hold_id=?", (hold_id,))
            conn.commit()
            raise HTTPException(status_code=409, detail="This hold has expired. Please select seats again.")
        seats = [row["seat_label"] for row in conn.execute("SELECT seat_label FROM seat_claims WHERE hold_id=? ORDER BY seat_label", (hold_id,))]
        if not seats:
            raise HTTPException(status_code=409, detail="Seats are no longer held")
        amount = hold["ticket_price"] * len(seats)
        payment_id = str(uuid.uuid4())
        if body.outcome == "failure":
            conn.execute("INSERT INTO payments(id,hold_id,booking_id,outcome,amount,created_at) VALUES(?,?,NULL,'failure',?,?)", (payment_id, hold_id, amount, iso(now)))
            return {"status": "failed", "message": "Payment failed. Your seats remain held while the timer is running.", "expires_at": hold["expires_at"]}
        booking_id = str(uuid.uuid4())
        conn.execute("INSERT INTO bookings(id,user_id,show_id,amount,status,created_at) VALUES(?,?,?,?,'confirmed',?)", (booking_id, user["id"], hold["show_id"], amount, iso(now)))
        conn.executemany("INSERT INTO booking_seats(booking_id,seat_label) VALUES(?,?)", [(booking_id, seat) for seat in seats])
        conn.execute("UPDATE seat_claims SET hold_id=NULL,booking_id=?,expires_at=NULL WHERE hold_id=?", (booking_id, hold_id))
        conn.execute("UPDATE holds SET status='converted' WHERE id=?", (hold_id,))
        conn.execute("INSERT INTO payments(id,hold_id,booking_id,outcome,amount,created_at) VALUES(?,?,?,'success',?,?)", (payment_id, hold_id, booking_id, amount, iso(now)))
        details = conn.execute("SELECT b.id,b.amount,b.status,s.starts_at,m.title FROM bookings b JOIN shows s ON s.id=b.show_id JOIN movies m ON m.id=s.movie_id WHERE b.id=?", (booking_id,)).fetchone()
    return {"booking": {**dict(details), "seats": seats}}


def bookings_for(user_id: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        where = "WHERE b.user_id=?" if user_id else ""
        args = (user_id,) if user_id else ()
        seats_expression = "STRING_AGG(bs.seat_label, ', ' ORDER BY bs.seat_label)" if USE_POSTGRES else "GROUP_CONCAT(bs.seat_label, ', ')"
        rows = conn.execute(f"""SELECT b.id,b.user_id,b.amount,b.status,b.created_at,s.starts_at,m.title,u.name customer_name,
            {seats_expression} seats FROM bookings b JOIN shows s ON s.id=b.show_id
            JOIN movies m ON m.id=s.movie_id JOIN users u ON u.id=b.user_id JOIN booking_seats bs ON bs.booking_id=b.id
            {where} GROUP BY b.id,b.user_id,b.amount,b.status,b.created_at,s.starts_at,m.title,u.name
            ORDER BY (s.starts_at > ?) DESC,s.starts_at""", (*args, iso(utc_now()))).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/bookings")
def my_bookings(user: dict[str, str] = Depends(current_user)) -> list[dict[str, Any]]:
    return bookings_for(user["id"])


@app.get("/api/admin/bookings")
def admin_bookings(_: dict[str, str] = Depends(require_admin)) -> list[dict[str, Any]]:
    return bookings_for()


@app.post("/api/admin/movies", status_code=201)
def create_movie(body: MovieInput, _: dict[str, str] = Depends(require_admin)) -> dict[str, Any]:
    movie_id = str(uuid.uuid4())
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        conn.execute("INSERT INTO movies(id,title,poster_url,language,duration_minutes,rating,description,created_at) VALUES(?,?,?,?,?,?,?,?)", (movie_id, body.title.strip(), body.poster_url.strip(), body.language.strip(), body.duration_minutes, body.rating, body.description.strip(), iso(utc_now())))
        return movie_dict(conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone())


@app.put("/api/admin/movies/{movie_id}")
def update_movie(movie_id: str, body: MovieInput, _: dict[str, str] = Depends(require_admin)) -> dict[str, Any]:
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        current = conn.execute("SELECT id FROM movies WHERE id=?", (movie_id,)).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="Movie not found")
        scheduled = conn.execute("SELECT id,starts_at FROM shows WHERE movie_id=?", (movie_id,)).fetchall()
        other_shows = conn.execute("SELECT s.id,s.movie_id,s.starts_at,m.duration_minutes FROM shows s JOIN movies m ON m.id=s.movie_id WHERE s.id NOT IN (SELECT id FROM shows WHERE movie_id=?)", (movie_id,)).fetchall()
        for show in scheduled:
            starts = parse_time(show["starts_at"])
            ends = starts + timedelta(minutes=body.duration_minutes)
            for other in other_shows:
                other_starts = parse_time(other["starts_at"])
                other_ends = other_starts + timedelta(minutes=other["duration_minutes"])
                if starts < other_ends and other_starts < ends:
                    raise HTTPException(status_code=409, detail="This runtime would make a scheduled show overlap")
        for index, show in enumerate(scheduled):
            starts = parse_time(show["starts_at"])
            ends = starts + timedelta(minutes=body.duration_minutes)
            for following in scheduled[index + 1:]:
                other_starts = parse_time(following["starts_at"])
                other_ends = other_starts + timedelta(minutes=body.duration_minutes)
                if starts < other_ends and other_starts < ends:
                    raise HTTPException(status_code=409, detail="This runtime would make two scheduled shows overlap")
        conn.execute("UPDATE movies SET title=?,poster_url=?,language=?,duration_minutes=?,rating=?,description=? WHERE id=?", (body.title.strip(), body.poster_url.strip(), body.language.strip(), body.duration_minutes, body.rating, body.description.strip(), movie_id))
        return movie_dict(conn.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone())


@app.delete("/api/admin/movies/{movie_id}", status_code=204)
def delete_movie(movie_id: str, _: dict[str, str] = Depends(require_admin)) -> None:
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        if not conn.execute("SELECT 1 FROM movies WHERE id=?", (movie_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Movie not found")
        if conn.execute("SELECT 1 FROM shows WHERE movie_id=?", (movie_id,)).fetchone():
            raise HTTPException(status_code=409, detail="Delete the movie's shows first")
        conn.execute("DELETE FROM movies WHERE id=?", (movie_id,))


@app.post("/api/admin/shows", status_code=201)
def create_show(body: ShowInput, _: dict[str, str] = Depends(require_admin)) -> dict[str, Any]:
    try:
        starts = parse_time(body.starts_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Show time must include a timezone") from exc
    if starts <= utc_now():
        raise HTTPException(status_code=422, detail="Show time must be in the future")
    show_id = str(uuid.uuid4())
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        movie = conn.execute("SELECT duration_minutes FROM movies WHERE id=?", (body.movie_id,)).fetchone()
        if not movie:
            raise HTTPException(status_code=404, detail="Movie not found")
        ends = starts + timedelta(minutes=movie["duration_minutes"])
        for existing in conn.execute("SELECT s.starts_at,m.duration_minutes FROM shows s JOIN movies m ON m.id=s.movie_id"):
            existing_start = parse_time(existing["starts_at"])
            existing_end = existing_start + timedelta(minutes=existing["duration_minutes"])
            if starts < existing_end and existing_start < ends:
                raise HTTPException(status_code=409, detail="This show overlaps another show on the screen")
        conn.execute("INSERT INTO shows(id,movie_id,starts_at,ticket_price,created_at) VALUES(?,?,?,?,?)", (show_id, body.movie_id, iso(starts), body.ticket_price, iso(utc_now())))
        return dict(conn.execute("SELECT s.*,m.title,m.duration_minutes FROM shows s JOIN movies m ON m.id=s.movie_id WHERE s.id=?", (show_id,)).fetchone())


@app.get("/api/admin/shows")
def list_admin_shows(_: dict[str, str] = Depends(require_admin)) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT s.id,s.movie_id,s.starts_at,s.ticket_price,m.title,m.duration_minutes FROM shows s JOIN movies m ON m.id=s.movie_id ORDER BY s.starts_at").fetchall()
    return [dict(row) for row in rows]


@app.delete("/api/admin/shows/{show_id}", status_code=204)
def delete_show(show_id: str, _: dict[str, str] = Depends(require_admin)) -> None:
    with transaction(lock_key=WRITE_LOCK_KEY) as conn:
        if not conn.execute("SELECT 1 FROM shows WHERE id=?", (show_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Show not found")
        if conn.execute("SELECT 1 FROM bookings WHERE show_id=?", (show_id,)).fetchone():
            raise HTTPException(status_code=409, detail="A show with bookings cannot be deleted")
        conn.execute("DELETE FROM seat_claims WHERE show_id=?", (show_id,))
        conn.execute("DELETE FROM payments WHERE hold_id IN (SELECT id FROM holds WHERE show_id=?)", (show_id,))
        conn.execute("DELETE FROM holds WHERE show_id=?", (show_id,))
        conn.execute("DELETE FROM shows WHERE id=?", (show_id,))
