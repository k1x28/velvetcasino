"""
Velvet Casino — Flask Backend
Handles: auth, leaderboard sync, avatar storage, session management
Run:  pip install flask && python server.py
Open: http://localhost:5000
"""

from flask import Flask, request, jsonify, session, send_from_directory
import json, os, hashlib, time
from functools import wraps

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "velvet-casino-secret-change-in-prod")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,   # set True in production with HTTPS
)

DB_FILE = "users.json"

# ── Database helpers ─────────────────────────────────────────────────────────

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=2)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def get_current_user():
    if "username" not in session:
        return None
    db = load_db()
    return db.get(session["username"])

def save_current_user(user):
    db = load_db()
    db[user["username"]] = user
    save_db(db)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return jsonify({"error": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated

def public(u):
    """Strip password before sending to client."""
    if not u:
        return None
    return {k: v for k, v in u.items() if k != "password"}

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    if not username or len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if not password or len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    db = load_db()
    if username in db:
        return jsonify({"error": "Username already taken"}), 400
    user = {
        "username": username,
        "password": hash_pw(password),
        "balance": 1000.0,
        "avatar": "",
        "stats": {"wins": 0, "losses": 0, "total_wagered": 0.0, "biggest_win": 0.0},
        "potions": {"luck": 0, "greed": 0, "fortune": 0, "chaos": 0},
        "activePotions": [],
        "created": time.time(),
    }
    db[username] = user
    save_db(db)
    session["username"] = username
    return jsonify({"user": public(user)})

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    db = load_db()
    user = db.get(username)
    if not user or user["password"] != hash_pw(password):
        return jsonify({"error": "Invalid username or password"}), 401
    session["username"] = username
    return jsonify({"user": public(user)})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("username", None)
    return jsonify({"ok": True})

@app.route("/api/me")
def me():
    user = get_current_user()
    return jsonify({"user": public(user)})

# ── Leaderboard ───────────────────────────────────────────────────────────────

@app.route("/api/leaderboard", methods=["GET"])
def leaderboard_get():
    """Return all players sorted by balance (top 50)."""
    db = load_db()
    players = []
    for u in db.values():
        players.append({
            "username": u["username"],
            "balance": u.get("balance", 0),
            "avatar": u.get("avatar", ""),
            "stats": u.get("stats", {}),
        })
    players.sort(key=lambda x: x["balance"], reverse=True)
    return jsonify(players[:50])

@app.route("/api/leaderboard", methods=["POST"])
def leaderboard_post():
    """
    Called by the client after every bet to sync the latest balance/stats.
    The client sends: { username, balance, stats, avatar }
    We update the server record — but ONLY non-sensitive fields.
    Auth is checked via session so random POSTs can't spoof other players.
    """
    if "username" not in session:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.json or {}
    sender = session["username"]

    # Only allow updating your own record
    if data.get("username") != sender:
        return jsonify({"error": "Forbidden"}), 403

    db = load_db()
    user = db.get(sender)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Merge safe fields only
    if "balance" in data:
        user["balance"] = round(float(data["balance"]), 2)
    if "stats" in data and isinstance(data["stats"], dict):
        user["stats"] = {
            "wins": int(data["stats"].get("wins", user["stats"].get("wins", 0))),
            "losses": int(data["stats"].get("losses", user["stats"].get("losses", 0))),
            "total_wagered": round(float(data["stats"].get("total_wagered", user["stats"].get("total_wagered", 0))), 2),
            "biggest_win": round(float(data["stats"].get("biggest_win", user["stats"].get("biggest_win", 0))), 2),
        }
    if "avatar" in data:
        user["avatar"] = data["avatar"]  # base64 string

    db[sender] = user
    save_db(db)
    return jsonify({"ok": True})

# ── Avatar upload (explicit endpoint) ────────────────────────────────────────

@app.route("/api/avatar", methods=["POST"])
@require_auth
def set_avatar():
    data = request.json or {}
    avatar = data.get("avatar", "")
    if avatar and not avatar.startswith("data:image/"):
        return jsonify({"error": "Invalid image format"}), 400
    user = get_current_user()
    if not user:
        return jsonify({"error": "User not found"}), 404
    user["avatar"] = avatar
    save_current_user(user)
    return jsonify({"ok": True})

# ── Profile / potions sync ────────────────────────────────────────────────────

@app.route("/api/sync", methods=["POST"])
@require_auth
def sync():
    """
    Full user sync — called when potions are activated or major state changes.
    Accepts: { balance, stats, potions, activePotions, avatar }
    """
    data = request.json or {}
    user = get_current_user()
    if not user:
        return jsonify({"error": "User not found"}), 404

    safe_fields = ["balance", "stats", "potions", "activePotions", "avatar"]
    for field in safe_fields:
        if field in data:
            user[field] = data[field]

    save_current_user(user)
    return jsonify({"user": public(user)})

# ── Serve the frontend ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    print("\n╔══════════════════════════════════════════╗")
    print("║        VELVET CASINO SERVER              ║")
    print("╠══════════════════════════════════════════╣")
    print("║  Open:  http://localhost:5000            ║")
    print("║  DB:    users.json (auto-created)        ║")
    print("║  Stop:  Ctrl+C                           ║")
    print("╚══════════════════════════════════════════╝\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
