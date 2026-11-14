"""FreelanceHub - a freelancer marketplace (Flask + SQLite) with live updates."""
import hmac
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DATABASE", os.path.join(BASE, "freelancer_portal.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")   # SQLite ignores FKs unless enabled per connection
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def init_db():
    con = get_db()
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as f:
        con.executescript(f.read())
    # tiny migration so databases created by an earlier version get the new column
    cols = [r[1] for r in con.execute("PRAGMA table_info(bids)")]
    if "rejection_reason" not in cols:
        con.execute("ALTER TABLE bids ADD COLUMN rejection_reason TEXT")
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        pw = generate_password_hash("1234")
        con.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                    ("Demo Client", "client@demo.com", pw, "Client"))
        for name, email, bio, exp, rate, skills in [
            ("Demo Freelancer", "freelancer@demo.com", "Full-stack developer", 2, 500,
             "Python, HTML, CSS, SQL"),
            ("Asha Verma", "asha@demo.com", "UI/UX and frontend designer", 3, 650,
             "Figma, CSS, JavaScript"),
        ]:
            uid = con.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                              (name, email, pw, "Freelancer")).lastrowid
            con.execute("INSERT INTO freelancer_profile(user_id,bio,experience,hourly_rate) VALUES(?,?,?,?)",
                        (uid, bio, exp, rate))
            save_skills(con, uid, parse_skills(skills))
        deadline = (date.today() + timedelta(days=60)).isoformat()
        con.execute("INSERT INTO projects(client_id,title,description,budget,deadline) VALUES(?,?,?,?,?)",
                    (1, "Business Website",
                     "Build a responsive business website with a modern dashboard.", 30000, deadline))
    con.commit()


# ---------------------------------------------------------------- helpers
def login_required(role=None):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "uid" not in session:
                flash("Please log in first.", "error")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.filters["inr"] = lambda v: f"₹{float(v):,.0f}"
app.jinja_env.filters["initials"] = lambda n: "".join(w[0] for w in str(n).split()[:2]).upper() or "?"
app.jinja_env.filters["hue"] = lambda n: sum(map(ord, str(n))) % 360


def days_left(d):
    try:
        return (date.fromisoformat(d) - date.today()).days
    except (TypeError, ValueError):
        return None


app.jinja_env.filters["days_left"] = days_left


@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf", "")
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            abort(400, "Invalid or missing CSRF token.")


def notify(con, user_id, message, link=None):
    con.execute("INSERT INTO notifications(user_id,message,link) VALUES(?,?,?)",
                (user_id, message, link))


def parse_skills(text):
    out = []
    for s in (text or "").split(","):
        s = " ".join(s.split())[:40]
        if s and s.lower() not in [x.lower() for x in out]:
            out.append(s)
    return out[:15]


def save_skills(con, uid, names):
    con.execute("DELETE FROM freelancer_skills WHERE user_id=?", (uid,))
    for n in names:
        con.execute("INSERT OR IGNORE INTO skills(name) VALUES(?)", (n,))
        sid = con.execute("SELECT skill_id FROM skills WHERE name=?", (n,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO freelancer_skills(user_id,skill_id) VALUES(?,?)", (uid, sid))


def positive_number(value, integer=False):
    try:
        n = int(value) if integer else float(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def error_page(e):
    return render_template("error.html", e=e), e.code


# ---------------------------------------------------------------- auth
@app.route("/")
def home():
    con = get_db()
    stats = {
        "projects": con.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
        "freelancers": con.execute("SELECT COUNT(*) FROM users WHERE role='Freelancer'").fetchone()[0],
        "bids": con.execute("SELECT COUNT(*) FROM bids").fetchone()[0],
    }
    return render_template("index.html", stats=stats)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")
        if not name or not email:
            return render_template("register.html", error="Name and email are required."), 400
        if len(password) < 6:
            return render_template("register.html", error="Password must be at least 6 characters."), 400
        if role not in ("Client", "Freelancer"):
            return render_template("register.html", error="Choose a valid role."), 400
        con = get_db()
        try:
            uid = con.execute("INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)",
                              (name, email, generate_password_hash(password), role)).lastrowid
            if role == "Freelancer":
                con.execute("INSERT INTO freelancer_profile(user_id,bio) VALUES(?,?)",
                            (uid, request.form.get("bio", "").strip()))
                save_skills(con, uid, parse_skills(request.form.get("skills")))
            con.commit()
        except sqlite3.IntegrityError:
            con.rollback()
            return render_template("register.html", error="Email already registered."), 409
        flash("Account created. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = get_db().execute("SELECT * FROM users WHERE email=?",
                             (request.form.get("email", "").strip().lower(),)).fetchone()
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(uid=u["user_id"], role=u["role"], name=u["name"])
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid email or password."), 401
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


# ---------------------------------------------------------------- dashboards / projects
@app.route("/dashboard")
@login_required()
def dashboard():
    con = get_db()
    if session["role"] == "Client":
        projects = con.execute("SELECT * FROM v_project_summary WHERE client_id=? ORDER BY project_id DESC",
                               (session["uid"],)).fetchall()
        return render_template("client.html", projects=projects)
    projects = con.execute("""SELECT p.*, u.name client_name,
                                     (SELECT COUNT(*) FROM bids b WHERE b.project_id=p.project_id) bid_count
                              FROM projects p JOIN users u ON p.client_id=u.user_id
                              WHERE p.status='Open' AND p.deadline >= date('now')
                              ORDER BY p.project_id DESC""").fetchall()
    mybids = con.execute("""SELECT b.*, p.title FROM bids b JOIN projects p ON b.project_id=p.project_id
                            WHERE b.freelancer_id=? ORDER BY b.bid_id DESC""", (session["uid"],)).fetchall()
    return render_template("freelancer.html", projects=projects, mybids=mybids)


@app.route("/project/new", methods=["GET", "POST"])
@login_required("Client")
def new_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()
        budget = positive_number(request.form.get("budget"))
        try:
            deadline = date.fromisoformat(request.form.get("deadline", ""))
        except ValueError:
            deadline = None
        if not title or not desc or budget is None or deadline is None or deadline <= date.today():
            flash("Fill all fields; budget must be positive and deadline in the future.", "error")
            return render_template("new_project.html"), 400
        con = get_db()
        con.execute("INSERT INTO projects(client_id,title,description,budget,deadline) VALUES(?,?,?,?,?)",
                    (session["uid"], title, desc, budget, deadline.isoformat()))
        con.commit()
        flash("Project published.", "success")
        return redirect(url_for("dashboard"))
    return render_template("new_project.html")


def load_project(pid):
    p = get_db().execute("""SELECT p.*, u.name client_name FROM projects p
                            JOIN users u ON p.client_id=u.user_id WHERE p.project_id=?""", (pid,)).fetchone()
    if not p:
        abort(404)
    return p


def visible_bids(p):
    """Privacy: owner sees all bids; a freelancer sees only their own; others see none."""
    con = get_db()
    q = """SELECT b.*, u.name freelancer_name FROM bids b
           JOIN users u ON b.freelancer_id=u.user_id WHERE b.project_id=?"""
    if session.get("uid") == p["client_id"]:
        return con.execute(q + " ORDER BY b.amount ASC", (p["project_id"],)).fetchall()
    if session.get("role") == "Freelancer":
        return con.execute(q + " AND b.freelancer_id=?", (p["project_id"], session["uid"])).fetchall()
    return []


@app.route("/project/<int:pid>")
def project(pid):
    p = load_project(pid)
    bids = visible_bids(p)
    total = get_db().execute("SELECT COUNT(*) FROM bids WHERE project_id=?", (pid,)).fetchone()[0]
    is_owner = session.get("uid") == p["client_id"]
    my_bid = next((b for b in bids if b["freelancer_id"] == session.get("uid")), None)
    expired = p["deadline"] < date.today().isoformat()
    hire = get_db().execute("SELECT * FROM hiring WHERE project_id=?", (pid,)).fetchone()
    return render_template("project.html", p=p, bids=bids, total=total, is_owner=is_owner,
                           my_bid=my_bid, expired=expired, hire=hire)


@app.route("/api/project/<int:pid>/bids")
@login_required("Client")
def api_project_bids(pid):
    """Live endpoint: returns the bids panel HTML; the browser polls it every 3s."""
    p = load_project(pid)
    if p["client_id"] != session["uid"]:
        abort(403)
    html = render_template("_bids.html", p=p, bids=visible_bids(p), is_owner=True)
    return jsonify(html=html)


@app.route("/project/<int:pid>/bid", methods=["POST"])
@login_required("Freelancer")
def bid(pid):
    p = load_project(pid)
    if p["status"] != "Open" or p["deadline"] < date.today().isoformat():
        flash("This project is no longer accepting bids.", "error")
        return redirect(url_for("project", pid=pid))
    amount = positive_number(request.form.get("amount"))
    days = positive_number(request.form.get("delivery_days"), integer=True)
    proposal = request.form.get("proposal", "").strip()
    if amount is None or days is None or not proposal:
        flash("Enter a positive amount, delivery days and a proposal.", "error")
        return redirect(url_for("project", pid=pid))
    con = get_db()
    try:
        con.execute("INSERT INTO bids(project_id,freelancer_id,amount,proposal,delivery_days) VALUES(?,?,?,?,?)",
                    (pid, session["uid"], amount, proposal, days))
        notify(con, p["client_id"], f"New bid of ₹{amount:,.0f} from {session['name']} on '{p['title']}'",
               url_for("project", pid=pid))
        con.commit()
        flash("Bid submitted.", "success")
    except sqlite3.IntegrityError:
        con.rollback()
        flash("You have already bid on this project.", "error")
    return redirect(url_for("project", pid=pid))


@app.route("/hire/<int:bid_id>", methods=["POST"])
@login_required("Client")
def hire(bid_id):
    con = get_db()
    b = con.execute("""SELECT b.*, p.client_id, p.title FROM bids b
                       JOIN projects p ON b.project_id=p.project_id WHERE b.bid_id=?""", (bid_id,)).fetchone()
    if not b or b["client_id"] != session["uid"]:
        abort(404)
    pid = b["project_id"]
    try:
        con.execute("BEGIN IMMEDIATE")                       # take the write lock up-front
        # Atomic guard: succeeds only for the first request while status is still 'Open'
        cur = con.execute("UPDATE projects SET status='Hired' WHERE project_id=? AND status='Open'", (pid,))
        if cur.rowcount == 0:
            con.rollback()
            flash("This project already has a hired freelancer.", "error")
            return redirect(url_for("project", pid=pid))
        # Only a still-pending bid can be accepted (a rejected bid cannot be hired)
        cur = con.execute("UPDATE bids SET status='Accepted' WHERE bid_id=? AND status='Pending'", (bid_id,))
        if cur.rowcount == 0:
            con.rollback()
            flash("This bid was already rejected, so it can't be hired.", "error")
            return redirect(url_for("project", pid=pid))
        others = [r[0] for r in con.execute(
            "SELECT freelancer_id FROM bids WHERE project_id=? AND bid_id<>? AND status='Pending'", (pid, bid_id))]
        con.execute("""UPDATE bids SET status='Rejected', rejection_reason='Another freelancer was selected'
                       WHERE project_id=? AND bid_id<>? AND status='Pending'""", (pid, bid_id))
        con.execute("INSERT INTO hiring(project_id,freelancer_id,bid_id,hired_date) VALUES(?,?,?,?)",
                    (pid, b["freelancer_id"], bid_id, datetime.now().strftime("%Y-%m-%d %H:%M")))
        link = url_for("project", pid=pid)
        notify(con, b["freelancer_id"], f"🎉 You were hired for '{b['title']}'", link)
        for fid in others:
            notify(con, fid, f"Your bid on '{b['title']}' was not selected", link)
        con.commit()
        flash("Freelancer hired.", "success")
    except sqlite3.Error:
        con.rollback()
        raise
    return redirect(url_for("project", pid=pid))


@app.route("/reject/<int:bid_id>", methods=["POST"])
@login_required("Client")
def reject(bid_id):
    con = get_db()
    b = con.execute("""SELECT b.*, p.client_id, p.title, p.status pstatus FROM bids b
                       JOIN projects p ON b.project_id=p.project_id WHERE b.bid_id=?""", (bid_id,)).fetchone()
    if not b or b["client_id"] != session["uid"]:
        abort(404)
    pid = b["project_id"]
    reason = request.form.get("reason", "").strip()[:200] or None
    if b["pstatus"] != "Open":
        flash("Bids can only be rejected while the project is open.", "error")
    else:
        # guarded update: only a Pending bid can be rejected, so double-clicks don't notify twice
        cur = con.execute("UPDATE bids SET status='Rejected', rejection_reason=? WHERE bid_id=? AND status='Pending'",
                          (reason, bid_id))
        if cur.rowcount:
            msg = f"Your bid on '{b['title']}' was rejected" + (f": {reason}" if reason else "")
            notify(con, b["freelancer_id"], msg, url_for("project", pid=pid))
            con.commit()
            flash("Bid rejected. The freelancer has been notified.", "success")
        else:
            flash("This bid was already handled.", "error")
    return redirect(url_for("project", pid=pid))


@app.route("/project/<int:pid>/complete", methods=["POST"])
@login_required("Client")
def complete(pid):
    p = load_project(pid)
    if p["client_id"] != session["uid"]:
        abort(403)
    con = get_db()
    cur = con.execute("UPDATE projects SET status='Completed' WHERE project_id=? AND status='Hired'", (pid,))
    if cur.rowcount:
        h = con.execute("SELECT freelancer_id FROM hiring WHERE project_id=?", (pid,)).fetchone()
        con.execute("UPDATE hiring SET status='Completed', completed_date=? WHERE project_id=?",
                    (datetime.now().strftime("%Y-%m-%d %H:%M"), pid))
        notify(con, h["freelancer_id"], f"'{p['title']}' was marked completed", url_for("project", pid=pid))
        con.commit()
        flash("Project marked completed.", "success")
    return redirect(url_for("project", pid=pid))


# ---------------------------------------------------------------- profiles
@app.route("/profile/<int:uid>")
@login_required()
def profile(uid):
    con = get_db()
    u = con.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not u:
        abort(404)
    p = con.execute("SELECT * FROM freelancer_profile WHERE user_id=?", (uid,)).fetchone()
    skills = con.execute("""SELECT s.name FROM skills s JOIN freelancer_skills fs ON s.skill_id=fs.skill_id
                            WHERE fs.user_id=? ORDER BY s.name""", (uid,)).fetchall()
    done = con.execute("SELECT COUNT(*) FROM hiring WHERE freelancer_id=? AND status='Completed'",
                       (uid,)).fetchone()[0]
    return render_template("profile.html", u=u, p=p, skills=skills, done=done)


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required("Freelancer")
def edit_profile():
    con = get_db()
    if request.method == "POST":
        try:
            exp = max(0, int(request.form.get("experience") or 0))
            rate = max(0.0, float(request.form.get("hourly_rate") or 0))
        except ValueError:
            flash("Experience and rate must be numbers.", "error")
            return redirect(url_for("edit_profile"))
        con.execute("UPDATE freelancer_profile SET bio=?, experience=?, hourly_rate=? WHERE user_id=?",
                    (request.form.get("bio", "").strip(), exp, rate, session["uid"]))
        save_skills(con, session["uid"], parse_skills(request.form.get("skills")))
        con.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("profile", uid=session["uid"]))
    p = con.execute("SELECT * FROM freelancer_profile WHERE user_id=?", (session["uid"],)).fetchone()
    skills = ", ".join(r[0] for r in con.execute(
        """SELECT s.name FROM skills s JOIN freelancer_skills fs ON s.skill_id=fs.skill_id
           WHERE fs.user_id=? ORDER BY s.name""", (session["uid"],)))
    return render_template("edit_profile.html", p=p, skills=skills)


# ---------------------------------------------------------------- notifications (real-time)
@app.route("/api/notifications")
@login_required()
def api_notifications():
    con = get_db()
    rows = con.execute("""SELECT notif_id id, message, link, is_read FROM notifications
                          WHERE user_id=? ORDER BY notif_id DESC LIMIT 10""", (session["uid"],)).fetchall()
    unread = con.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
                         (session["uid"],)).fetchone()[0]
    return jsonify(unread=unread, latest_id=rows[0]["id"] if rows else 0, items=[dict(r) for r in rows])


@app.route("/notifications")
@login_required()
def notifications():
    rows = get_db().execute("SELECT * FROM notifications WHERE user_id=? ORDER BY notif_id DESC LIMIT 50",
                            (session["uid"],)).fetchall()
    return render_template("notifications.html", rows=rows)


@app.route("/notifications/read", methods=["POST"])
@login_required()
def notifications_read():
    con = get_db()
    con.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["uid"],))
    con.commit()
    return redirect(url_for("notifications"))


with app.app_context():      # runs for `python app.py`, `flask run` and gunicorn alike
    init_db()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
