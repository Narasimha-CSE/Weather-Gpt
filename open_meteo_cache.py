# -*- coding: utf-8 -*-
"""WeatherGPT persistent API cache with HTTP 429 protection.

Used by features.py and reliability.py (their om_get() delegates to cached_get() below).

What it does
------------
1. Fresh cache    - every successful response is stored in SQLite (survives restarts) and re-used for 6 hours.
2. Stale fallback - if Open-Meteo answers HTTP 429 (rate limit) or fails temporarily (5xx / timeout / network),
                    the last good response is served for up to 7 days instead of showing an error.
3. No 429 retries - a 429 is never retried. The host is put on "cool-down" (until the limit resets, taken from the
                    API's own message or Retry-After header) and NO request is sent while it lasts.
4. RateLimitError - raised only when the API is limited AND nothing is cached, so callers can stop making
                    follow-up requests instead of hammering the API.

The cache lives in data/open_meteo_cache.sqlite3 next to this file (override with env var
WEATHERGPT_CACHE_DB). If the hosting disk is read-only the module silently falls back to memory only.
"""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("WEATHERGPT_CACHE_DB") or os.path.join(BASE_DIR, "data", "open_meteo_cache.sqlite3")

FRESH_TTL = 6 * 60 * 60          # successful responses are used directly for 6 hours
STALE_TTL = 7 * 24 * 60 * 60     # ...and as an emergency fallback for up to 7 days
DEFAULT_COOLDOWN = 10 * 60       # 429 without any hint about when the limit resets

_lock = threading.Lock()
_ready = False
_mem = {}                         # fallback / speed-up: cache_key -> (created_at, payload_text)
_mem_block = {}                   # host -> (until_epoch, reason)


class RateLimitError(RuntimeError):
    """HTTP 429 from the API and no cached copy to fall back on."""


class CachedResponse(object):
    """Minimal stand-in for requests.Response (what features.py / reliability.py use)."""
    status_code = 200

    def __init__(self, text, created_at, from_cache, stale):
        self.text = text
        self.created_at = created_at
        self.from_cache = from_cache
        self.stale = stale
        self.headers = {}

    def json(self):
        return json.loads(self.text)


# ---------------------------------------------------------------------------
# SQLite helpers (every failure degrades to "no persistent cache", never to an exception)
# ---------------------------------------------------------------------------

def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass
    return conn


def _init():
    global _ready
    if _ready:
        return True
    with _lock:
        if _ready:
            return True
        try:
            conn = _connect()
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS api_cache ("
                             "cache_key TEXT PRIMARY KEY, url TEXT, payload TEXT NOT NULL, created_at REAL NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS api_block ("
                             "host TEXT PRIMARY KEY, until REAL NOT NULL, reason TEXT)")
                conn.execute("DELETE FROM api_cache WHERE created_at < ?", (time.time() - STALE_TTL,))
                conn.commit()
            finally:
                conn.close()
            _ready = True
        except Exception:
            # data/ not writable (e.g. Vercel / read-only disk): retry once in the system temp folder
            global DB_PATH
            tmp = os.path.join(tempfile.gettempdir(), "open_meteo_cache.sqlite3")
            if DB_PATH == tmp:
                return False
            DB_PATH = tmp
            _lock.release()
            try:
                return _init()
            finally:
                _lock.acquire()
    return True


def _norm_coord(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    try:
        return ",".join(str(round(float(x), 2)) for x in str(v).split(","))
    except ValueError:
        return str(v)


def make_key(url, params):
    """Stable key. Coordinates are rounded to 2 decimals (~1 km, finer than the weather model grid) so that
    users standing a few metres apart share one cached response."""
    p = {}
    for k, v in (params or {}).items():
        p[k] = _norm_coord(v) if k in ("latitude", "longitude") else v
    raw = json.dumps({"url": url, "params": p}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read(key):
    item = _mem.get(key)
    if item:
        return item
    if not _init():
        return None
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT created_at, payload FROM api_cache WHERE cache_key=?", (key,)).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if row:
        _mem[key] = (row[0], row[1])
        return _mem[key]
    return None


def _write(key, url, text):
    now = time.time()
    if len(_mem) > 400:
        for k in list(_mem)[:150]:
            _mem.pop(k, None)
    _mem[key] = (now, text)
    if not _init():
        return
    try:
        conn = _connect()
        try:
            conn.execute("INSERT OR REPLACE INTO api_cache (cache_key, url, payload, created_at) VALUES (?,?,?,?)",
                         (key, url, text, now))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 429 cool-down (shared between worker processes through SQLite)
# ---------------------------------------------------------------------------

def _cooldown_seconds(resp):
    """How long to stay away after a 429, from Retry-After or Open-Meteo's own message."""
    try:
        ra = resp.headers.get("Retry-After")
        if ra and str(ra).strip().isdigit():
            return min(max(int(ra), 30), 24 * 3600)
    except Exception:
        pass
    try:
        reason = str(resp.json().get("reason", "")).lower()
    except Exception:
        reason = (resp.text or "")[:200].lower()
    now = datetime.now(timezone.utc)
    if "daily" in reason or "tomorrow" in reason:
        nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return int((nxt - now).total_seconds())
    if "hour" in reason:
        nxt = (now + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)
        return int((nxt - now).total_seconds())
    if "minut" in reason:
        return 75
    return DEFAULT_COOLDOWN


def _set_block(host, seconds, reason):
    until = time.time() + seconds
    _mem_block[host] = (until, reason)
    if not _init():
        return
    try:
        conn = _connect()
        try:
            conn.execute("INSERT OR REPLACE INTO api_block (host, until, reason) VALUES (?,?,?)", (host, until, reason))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _blocked(host):
    """-> (until, reason) while the host is on cool-down, else None."""
    now = time.time()
    item = _mem_block.get(host)
    if not item and _init():
        try:
            conn = _connect()
            try:
                row = conn.execute("SELECT until, reason FROM api_block WHERE host=?", (host,)).fetchone()
            finally:
                conn.close()
            if row:
                item = (row[0], row[1])
                _mem_block[host] = item
        except Exception:
            item = None
    if item and item[0] > now:
        return item
    return None


def _reason_of(resp):
    try:
        return str(resp.json().get("reason") or resp.text[:160])
    except Exception:
        return (resp.text or "")[:160]


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def cached_get(url, params=None, headers=None, timeout=20, tries=2, fresh_ttl=None, stale_ttl=None):
    """Drop-in replacement for the old om_get(): returns an object with .json() / .text / .status_code.

    Extra attributes on the result: .from_cache (bool) and .stale (True when an old copy was served because
    the API was rate-limited or failing). Raises RateLimitError (HTTP 429, nothing cached) or RuntimeError.
    """
    fresh_ttl = FRESH_TTL if fresh_ttl is None else fresh_ttl
    stale_ttl = STALE_TTL if stale_ttl is None else stale_ttl
    host = url.split("/")[2]
    key = make_key(url, params)
    now = time.time()

    row = _read(key)
    if row and now - row[0] < fresh_ttl:                       # 1. fresh copy: no network at all
        return CachedResponse(row[1], row[0], True, False)

    def stale_or(exc):
        if row and time.time() - row[0] < stale_ttl:           # 2. old copy beats an error page
            return CachedResponse(row[1], row[0], True, True)
        raise exc

    blocked = _blocked(host)                                   # 3. rate limited recently: do not call at all
    if blocked:
        mins = max(1, int((blocked[0] - now) / 60))
        return stale_or(RateLimitError("HTTP 429 from %s: %s (no new requests for ~%d min)" % (host, blocked[1], mins)))

    last = None
    for n in range(max(1, tries)):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            last = "%s while contacting %s" % (type(e).__name__, host)
        else:
            if r.status_code == 200:
                _write(key, url, r.text)
                return CachedResponse(r.text, time.time(), False, False)
            reason = _reason_of(r)
            if r.status_code == 429:                           # never retry a 429
                secs = _cooldown_seconds(r)
                _set_block(host, secs, reason)
                return stale_or(RateLimitError("HTTP 429 from %s: %s" % (host, reason)))
            last = "HTTP %s from %s: %s" % (r.status_code, host, reason)
            if r.status_code < 500:                            # 400/404...: our request is wrong, retrying is useless
                raise RuntimeError(last)
        if n < tries - 1:
            time.sleep(0.8 * (n + 1))
    return stale_or(RuntimeError(last or "request failed"))
