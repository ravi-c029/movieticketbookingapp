from __future__ import annotations

import os
import sys
import uuid
from datetime import timedelta

from app import USE_POSTGRES, connect, hash_password, initialize_database, iso, utc_now


def seed() -> None:
    if len(os.environ.get("JWT_SECRET", "")) < 32:
        raise RuntimeError("Set a JWT_SECRET containing at least 32 characters before seeding")
    if USE_POSTGRES:
        admin_email = os.environ.get("INITIAL_ADMIN_EMAIL", "").strip().lower()
        admin_password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
        if not admin_email or len(admin_password) < 12:
            raise RuntimeError("For PostgreSQL seeding, set INITIAL_ADMIN_EMAIL and INITIAL_ADMIN_PASSWORD (at least 12 characters)")
        accounts = [("Cinema Admin", admin_email, admin_password, "admin")]
    else:
        accounts = [
            ("Test Customer", "customer@example.com", "Customer123!", "customer"),
            ("Cinema Admin", "admin@example.com", "Admin123!", "admin"),
        ]
    initialize_database()
    now = utc_now()
    with connect() as conn:
        for name, email, password, role in accounts:
            values = (str(uuid.uuid5(uuid.NAMESPACE_URL, email)), name, email, hash_password(password), role, iso(now))
            if USE_POSTGRES:
                conn.execute(
                    "INSERT INTO users(id,name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(email) DO UPDATE SET name=excluded.name,password_hash=excluded.password_hash,role=excluded.role",
                    values,
                )
            else:
                conn.execute("INSERT OR IGNORE INTO users(id,name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", values)
        existing = conn.execute("SELECT COUNT(*) count FROM movies").fetchone()["count"]
        if existing == 0:
            movie_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
            movies = [
                (movie_ids[0], "The Last Signal", "", "English", 128, "UA", "A signal from the deep frontier changes everything."),
                (movie_ids[1], "Paper Moons", "", "Hindi", 114, "U", "Two strangers find a new beginning in the city."),
            ]
            conn.executemany("INSERT INTO movies(id,title,poster_url,language,duration_minutes,rating,description,created_at) VALUES(?,?,?,?,?,?,?,?)", [(*movie, iso(now)) for movie in movies])
            start_a = now + timedelta(days=1)
            start_a = start_a.replace(hour=10, minute=0, second=0, microsecond=0)
            start_b = start_a.replace(hour=14)
            conn.executemany("INSERT INTO shows(id,movie_id,starts_at,ticket_price,created_at) VALUES(?,?,?,?,?)", [
                (str(uuid.uuid4()), movie_ids[0], iso(start_a), 25000, iso(now)),
                (str(uuid.uuid4()), movie_ids[0], iso(start_b), 25000, iso(now)),
            ])
    if USE_POSTGRES:
        print(f"Production seed complete. Admin account: {accounts[0][1]}")
    else:
        print("Seed complete. Customer: customer@example.com / Customer123!  Admin: admin@example.com / Admin123!")


if __name__ == "__main__":
    seed()
