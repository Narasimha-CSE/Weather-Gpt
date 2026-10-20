# -*- coding: utf-8 -*-
"""WeatherGPT feature APIs using OpenWeather forecasts, plus map tiles and geocoding.
Long-term climate history requires a separate historical-data provider.
"""

import base64
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, Response, jsonify, request

from i18n_data import LANG_INSTRUCTION, tr

bp = Blueprint("features", __name__)

_ctx = {"groq": None, "weather_key": None}


def init_features(app, groq_fn, weather_key):
    """Register blueprint. groq_fn(prompt) -> (text, error)."""
    _ctx["groq"] = groq_fn
    _ctx["weather_key"] = weather_key
    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_cache = {}


def cache_get(key, ttl):
    item = _cache.get(key)
    if item and time.time() - item[0] < ttl:
        return item[1]
    return None


def cache_set(key, value):
    if len(_cache) > 300:
        for k in list(_cache)[:100]:
            _cache.pop(k, None)
    _cache[key] = (time.time(), value)
    return value


def norm_lang(value):
    v = str(value or "en").strip().lower()
    if v.startswith("te"):
        return "te"
    if v.startswith("hi"):
        return "hi"
    return "en"


def num(arr, i, default=0.0):
    try:
        v = arr[i]
        return default if v is None else float(v)
    except (IndexError, TypeError, ValueError):
        return default


def get_coords(src):
    try:
        lat = float(src.get("lat"))
        lon = float(src.get("lon"))
    except (TypeError, ValueError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def cond_group(code):
    code = int(code or 0)
    if code in (0, 1):
        return "clear"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if 80 <= code <= 82:
        return "showers"
