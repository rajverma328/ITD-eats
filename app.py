# app.py
import os
from datetime import datetime, date, time as dtime
import threading
import logging
import uuid

import pytz
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from sqlalchemy import UniqueConstraint
from sqlalchemy import func

db = SQLAlchemy()

# -----------------------
# Models (declared before create_app so migrations can import)
# -----------------------
class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    votes = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Vote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("item.id", ondelete="CASCADE"), nullable=False)
    voter_token = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("item_id", "voter_token", name="uix_item_voter"),)


# -----------------------
# Reset-once-per-day logic (no APScheduler)
# -----------------------
_reset_lock = threading.Lock()
_last_reset_date = None  # stores date object of last reset (in RESET_TZ)

def maybe_reset(app, RESET_TZ, RESET_TIME):
    """
    Deletes all Item records once per day after RESET_TIME in RESET_TZ timezone.
    Safe to call on every request - will perform deletion at most once per day (per process).
    For multi-instance deployments prefer cron / scheduler or a DB-based marker.
    """
    global _last_reset_date
    try:
        tz = pytz.timezone(RESET_TZ)
    except Exception:
        tz = pytz.UTC

    now = datetime.now(tz)
    today = now.date()

    if _last_reset_date == today:
        return

    if now.time() < RESET_TIME:
        return

    with _reset_lock:
        if _last_reset_date == today:
            return
        with app.app_context():
            # delete Votes and Items
            Vote.query.delete()
            Item.query.delete()
            db.session.commit()
            _last_reset_date = today
            app.logger.info(f"Daily reset executed at {now.isoformat()} ({RESET_TZ})")


# -----------------------
# Helpers / decorators
# -----------------------
def require_login(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def ensure_voter_token():
    """Ensure a persistent voter_token exists in session and return it."""
    token = session.get("voter_token")
    if not token:
        token = uuid.uuid4().hex
        session["voter_token"] = token
    return token


# -----------------------
# Application factory
# -----------------------
def create_app(test_config=None):
    """
    Create and configure the Flask app.
    Reads configuration from environment variables (sane defaults for local dev).
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Config from environment
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change_this_secret_in_prod")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///items.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    ADMIN_PASS_HASH = "scrypt:32768:8:1$INnuLziqpYVfTZ2d$5ae101b115844cca1f313cacd2323f10a81cc14127ad55b66a1e4097e8da5dc3ad342e37791713013f8e9333d241a2b5637f208c33624d8679cb3c27970d557a"

    RESET_TZ = os.environ.get("RESET_TZ", "Asia/Kolkata")
    RESET_TIME = dtime.fromisoformat(os.environ.get("RESET_TIME", "18:00:00"))

    # initialize extensions
    db.init_app(app)

    # configure logging to stdout (useful for containers)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    stream_handler.setFormatter(formatter)
    if not app.logger.handlers:
        app.logger.addHandler(stream_handler)
    app.logger.setLevel(logging.INFO)

    # create DB tables if missing (for simple deployments)
    with app.app_context():
        db.create_all()
        app.logger.info(f"DB initialized at {app.config['SQLALCHEMY_DATABASE_URI']}")

    # -----------------------
    # Routes (closures so they capture ADMIN_PASS_HASH, RESET_TZ, RESET_TIME)
    # -----------------------
    @app.before_request
    def _before_request():
        # ensure each session gets a persistent voter token used to limit votes
        ensure_voter_token()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            pw = request.form.get("password", "")
            if check_password_hash(ADMIN_PASS_HASH, pw):
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("index"))
            else:
                return render_template("login.html", error="Incorrect password")
        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @require_login
    def index():
        maybe_reset(app, RESET_TZ, RESET_TIME)
        return render_template("index.html")

    @app.route("/api/items", methods=["GET"])
    @require_login
    def api_items():
        maybe_reset(app, RESET_TZ, RESET_TIME)
        items = Item.query.order_by(Item.votes.desc(), Item.created_at.asc()).all()
        # include whether current voter has voted on each item (helpful for UI to disable bubble)
        voter = session.get("voter_token")
        voted_item_ids = set()
        if voter:
            votes = Vote.query.filter_by(voter_token=voter).all()
            voted_item_ids = {v.item_id for v in votes}
        return jsonify([{"id": it.id, "name": it.name, "votes": it.votes, "voted_by_me": (it.id in voted_item_ids)} for it in items])



    @app.route("/api/items", methods=["POST"])
    @require_login
    def api_add_item():
        maybe_reset(app, RESET_TZ, RESET_TIME)
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()

        if not name:
            return jsonify({"error": "Name required"}), 400

        # --- NEW: case-insensitive duplicate check ---
        existing = Item.query.filter(func.lower(Item.name) == name.lower()).first()
        if existing:
            return jsonify({"error": "This item is already in the list."}), 400
        # ------------------------------------------------

        it = Item(name=name, votes=0)
        db.session.add(it)
        db.session.commit()

        return jsonify({"ok": True, "id": it.id, "name": it.name, "votes": it.votes})


    @app.route("/api/items/<int:item_id>/vote", methods=["POST"])
    @require_login
    def api_vote(item_id):
        maybe_reset(app, RESET_TZ, RESET_TIME)
        voter = session.get("voter_token")
        if not voter:
            # should never happen because of before_request, but just in case
            voter = ensure_voter_token()

        # Ensure item exists
        it = Item.query.get_or_404(item_id)

        # Try to insert a Vote row. UniqueConstraint will prevent double-voting for same voter_token+item.
        v = Vote(item_id=item_id, voter_token=voter)
        db.session.add(v)
        try:
            # commit the Vote; if it violates unique constraint, IntegrityError will be raised
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"ok": False, "error": "You have already voted for this item."}), 400

        # Only increment Item.votes when Vote insertion succeeded
        it.votes = Item.votes + 1 if isinstance(Item.votes, int) else it.votes + 1  # safe increment
        # better: increment the specific instance's votes
        it.votes = it.votes + 1
        db.session.add(it)
        db.session.commit()
        return jsonify({"ok": True, "id": it.id, "votes": it.votes})

    @app.route("/health")
    def health():
        return "OK", 200

    # attach config info to app for debugging
    app.config["RESET_TZ"] = RESET_TZ
    app.config["RESET_TIME"] = RESET_TIME.isoformat()

    return app


# Create top-level app variable for Gunicorn / wsgi servers
app = create_app()


# If running locally via `python app.py`, start Flask dev server (useful for quick dev)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.logger.info(f"Starting dev server (DB={app.config['SQLALCHEMY_DATABASE_URI']}) Reset at {app.config['RESET_TIME']} in TZ={app.config['RESET_TZ']}")
    app.run(host="0.0.0.0", port=port)
