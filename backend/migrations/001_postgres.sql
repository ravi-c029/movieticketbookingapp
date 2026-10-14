CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('customer','admin')),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS movies (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  poster_url TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL,
  duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
  rating TEXT NOT NULL CHECK(rating IN ('U','UA','A')),
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shows (
  id TEXT PRIMARY KEY,
  movie_id TEXT NOT NULL REFERENCES movies(id),
  starts_at TEXT NOT NULL,
  ticket_price INTEGER NOT NULL CHECK(ticket_price > 0),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS shows_starts_at_idx ON shows(starts_at);

CREATE TABLE IF NOT EXISTS holds (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  show_id TEXT NOT NULL REFERENCES shows(id),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','converted','expired'))
);

CREATE TABLE IF NOT EXISTS bookings (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  show_id TEXT NOT NULL REFERENCES shows(id),
  amount INTEGER NOT NULL CHECK(amount > 0),
  status TEXT NOT NULL CHECK(status IN ('confirmed','cancelled')),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS bookings_user_created_idx ON bookings(user_id, created_at);

CREATE TABLE IF NOT EXISTS booking_seats (
  booking_id TEXT NOT NULL REFERENCES bookings(id),
  seat_label TEXT NOT NULL,
  PRIMARY KEY(booking_id, seat_label)
);

CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  hold_id TEXT NOT NULL REFERENCES holds(id),
  booking_id TEXT REFERENCES bookings(id),
  outcome TEXT NOT NULL CHECK(outcome IN ('success','failure')),
  amount INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seat_claims (
  show_id TEXT NOT NULL REFERENCES shows(id),
  seat_label TEXT NOT NULL,
  hold_id TEXT REFERENCES holds(id),
  booking_id TEXT REFERENCES bookings(id),
  expires_at TEXT,
  PRIMARY KEY(show_id, seat_label),
  CHECK((hold_id IS NOT NULL AND booking_id IS NULL AND expires_at IS NOT NULL) OR
        (hold_id IS NULL AND booking_id IS NOT NULL AND expires_at IS NULL))
);
CREATE INDEX IF NOT EXISTS seat_claims_expiry_idx ON seat_claims(expires_at);
