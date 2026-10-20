from flask import (
    Flask, Response, jsonify, render_template, request, send_from_directory,
)
import requests
import os
import re
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from groq import Groq

from auth import init_auth, current_user
from features import init_features, forecast_context
from reliability import init_reliability

# =========================================================
# CONFIGURATION
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load environment variables from this project's .env file.
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Brevo settings are loaded here to verify configuration at startup.
# The actual email delivery is handled by auth.py.
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "").strip()

# ---- Google Search Console / SEO -------------------------------------------
# Public address of the deployed site (no trailing slash). Optional: if
# SITE_URL is not set, the address the visitor (or Googlebot) used to reach
# the site is used automatically, so the sitemap can never point to a wrong
# domain. Set SITE_URL=https://your-domain.com to force a fixed address.
SITE_URL = os.getenv("SITE_URL", "").strip().rstrip("/")


def site_url():
    if SITE_URL:
        return SITE_URL
    # Render sits behind a proxy; always use https for the public address.
    host = request.headers.get("X-Forwarded-Host", request.host)
    scheme = "http" if host.startswith(("127.0.0.1", "localhost")) else "https"
    return "%s://%s" % (scheme, host)

# File name given by Search Console ("HTML file" verification method).
GOOGLE_VERIFICATION_FILE = os.getenv(
    "GOOGLE_VERIFICATION_FILE",
    "google825a0e9664b14fbc.html",
).strip()

# Pages that anyone (including Googlebot) can open without logging in and that
# answer with HTTP 200. "/" is NOT listed because it redirects logged-out
# visitors to /login, and Search Console reports redirecting URLs in a
# sitemap as a problem.
PUBLIC_SEO_PAGES = ["/login", "/register"]

GOOGLE_VERIFY_PATH_RE = re.compile(r"^/google[0-9a-f]{16}\.html$")

print("=" * 60)
print("WeatherGPT Starting...")
print("Weather API Key Loaded:", bool(WEATHER_API_KEY))
print("Groq API Key Loaded:", bool(GROQ_API_KEY))
print("Brevo API Key Loaded:", bool(BREVO_API_KEY))
print("Brevo Sender Email Configured:", bool(BREVO_SENDER_EMAIL))
print("Site URL:", SITE_URL or "(auto-detected from request)")
print("=" * 60)

# =========================================================
# GROQ CLIENT
# =========================================================

groq_client = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return render_template("index.html", user=current_user())

# =========================================================
# GOOGLE SEARCH CONSOLE FILES (PUBLIC - NO LOGIN NEEDED)
# =========================================================

def _seo_response(body, mimetype):
    response = Response(body, status=200, mimetype=mimetype)
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
