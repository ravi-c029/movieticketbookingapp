from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

os.environ["JWT_SECRET"] = "test-secret-for-integration-tests"
_temp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_temp.name) / "test.sqlite3")

from fastapi.testclient import TestClient

from app import app, connect, hash_password, initialize_database, iso, provision_initial_admin, utc_now


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        initialize_database()
        cls.client = TestClient(app)

    def setUp(self) -> None:
        with connect() as conn:
            conn.execute("DELETE FROM payments")
            conn.execute("DELETE FROM seat_claims")
            conn.execute("DELETE FROM booking_seats")
            conn.execute("DELETE FROM bookings")
            conn.execute("DELETE FROM holds")
            conn.execute("DELETE FROM shows")
            conn.execute("DELETE FROM movies")
            conn.execute("DELETE FROM users")
        self.customer = self.client.post("/api/auth/register", json={"name": "Ravi", "email": "ravi@example.com", "password": "password123"}).json()
        self.other = self.client.post("/api/auth/register", json={"name": "Asha", "email": "asha@example.com", "password": "password123"}).json()
        with connect() as conn:
            admin_id = "admin-test"
            conn.execute("INSERT INTO users(id,name,email,password_hash,role,created_at) VALUES(?,?,?,?,?,?)", (admin_id, "Admin", "admin@example.com", hash_password("password123"), "admin", iso(utc_now())))
        self.admin = self.client.post("/api/auth/login", json={"email": "admin@example.com", "password": "password123"}).json()
        self.movie = self.client.post("/api/admin/movies", headers=self.headers(self.admin), json={"title":"Test Film","poster_url":"","language":"English","duration_minutes":90,"rating":"U","description":"Test"}).json()
        self.show = self.client.post("/api/admin/shows", headers=self.headers(self.admin), json={"movie_id":self.movie["id"],"starts_at":iso(utc_now()+timedelta(days=2)),"ticket_price":1000}).json()

    @staticmethod
    def headers(auth: dict) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth['token']}"}

    def test_registration_hashes_password_and_duplicate_is_rejected(self) -> None:
        with connect() as conn:
            stored = conn.execute("SELECT password_hash FROM users WHERE email='ravi@example.com'").fetchone()[0]
        self.assertNotEqual(stored, "password123")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertEqual(self.client.post("/api/auth/register", json={"name":"Again","email":"ravi@example.com","password":"password123"}).status_code, 409)
        self.assertEqual(self.client.post("/api/auth/register", json={"name":"Short","email":"short@example.com","password":"short"}).status_code, 422)
        login = self.client.post("/api/auth/login", json={"email":"ravi@example.com","password":"password123"})
        self.assertEqual(login.status_code, 200)
        wrong_password = self.client.post("/api/auth/login", json={"email":"ravi@example.com","password":"wrong-password"})
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(wrong_password.json()["detail"], "Email or password is incorrect")

    def test_initial_admin_environment_credentials_are_provisioned(self) -> None:
        old_email = os.environ.get("INITIAL_ADMIN_EMAIL")
        old_password = os.environ.get("INITIAL_ADMIN_PASSWORD")
        os.environ["INITIAL_ADMIN_EMAIL"] = "configured-admin@example.com"
        os.environ["INITIAL_ADMIN_PASSWORD"] = "StrongTestPassword123!"
        try:
            provision_initial_admin()
            response = self.client.post("/api/auth/login", json={"email": "configured-admin@example.com", "password": "StrongTestPassword123!"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["user"]["role"], "admin")
        finally:
            if old_email is None:
                os.environ.pop("INITIAL_ADMIN_EMAIL", None)
            else:
                os.environ["INITIAL_ADMIN_EMAIL"] = old_email
            if old_password is None:
                os.environ.pop("INITIAL_ADMIN_PASSWORD", None)
            else:
                os.environ["INITIAL_ADMIN_PASSWORD"] = old_password

    def test_auth_and_role_boundaries(self) -> None:
        self.assertEqual(self.client.post(f"/api/shows/{self.show['id']}/holds", json={"seats":["A1"]}).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/movies", headers=self.headers(self.customer), json={"title":"x","language":"x","duration_minutes":90,"rating":"U"}).status_code, 403)

    def test_seat_map_has_eighty_available_seats(self) -> None:
        result = self.client.get(f"/api/shows/{self.show['id']}/seats").json()
        self.assertEqual(len(result["seats"]), 80)
        self.assertTrue(all(seat["status"] == "available" for seat in result["seats"]))

    def test_movies_and_future_shows_are_retrievable(self) -> None:
        self.assertEqual(len(self.client.get("/api/movies").json()), 1)
        details = self.client.get(f"/api/movies/{self.movie['id']}").json()
        self.assertEqual(details["movie"]["title"], "Test Film")
        self.assertEqual([show["id"] for show in details["shows"]], [self.show["id"]])
        admin_shows = self.client.get("/api/admin/shows", headers=self.headers(self.admin))
        self.assertEqual(admin_shows.status_code, 200)
        self.assertEqual(admin_shows.json()[0]["id"], self.show["id"])

    def test_six_seat_limit_and_conflicting_hold(self) -> None:
        too_many = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["A1","A2","A3","A4","A5","A6","A7"]})
        self.assertEqual(too_many.status_code, 422)
        held = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["C4","C5"]})
        self.assertEqual(held.status_code, 201)
        conflict = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.other), json={"seats":["C5"]})
        self.assertEqual(conflict.status_code, 409)
        self.assertIn("C5", conflict.json()["detail"])
        all_or_nothing = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.other), json={"seats":["C3","C5"]})
        self.assertEqual(all_or_nothing.status_code, 409)
        map_result = self.client.get(f"/api/shows/{self.show['id']}/seats").json()
        self.assertEqual(next(seat for seat in map_result["seats"] if seat["label"] == "C3")["status"], "available")

    def test_payment_failure_keeps_hold_then_success_confirms(self) -> None:
        hold = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["B2"]}).json()
        failed = self.client.post(f"/api/holds/{hold['id']}/payment", headers=self.headers(self.customer), json={"outcome":"failure"})
        self.assertEqual(failed.status_code, 200)
        self.assertEqual(failed.json()["status"], "failed")
        success = self.client.post(f"/api/holds/{hold['id']}/payment", headers=self.headers(self.customer), json={"outcome":"success"})
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()["booking"]["seats"], ["B2"])
        self.assertEqual(len(self.client.get("/api/bookings", headers=self.headers(self.customer)).json()), 1)
        self.assertEqual(self.client.get("/api/bookings", headers=self.headers(self.other)).json(), [])

    def test_expired_hold_releases_seat_and_cannot_be_paid(self) -> None:
        hold = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["D1"]}).json()
        with connect() as conn:
            past = iso(utc_now() - timedelta(seconds=1))
            conn.execute("UPDATE holds SET expires_at=? WHERE id=?", (past, hold["id"]))
            conn.execute("UPDATE seat_claims SET expires_at=? WHERE hold_id=?", (past, hold["id"]))
        expired = self.client.post(f"/api/holds/{hold['id']}/payment", headers=self.headers(self.customer), json={"outcome":"success"})
        self.assertEqual(expired.status_code, 409)
        self.assertEqual(self.client.get(f"/api/holds/{hold['id']}", headers=self.headers(self.customer)).json()["status"], "expired")
        available = self.client.get(f"/api/shows/{self.show['id']}/seats").json()
        self.assertEqual(next(seat for seat in available["seats"] if seat["label"] == "D1")["status"], "available")

    def test_show_overlap_is_rejected_and_booked_show_cannot_be_deleted(self) -> None:
        overlapping = self.client.post("/api/admin/shows", headers=self.headers(self.admin), json={"movie_id":self.movie["id"],"starts_at":self.show["starts_at"],"ticket_price":1000})
        self.assertEqual(overlapping.status_code, 409)
        hold = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["E1"]}).json()
        self.client.post(f"/api/holds/{hold['id']}/payment", headers=self.headers(self.customer), json={"outcome":"success"})
        deleted = self.client.delete(f"/api/admin/shows/{self.show['id']}", headers=self.headers(self.admin))
        self.assertEqual(deleted.status_code, 409)

    def test_movie_runtime_edit_cannot_create_a_schedule_overlap(self) -> None:
        second_movie = self.client.post("/api/admin/movies", headers=self.headers(self.admin), json={"title":"Second Film","poster_url":"","language":"English","duration_minutes":90,"rating":"U","description":"Test"}).json()
        starts = utc_now() + timedelta(days=2)
        second_show = self.client.post("/api/admin/shows", headers=self.headers(self.admin), json={"movie_id":second_movie["id"],"starts_at":iso(starts+timedelta(minutes=100)),"ticket_price":1000})
        self.assertEqual(second_show.status_code, 201)
        edited = self.client.put(f"/api/admin/movies/{self.movie['id']}", headers=self.headers(self.admin), json={"title":"Test Film","poster_url":"","language":"English","duration_minutes":120,"rating":"U","description":"Test"})
        self.assertEqual(edited.status_code, 409)

    def test_unbooked_show_with_hold_can_be_removed_for_rescheduling(self) -> None:
        hold = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(self.customer), json={"seats":["A1"]})
        self.assertEqual(hold.status_code, 201)
        deleted = self.client.delete(f"/api/admin/shows/{self.show['id']}", headers=self.headers(self.admin))
        self.assertEqual(deleted.status_code, 204)

    def test_simultaneous_conflicting_holds_allow_exactly_one_booking(self) -> None:
        def attempt(auth: dict) -> dict:
            response = self.client.post(f"/api/shows/{self.show['id']}/holds", headers=self.headers(auth), json={"seats":["H10"]})
            return {"status": response.status_code, "body": response.json()}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, [self.customer, self.other]))
        winners = [result for result in results if result["status"] == 201]
        losers = [result for result in results if result["status"] == 409]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(len(losers), 1, results)
        winner_auth = self.customer if results[0]["status"] == 201 else self.other
        paid = self.client.post(f"/api/holds/{winners[0]['body']['id']}/payment", headers=self.headers(winner_auth), json={"outcome":"success"})
        self.assertEqual(paid.status_code, 200)
        with connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM booking_seats WHERE seat_label='H10'").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
