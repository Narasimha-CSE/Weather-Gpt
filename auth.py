# -*- coding: utf-8 -*-
"""WeatherGPT authentication (SQLite sessions).

* Email OTP  : register (verify email -> account created -> go to login) and login (email -> OTP).
* Phone OTP  : SMS code through Twilio (see .env) - TWILIO_* keys, or PHONE_OTP_DEV=1 to print codes in the console.
* Google / Facebook : OAuth 2.0 authorization-code flow (keys in .env).
"""

import hashlib
import hmac
import os
import random
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests
from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

bp = Blueprint("auth", __name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "/tmp/weathergpt-data"
DB_PATH = os.path.join(DATA_DIR, "weathergpt.db")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+[1-9]\d{9,14}$")

# ---------------------------------------------------------------------------
# Settings (all read lazily because app.py calls load_dotenv() after importing this module)
# ---------------------------------------------------------------------------

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

OTP_TTL = 600          # OTP valid for 10 minutes
OTP_MAX_TRIES = 5      # wrong guesses allowed per OTP
OTP_RESEND_GAP = 30    # seconds between sends to the same email / phone


def smtp_credentials():
    email = os.getenv("SMTP_EMAIL", "mamidinarasimha143@gmail.com").strip()
    password = os.getenv("SMTP_APP_PASSWORD", "").replace(" ", "")
    return email, password


# key -> {"mode", "name", "otp_hash", "expires", "tries", "sent_at"}   (in memory)
# email OTPs use the email as key, phone OTPs use "tel:+91..."
_pending = {}


# ---------------------------------------------------------------------------
# Secret key + database
# ---------------------------------------------------------------------------

def load_secret_key():
    """Load SECRET_KEY from environment variables."""
    env_key = os.getenv("SECRET_KEY")

    if not env_key:
        raise RuntimeError(
            "SECRET_KEY is missing. Please configure it in Vercel Environment Variables."
        )

    return env_key


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as conn:
        # password_hash is kept so existing databases keep working; it is not used for sign-in.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            )""")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "phone" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        if "provider" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN provider TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL")


def init_auth(app):
    app.secret_key = load_secret_key()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="weathergpt_session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )

    # HTTPS-only cookies should be enabled when deployed over HTTPS.
    if os.getenv("COOKIE_SECURE", "").strip() == "1":
        app.config["SESSION_COOKIE_SECURE"] = True

    init_db()
    app.register_blueprint(bp)

    @app.before_request
    def require_login():
        endpoint = request.endpoint or ""
        path = request.path

        # Search-engine files are public (also handled earlier in app.py).
        public_paths = {
            "/robots.txt",
            "/sitemap.xml",
            "/google825a0e9664b14fbc.html",
        }
        if path in public_paths:
            return None

        if endpoint == "static" or endpoint.startswith("auth."):
            return None
        if current_user():
            return None
        if request.path == "/":
            return redirect(url_for("auth.login_page"))
        return jsonify({"error": "Please log in to continue.", "login_required": True}), 401

    @app.after_request
    def no_cache_for_private(resp):
        if request.endpoint and not request.path.startswith("/static") and request.method == "GET":
            resp.headers.setdefault("Cache-Control", "no-cache")
        return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    with db() as conn:
        row = conn.execute("SELECT id, name, email FROM users WHERE id = ?", (uid,)).fetchone()
    if not row:
        session.clear()
        return None
    return {"id": row["id"], "name": row["name"], "email": row["email"]}


def start_session(user_id, remember):
    session.clear()
    session["user_id"] = user_id
    session.permanent = bool(remember)


def clean_email(value):
    return str(value or "").strip().lower()


def valid_email(email):
    return bool(EMAIL_RE.match(email)) and len(email) <= 120


def clean_name(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_phone(value):
    """Return an E.164 number (+919876543210) or None. 10-digit numbers get PHONE_DEFAULT_COUNTRY (+91)."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if raw.startswith("+"):
        number = "+" + digits
    elif len(digits) == 10:
        number = os.getenv("PHONE_DEFAULT_COUNTRY", "+91").strip() + digits
    elif raw.startswith("00"):
        number = "+" + digits[2:]
    else:
        number = "+" + digits
    return number if PHONE_RE.match(number) else None


# ---------------------------------------------------------------------------
# Captcha (server-side) + trusted devices
#
# * The captcha image is an SVG made on the server. The session only keeps a salted HMAC of the answer
#   (never the text), the answer works once and expires after 5 minutes.
# * An email is verified ONCE (OTP at registration, or Google). That moment marks this browser as a trusted
#   device with a signed, HttpOnly cookie. After that, "email + captcha" is enough to log in on this device.
#   By default that is all the login page asks for (email + captcha, no emailed code), on any device.
#   Set STRICT_NEW_DEVICE_OTP=1 in .env to also require the emailed code once on a device that has not
#   verified the account yet (safer: knowing an email address alone is then not enough).
# ---------------------------------------------------------------------------

CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CAPTCHA_TTL = 300
DEVICE_COOKIE = "wg_device"
DEVICE_MAX_AGE = 180 * 24 * 3600
_hits = {}   # rate-limit buckets (in memory)


def make_captcha_text():
    return "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(5))


def _captcha_digest(text, nonce):
    return hmac.new(current_app.secret_key.encode(), (nonce + text.upper()).encode(), hashlib.sha256).hexdigest()


def captcha_svg(text):
    rnd = random.SystemRandom()
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="170" height="56" viewBox="0 0 170 56" role="img" aria-label="Captcha">',
           '<rect width="170" height="56" rx="10" fill="#0e2230"/>']
    for _ in range(7):
        out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="hsl(%d,60%%,60%%)" stroke-width="1.4" opacity=".55"/>'
                   % (rnd.randint(0, 170), rnd.randint(0, 56), rnd.randint(0, 170), rnd.randint(0, 56), rnd.randint(0, 360)))
    for i, ch in enumerate(text):
        x, y = 16 + i * 29, 37 + rnd.randint(-4, 4)
        out.append('<text x="%d" y="%d" font-size="%d" font-weight="700" font-family="Georgia,serif" fill="hsl(%d,75%%,72%%)" '
                   'transform="rotate(%d %d %d)">%s</text>' % (x, y, rnd.randint(26, 32), rnd.randint(0, 360), rnd.randint(-22, 22), x, y, ch))
    for _ in range(40):
        out.append('<circle cx="%d" cy="%d" r="1.2" fill="#9fb4c4" opacity=".6"/>' % (rnd.randint(0, 170), rnd.randint(0, 56)))
    out.append('<path d="M0 %d Q 60 %d 120 %d T 170 %d" fill="none" stroke="#38d996" stroke-width="1.6" opacity=".7"/>'
               % (rnd.randint(10, 46), rnd.randint(0, 56), rnd.randint(10, 46), rnd.randint(10, 46)))
    out.append("</svg>")
    return "".join(out)


def verify_captcha(answer):
    """One-shot check: the stored captcha is consumed whether the answer is right or wrong."""
    c = session.pop("captcha", None)
    if not isinstance(c, dict) or time.time() > c.get("e", 0):
        return False
    answer = re.sub(r"\s+", "", str(answer or "")).upper()
    return len(answer) >= 4 and hmac.compare_digest(str(c.get("h", "")), _captcha_digest(answer, str(c.get("n", ""))))


def rate_limited(key, limit, window=300):
    now = time.time()
    hits = [t for t in _hits.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _hits[key] = hits
        return True
    hits.append(now)
    _hits[key] = hits
    return False


def _device_serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="wg-device-v1")


def device_users():
    """User ids this browser has verified on (empty when the cookie is missing, forged or old)."""
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        return []
    try:
        data = _device_serializer().loads(raw, max_age=DEVICE_MAX_AGE)
    except Exception:
        return []
    ids = data.get("u") if isinstance(data, dict) else None
    return [i for i in ids if isinstance(i, int)] if isinstance(ids, list) else []


def trust_device(resp, user_id):
    ids = device_users()
    if user_id not in ids:
        ids.append(user_id)
    resp.set_cookie(DEVICE_COOKIE, _device_serializer().dumps({"u": ids[-5:]}), max_age=DEVICE_MAX_AGE,
                    httponly=True, samesite="Lax", secure=os.getenv("COOKIE_SECURE", "").strip() == "1")
    return resp


# ---------------------------------------------------------------------------
# One-time codes (shared by email and phone)
# ---------------------------------------------------------------------------

def make_code(key, name, mode):
    otp = "%06d" % secrets.randbelow(1000000)
    _pending[key] = {
        "mode": mode,
        "name": name,
        "otp_hash": generate_password_hash(otp),
        "expires": time.time() + OTP_TTL,
        "tries": 0,
        "sent_at": time.time(),
    }
    return otp


def too_soon(key):
    p = _pending.get(key)
    return bool(p) and time.time() - p["sent_at"] < OTP_RESEND_GAP


def check_code(key, code):
    """Return (pending, None) when the code is right, otherwise (None, error_response)."""
    p = _pending.get(key)
    if not p:
        return None, (jsonify({"error": "No code requested. Please request a new one."}), 400)
    if time.time() > p["expires"]:
        _pending.pop(key, None)
        return None, (jsonify({"error": "Code expired. Please request a new one."}), 400)
    if p["tries"] >= OTP_MAX_TRIES:
        _pending.pop(key, None)
        return None, (jsonify({"error": "Too many wrong attempts. Please request a new code."}), 429)
    if not check_password_hash(p["otp_hash"], code):
        p["tries"] += 1
        return None, (jsonify({"error": "Incorrect code."}), 400)
    return p, None


# ---------------------------------------------------------------------------
# Email OTP: Brevo transactional email API (used when BREVO_API_KEY is set,
# works on hosts such as Render that block SMTP), otherwise Gmail SMTP.
# ---------------------------------------------------------------------------

def send_otp_email_brevo(to_email, name, otp):
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "").strip()
    sender_name = os.getenv("BREVO_SENDER_NAME", "WeatherGPT").strip()

    if not api_key:
        raise RuntimeError("BREVO_API_KEY is missing from .env.")

    if not sender_email:
        raise RuntimeError("BREVO_SENDER_EMAIL is missing from .env.")

    payload = {
        "sender": {
            "name": sender_name,
            "email": sender_email,
        },
        "to": [
            {
                "email": to_email,
                "name": name or to_email,
            }
        ],
        "subject": "Your WeatherGPT verification code",
        "textContent": (
            "Hi %s,\n\n"
            "Your WeatherGPT verification code is: %s\n\n"
            "This code expires in 10 minutes. "
            "If you did not request it, please ignore this email."
        ) % (name or "there", otp),
    }

    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        json=payload,
        timeout=15,
    )

    if not response.ok:
        # Do not expose the API key or the full provider response to users.
        raise RuntimeError(
            "Brevo email request failed with HTTP %s."
            % response.status_code
        )


def send_otp_email(to_email, name, otp):
    if os.getenv("BREVO_API_KEY", "").strip():
        return send_otp_email_brevo(to_email, name, otp)

    # Fallback: Gmail SMTP
    smtp_email, smtp_password = smtp_credentials()
    if not smtp_password:
        raise RuntimeError("SMTP_APP_PASSWORD is not set in .env.")
    msg = EmailMessage()
    msg["Subject"] = "Your WeatherGPT verification code"
    msg["From"] = "WeatherGPT <%s>" % smtp_email
    msg["To"] = to_email
    msg.set_content(
        "Hi %s,\n\nYour WeatherGPT one-time code is: %s\n\n"
        "It expires in 10 minutes. If you didn't request this, ignore this email.\n"
        % (name, otp))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(smtp_email, smtp_password)
        server.send_message(msg)


def issue_otp(email, name, mode):
    otp = make_code(email, name, mode)
    try:
        send_otp_email(email, name, otp)
    except Exception:
        _pending.pop(email, None)
        raise


def otp_sent_response(email, message="We sent a 6-digit code to your email."):
    return jsonify({"ok": True, "otp_required": True, "email": email, "message": message})


# ---------------------------------------------------------------------------
# Phone OTP (SMS through Twilio)
# ---------------------------------------------------------------------------

class SmsNotConfigured(RuntimeError):
    pass


def send_sms(to_number, body):
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    sender = os.getenv("TWILIO_FROM", "").strip()
    service = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "").strip()
    if sid and token and (sender or service):
        data = {"To": to_number, "Body": body}
        if service:
            data["MessagingServiceSid"] = service
        else:
            data["From"] = sender
        res = requests.post("https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % sid,
                            data=data, auth=(sid, token), timeout=15)
        res.raise_for_status()
        return
    if os.getenv("PHONE_OTP_DEV", "").strip() == "1":
        # Development only: no SMS provider configured, so show the message in the server console.
        print("[WeatherGPT DEV SMS] to %s: %s" % (to_number, body))
        return
    raise SmsNotConfigured()


def issue_phone_otp(phone, name, mode):
    key = "tel:" + phone
    otp = make_code(key, name, mode)
    try:
        send_sms(phone, "Your WeatherGPT code is %s. It expires in 10 minutes." % otp)
    except Exception:
        _pending.pop(key, None)
        raise


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.route("/login")
def login_page():
    if current_user():
        return redirect("/")
    return render_template("auth.html", mode="login")


@bp.route("/register")
def register_page():
    if current_user():
        return redirect("/")
    return render_template("auth.html", mode="register")


@bp.route("/logout")
def logout_page():
    session.clear()
    return redirect(url_for("auth.login_page"))


# ---------------------------------------------------------------------------
# JSON API - email
# ---------------------------------------------------------------------------

@bp.route("/auth/register", methods=["POST"])
def register():
    """Step 1 (new user): send an OTP to the email. The account is created in /auth/verify."""
    data = request.get_json(silent=True) or {}
    name = clean_name(data.get("name"))
    email = clean_email(data.get("email"))

    errors = {}
    if not (2 <= len(name) <= 50):
        errors["name"] = "Enter your name (2–50 characters)."
    if not valid_email(email):
        errors["email"] = "Enter a valid email address."
    if errors:
        return jsonify({"error": next(iter(errors.values())), "fields": errors}), 400

    with db() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    if exists:
        return jsonify({"error": "That email is already registered. Log in instead.",
                        "fields": {"email": "That email is already registered."}}), 409

    if too_soon(email):
        return jsonify({"error": "Please wait a few seconds before requesting another code."}), 429
    try:
        issue_otp(email, name, "register")
    except Exception:
        app_logger_error("Failed to send registration OTP.")
        return jsonify({"error": "Could not send the verification email. Try again."}), 502
    return otp_sent_response(email)


@bp.route("/auth/captcha")
def captcha():
    text = make_captcha_text()
    nonce = secrets.token_hex(8)
    session["captcha"] = {"n": nonce, "h": _captcha_digest(text, nonce), "e": time.time() + CAPTCHA_TTL}
    resp = Response(captcha_svg(text), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/auth/login", methods=["POST"])
def login():
    """Email + captcha. The email was verified when the account was created (OTP) or by Google, so the
    login page does not ask for an emailed code. With STRICT_NEW_DEVICE_OTP=1 a device that has not verified
    the account yet still gets the one-time code (step 2 is /auth/verify)."""
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))

    if not email:
        return jsonify({"error": "Enter your email."}), 400
    if not valid_email(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if rate_limited("login-ip:" + (request.remote_addr or "?"), 30) or rate_limited("login-mail:" + email, 10):
        return jsonify({"error": "Too many attempts. Please wait a few minutes and try again."}), 429
    if not verify_captcha(data.get("captcha")):
        return jsonify({"error": "Captcha is incorrect. Try the new one.", "captcha_failed": True,
                        "fields": {"captcha": "Captcha is incorrect."}}), 400

    with db() as conn:
        row = conn.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return jsonify({"error": "No account found for that email. Please register first."}), 404

    strict = os.getenv("STRICT_NEW_DEVICE_OTP", "").strip() == "1"
    if not strict or row["id"] in device_users():
        now = datetime.now(timezone.utc).isoformat()
        with db() as conn:
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, row["id"]))
        start_session(row["id"], bool(data.get("remember", True)))
        resp = jsonify({"ok": True, "verified": "device", "user": {"name": row["name"], "email": email}, "redirect": "/"})
        return trust_device(resp, row["id"])

    if too_soon(email):
        return jsonify({"error": "Please wait a few seconds before requesting another code."}), 429
    try:
        issue_otp(email, row["name"], "login")
    except Exception:
        app_logger_error("Failed to send login OTP.")
        return jsonify({"error": "Could not send the verification email. Try again."}), 502
    return otp_sent_response(email, "New device: we sent a 6-digit code to your email. You only need it once on this device.")


@bp.route("/auth/verify", methods=["POST"])
def verify_otp():
    """Step 2.
    * register: the code proves the email, the account is created and the user is sent to the login section.
    * login   : the code logs the user in.
    """
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))
    code = str(data.get("otp", "")).strip()
    remember = bool(data.get("remember", True))

    p, err = check_code(email, code)
    if err:
        return err

    now = datetime.now(timezone.utc).isoformat()
    try:
        with db() as conn:
            row = conn.execute("SELECT id, name FROM users WHERE email = ?", (email,)).fetchone()
            if p["mode"] == "register":
                if row:
                    _pending.pop(email, None)
                    return jsonify({"error": "That email is already registered. Log in instead."}), 409
                cur = conn.execute(
                    "INSERT INTO users (name, email, password_hash, created_at, last_login, provider) VALUES (?, ?, ?, ?, ?, ?)",
                    (p["name"], email, "!otp-only", now, None, "email"))
                _pending.pop(email, None)
                # Account created and email verified; no session yet - the page now opens the login section.
                # This browser is marked as trusted, so the next login only needs the captcha.
                resp = jsonify({"ok": True, "registered": True,
                                "user": {"name": p["name"], "email": email}, "redirect": None})
                resp.status_code = 201
                return trust_device(resp, cur.lastrowid)
            if not row:
                _pending.pop(email, None)
                return jsonify({"error": "No account found for that email. Please register first."}), 404
            user_id, name = row["id"], row["name"]
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
    except sqlite3.IntegrityError:
        _pending.pop(email, None)
        return jsonify({"error": "That email is already registered. Log in instead."}), 409

    _pending.pop(email, None)
    start_session(user_id, remember)
    resp = jsonify({"ok": True, "user": {"name": name, "email": email}, "redirect": "/"})
    return trust_device(resp, user_id)


@bp.route("/auth/resend", methods=["POST"])
def resend_otp():
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))
    p = _pending.get(email)
    if not p:
        return jsonify({"error": "No code requested for this email. Please start again."}), 400
    if too_soon(email):
        return jsonify({"error": "Please wait a few seconds before requesting another code."}), 429
    try:
        issue_otp(email, p["name"], p["mode"])
    except Exception:
        app_logger_error("Failed to resend email OTP.")
        return jsonify({"error": "Could not send the verification email. Try again."}), 502
    return jsonify({"ok": True, "message": "A new code was sent."})


# ---------------------------------------------------------------------------
# JSON API - phone
# ---------------------------------------------------------------------------

@bp.route("/auth/phone/send", methods=["POST"])
def phone_send():
    data = request.get_json(silent=True) or {}
    phone = normalize_phone(data.get("phone"))
    name = clean_name(data.get("name"))
    if not phone:
        return jsonify({"error": "Enter a valid phone number (with country code if not Indian).",
                        "fields": {"phone": "Enter a valid phone number."}}), 400
    if name and not (2 <= len(name) <= 50):
        return jsonify({"error": "Name must be 2–50 characters.", "fields": {"name": "Name must be 2–50 characters."}}), 400
    if too_soon("tel:" + phone):
        return jsonify({"error": "Please wait a few seconds before requesting another code."}), 429
    try:
        issue_phone_otp(phone, name, "phone")
    except SmsNotConfigured:
        return jsonify({"error": "Phone login isn't set up yet. Add the TWILIO_* keys to .env "
                                 "(or PHONE_OTP_DEV=1 for local testing)."}), 503
    except Exception:
        app_logger_error("Failed to send phone OTP.")
        return jsonify({"error": "Could not send the SMS. Check the number and try again."}), 502
    return jsonify({"ok": True, "otp_required": True, "phone": phone,
                    "message": "We sent a 6-digit code by SMS."})


@bp.route("/auth/phone/verify", methods=["POST"])
def phone_verify():
    data = request.get_json(silent=True) or {}
    phone = normalize_phone(data.get("phone"))
    code = str(data.get("otp", "")).strip()
    remember = bool(data.get("remember", True))
    if not phone:
        return jsonify({"error": "Enter a valid phone number."}), 400

    p, err = check_code("tel:" + phone, code)
    if err:
        return err

    now = datetime.now(timezone.utc).isoformat()
    try:
        with db() as conn:
            row = conn.execute("SELECT id, name, email FROM users WHERE phone = ?", (phone,)).fetchone()
            if row:
                user_id, name, email = row["id"], row["name"], row["email"]
                conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
            else:
                name = p["name"] or ("User " + phone[-4:])
                email = "%s@phone.weathergpt.local" % phone.lstrip("+")
                cur = conn.execute(
                    "INSERT INTO users (name, email, password_hash, created_at, last_login, phone, provider) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (name, email, "!phone-otp", now, now, phone, "phone"))
                user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        _pending.pop("tel:" + phone, None)
        return jsonify({"error": "That number is already registered. Please try again."}), 409

    _pending.pop("tel:" + phone, None)
    start_session(user_id, remember)
    resp = jsonify({"ok": True, "user": {"name": name, "email": email}, "redirect": "/"})
    return trust_device(resp, user_id)


# ---------------------------------------------------------------------------
# Google / Facebook (OAuth 2.0 authorization-code flow)
# ---------------------------------------------------------------------------

def _providers():
    return {
        "google": {
            "label": "Google",
            "id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "scope": "openid email profile",
            "extra": {"prompt": "select_account"},
        },
        "facebook": {
            "label": "Facebook",
            "id": os.getenv("FACEBOOK_APP_ID", "").strip(),
            "secret": os.getenv("FACEBOOK_APP_SECRET", "").strip(),
            "auth_url": "https://www.facebook.com/v19.0/dialog/oauth",
            "scope": "email,public_profile",
            "extra": {},
        },
    }


def _redirect_uri(provider):
    base = os.getenv("OAUTH_REDIRECT_BASE", "").strip().rstrip("/")
    path = url_for("auth.social_callback", provider=provider)
    return (base + path) if base else url_for("auth.social_callback", provider=provider, _external=True)


def _login_error(code):
    return redirect(url_for("auth.login_page", social_error=code))


def _fetch_profile(provider, cfg, code):
    """Exchange the code for a token and return (name, email, email_verified)."""
    redirect_uri = _redirect_uri(provider)
    if provider == "google":
        tok = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": cfg["id"], "client_secret": cfg["secret"],
            "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=15)
        tok.raise_for_status()
        access = tok.json()["access_token"]
        info = requests.get("https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": "Bearer " + access}, timeout=15)
        info.raise_for_status()
        j = info.json()
        return clean_name(j.get("name") or j.get("given_name") or ""), clean_email(j.get("email")), bool(j.get("email_verified"))
    tok = requests.get("https://graph.facebook.com/v19.0/oauth/access_token", params={
        "client_id": cfg["id"], "client_secret": cfg["secret"],
        "redirect_uri": redirect_uri, "code": code}, timeout=15)
    tok.raise_for_status()
    access = tok.json()["access_token"]
    info = requests.get("https://graph.facebook.com/me",
                        params={"fields": "id,name,email", "access_token": access}, timeout=15)
    info.raise_for_status()
    j = info.json()
    email = clean_email(j.get("email"))
    if not email:
        email = "fb%s@facebook.weathergpt.local" % j.get("id", "user")
    return clean_name(j.get("name") or ""), email, True


@bp.route("/auth/social/<provider>")
def social_start(provider):
    cfg = _providers().get(provider)
    if not cfg:
        return _login_error("unknown_provider")
    if not (cfg["id"] and cfg["secret"]):
        return _login_error(provider + "_not_configured")
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {"client_id": cfg["id"], "redirect_uri": _redirect_uri(provider), "response_type": "code",
              "scope": cfg["scope"], "state": state}
    params.update(cfg["extra"])
    return redirect(cfg["auth_url"] + "?" + requests.compat.urlencode(params))


@bp.route("/auth/social/<provider>/callback")
def social_callback(provider):
    cfg = _providers().get(provider)
    if not cfg or not (cfg["id"] and cfg["secret"]):
        return _login_error((provider if cfg else "unknown") + "_not_configured")
    if request.args.get("error"):
        return _login_error("denied")
    expected = session.pop("oauth_state", None)
    if not expected or not secrets.compare_digest(expected, request.args.get("state", "")):
        return _login_error("failed")
    code = request.args.get("code", "")
    if not code:
        return _login_error("failed")
    try:
        name, email, verified = _fetch_profile(provider, cfg, code)
    except Exception:
        return _login_error("failed")
    if not valid_email(email) and not email.endswith(".weathergpt.local"):
        return _login_error("failed")
    if not verified:
        return _login_error("unverified")

    now = datetime.now(timezone.utc).isoformat()
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            user_id = row["id"]
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
        else:
            display = name if 2 <= len(name) <= 50 else email.split("@")[0][:50] or "User"
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, created_at, last_login, provider) VALUES (?, ?, ?, ?, ?, ?)",
                (display, email, "!oauth", now, now, provider))
            user_id = cur.lastrowid
    # The provider already verified this email, so this browser becomes a trusted device: later logins can
    # use email + captcha. "?welcome=1" tells the home page to play the logo animation.
    start_session(user_id, True)
    return trust_device(redirect("/?welcome=1"), user_id)


@bp.route("/auth/forget-device", methods=["POST"])
def forget_device():
    resp = jsonify({"ok": True})
    resp.delete_cookie(DEVICE_COOKIE)
    return resp


@bp.route("/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True, "redirect": "/login"})


@bp.route("/auth/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user})


# ---------------------------------------------------------------------------
# Safe logging
# ---------------------------------------------------------------------------

def app_logger_error(message):
    # Do not log OTP values, API keys, or message contents.
    print("[WeatherGPT auth] " + message)
