import os, sys, tempfile, unittest
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ["DATABASE"] = _tmp.name
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402


def login(c, email, pw="1234"):
    c.get("/login")
    with c.session_transaction() as s:
        tok = s.setdefault("csrf", "t")
    return c.post("/login", data={"email": email, "password": pw, "csrf_token": tok})


def post(c, url, **data):
    with c.session_transaction() as s:
        data["csrf_token"] = s.setdefault("csrf", "t")
    return c.post(url, data=data)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.client_c, self.f1, self.f2 = (A.app.test_client() for _ in range(3))
        login(self.client_c, "client@demo.com")
        login(self.f1, "freelancer@demo.com")
        login(self.f2, "asha@demo.com")

    def test_password_hashed(self):
        with A.app.app_context():
            pw = A.get_db().execute("SELECT password_hash FROM users WHERE user_id=1").fetchone()[0]
        self.assertNotEqual(pw, "1234"); self.assertTrue(pw.startswith(("scrypt", "pbkdf2")))

    def test_csrf_blocks_post(self):
        self.assertEqual(self.f1.post("/project/1/bid", data={"amount": 1}).status_code, 400)

    def test_hire_must_be_post(self):
        self.assertEqual(self.client_c.get("/hire/1").status_code, 405)

    def test_full_flow_and_live_endpoints(self):
        pid = 1
        r = post(self.f1, f"/project/{pid}/bid", amount=20000, delivery_days=10, proposal="I can do it")
        self.assertEqual(r.status_code, 302)
        post(self.f2, f"/project/{pid}/bid", amount=18000, delivery_days=12, proposal="Cheaper")
        # duplicate bid is reported, not silently ignored
        post(self.f1, f"/project/{pid}/bid", amount=1, delivery_days=1, proposal="again")
        self.assertIn(b"already bid", self.f1.get(f"/project/{pid}").data)

        # live endpoint (client only) shows both bids, lowest first
        j = self.client_c.get(f"/api/project/{pid}/bids").get_json()
        self.assertIn("Asha Verma", j["html"]); self.assertLess(j["html"].index("Asha"), j["html"].index("Demo Freelancer"))
        self.assertEqual(self.f1.get(f"/api/project/{pid}/bids").status_code, 403)

        # privacy: freelancer 1 cannot see freelancer 2's proposal
        self.assertNotIn(b"Cheaper", self.f1.get(f"/project/{pid}").data)

        # client got notifications
        n = self.client_c.get("/api/notifications").get_json()
        self.assertEqual(n["unread"], 2)

        # hire asha (bid 2)
        post(self.client_c, "/hire/2")
        with A.app.app_context():
            con = A.get_db()
            self.assertEqual(con.execute("SELECT status FROM projects WHERE project_id=1").fetchone()[0], "Hired")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM hiring").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT status FROM bids WHERE bid_id=1").fetchone()[0], "Rejected")
        # second hire attempt is refused by the atomic guard
        post(self.client_c, "/hire/1")
        with A.app.app_context():
            self.assertEqual(A.get_db().execute("SELECT COUNT(*) FROM hiring").fetchone()[0], 1)
        # both freelancers notified
        self.assertGreaterEqual(self.f2.get("/api/notifications").get_json()["unread"], 1)
        self.assertGreaterEqual(self.f1.get("/api/notifications").get_json()["unread"], 1)

        post(self.client_c, f"/project/{pid}/complete")
        with A.app.app_context():
            self.assertEqual(A.get_db().execute("SELECT status FROM hiring").fetchone()[0], "Completed")

    def test_bad_ids_and_validation(self):
        self.assertEqual(post(self.client_c, "/hire/9999").status_code, 404)
        self.assertEqual(post(self.f1, "/project/1/bid", amount=-5, delivery_days=3, proposal="x").status_code, 302)
        r = post(self.client_c, "/project/new", title="t", description="d", budget=10, deadline="2000-01-01")
        self.assertEqual(r.status_code, 400)

    def test_foreign_keys_enforced_and_check(self):
        import sqlite3
        with A.app.app_context():
            con = A.get_db()
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO projects(client_id,title,description,budget,deadline) VALUES(999,'a','b',1,'2030-01-01')")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("INSERT INTO projects(client_id,title,description,budget,deadline) VALUES(1,'a','b',-1,'2030-01-01')")
            con.rollback()

    def test_register_and_profile(self):
        c = A.app.test_client(); c.get("/register")
        r = post(c, "/register", name="Ravi", email="ravi@x.com", password="secret1", role="Freelancer",
                 skills="Python, python, SQL", bio="hi")
        self.assertEqual(r.status_code, 302)
        r = post(c, "/register", name="Ravi", email="ravi@x.com", password="secret1", role="Freelancer")
        self.assertEqual(r.status_code, 409)
        r = post(c, "/register", name="X", email="x@x.com", password="secret1", role="Hacker")
        self.assertEqual(r.status_code, 400)
        login(c, "ravi@x.com", "secret1")
        self.assertIn(b"Python", c.get("/profile/4").data)
        post(c, "/profile/edit", bio="b", skills="Go", experience=3, hourly_rate=700)
        self.assertIn(b"700", c.get("/profile/4").data)

    def test_all_pages_render(self):
        for c, urls in [(self.client_c, ["/dashboard", "/project/new", "/project/1", "/notifications", "/profile/2"]),
                        (self.f1, ["/dashboard", "/project/1", "/profile/edit", "/notifications"]),
                        (A.app.test_client(), ["/", "/login", "/register", "/project/1"])]:
            for u in urls:
                self.assertEqual(c.get(u).status_code, 200, u)

    def test_z_reject_flow(self):
        con = lambda: A.get_db()
        post(self.client_c, "/project/new", title="Logo", description="Design a logo", budget=5000,
             deadline="2099-01-01")
        with A.app.app_context():
            pid = con().execute("SELECT MAX(project_id) FROM projects").fetchone()[0]
        post(self.f1, f"/project/{pid}/bid", amount=4000, delivery_days=5, proposal="mine")
        post(self.f2, f"/project/{pid}/bid", amount=3000, delivery_days=7, proposal="hers")
        with A.app.app_context():
            b1, b2 = [r[0] for r in con().execute(
                "SELECT bid_id FROM bids WHERE project_id=? ORDER BY bid_id", (pid,))]
        before = self.f1.get("/api/notifications").get_json()["unread"]

        # freelancers cannot reject; another client cannot reject someone else's project
        self.assertEqual(post(self.f2, f"/reject/{b1}").status_code, 403)
        other = A.app.test_client(); other.get("/register")
        post(other, "/register", name="C2", email="c2@x.com", password="secret1", role="Client")
        login(other, "c2@x.com", "secret1")
        self.assertEqual(post(other, f"/reject/{b1}").status_code, 404)

        # owner rejects with a reason
        post(self.client_c, f"/reject/{b1}", reason="Too expensive")
        with A.app.app_context():
            row = con().execute("SELECT status, rejection_reason FROM bids WHERE bid_id=?", (b1,)).fetchone()
        self.assertEqual((row[0], row[1]), ("Rejected", "Too expensive"))
        notes = self.f1.get("/api/notifications").get_json()
        self.assertEqual(notes["unread"], before + 1)
        self.assertIn("Too expensive", notes["items"][0]["message"])
        self.assertIn(b"Too expensive", self.f1.get(f"/project/{pid}").data)

        # double reject does not notify twice
        post(self.client_c, f"/reject/{b1}")
        self.assertEqual(self.f1.get("/api/notifications").get_json()["unread"], before + 1)

        # a rejected bid cannot be hired; project stays Open
        post(self.client_c, f"/hire/{b1}")
        with A.app.app_context():
            self.assertEqual(con().execute("SELECT status FROM projects WHERE project_id=?", (pid,)).fetchone()[0], "Open")
        # hire the other one, then rejecting is no longer allowed
        post(self.client_c, f"/hire/{b2}")
        post(self.client_c, f"/reject/{b2}")
        with A.app.app_context():
            self.assertEqual(con().execute("SELECT status FROM bids WHERE bid_id=?", (b2,)).fetchone()[0], "Accepted")
        # live panel renders reject/hire buttons only for pending bids on an open project
        self.assertNotIn("✕ Reject", self.client_c.get(f"/api/project/{pid}/bids").get_json()["html"])


if __name__ == "__main__":
    unittest.main()
