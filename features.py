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
    if code >= 95:
        return "storm"
    return "cloudy"


def fmt_hour(h):
    return "%02d:00" % (int(h) % 24)


def span(hours):
    """'17:00–20:00' for a list of hourly dicts."""
    if not hours:
        return ""
    step = 3
    return "%s–%s" % (fmt_hour(hours[0]["hour"]), fmt_hour(hours[-1]["hour"] + step))


# ---------------------------------------------------------------------------
# OpenWeather 5-day forecast bundle (standard /data/2.5/forecast API)
# ---------------------------------------------------------------------------

OW_FORECAST = "https://api.openweathermap.org/data/2.5/forecast"
OW_CURRENT = "https://api.openweathermap.org/data/2.5/weather"


def _ow_condition_code(item):
    """Map OpenWeather condition IDs to the WMO-like groups used by this app."""
    weather = (item.get("weather") or [{}])[0]
    oid = int(weather.get("id") or 800)
    if 200 <= oid < 300:
        return 95
    if 300 <= oid < 400:
        return 51
    if 500 <= oid < 600:
        return 65 if oid in (502, 503, 504, 522, 531) else 61
    if 600 <= oid < 700:
        return 71
    if 700 <= oid < 800:
        return 45
    if oid == 800:
        return 0
    if oid == 801:
        return 2
    if oid == 802:
        return 2
    return 3


def _request_openweather(url, params, timeout=15):
    response = requests.get(url, params=params, timeout=timeout)
    if response.status_code == 401:
        raise ValueError("OpenWeather rejected the API key. Check WEATHER_API_KEY in Render.")
    if response.status_code == 429:
        raise ValueError("OpenWeather rate limit reached. Please try again shortly.")
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and data.get("cod") not in (None, 200, "200"):
        raise ValueError(data.get("message", "OpenWeather returned an API error."))
    return data


def fetch_bundle(lat, lon):
    """Return forecast data normalized to WeatherGPT's internal schema.

    The standard OpenWeather forecast API returns 3-hour forecast steps for
    about five days. It does not supply UV index or evapotranspiration, so
    those fields use neutral/fallback values rather than invented readings.
    """
    key = ("ow_bundle", round(lat, 2), round(lon, 2))
    hit = cache_get(key, 600)
    if hit:
        return hit

    api_key = _ctx.get("weather_key") or os.getenv("WEATHER_API_KEY")
    if not api_key:
        raise ValueError("WEATHER_API_KEY is not configured.")

    params = {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"}
    data = _request_openweather(OW_FORECAST, params)
    entries = data.get("list") or []
    if not entries:
        raise ValueError("OpenWeather returned no forecast data.")

    city = data.get("city") or {}
    offset = int(city.get("timezone") or 0)
    now_local = datetime.now(timezone.utc) + timedelta(seconds=offset)
    hourly = []
    for entry in entries:
        dt_utc = datetime.fromtimestamp(int(entry.get("dt") or 0), timezone.utc)
        dt_local = dt_utc + timedelta(seconds=offset)
        main = entry.get("main") or {}
        wind = entry.get("wind") or {}
        rain_obj = entry.get("rain") or {}
        weather = (entry.get("weather") or [{}])[0]
        # OpenWeather's rain.3h is a total for the three-hour forecast period.
        hourly.append({
            "time": dt_local.strftime("%Y-%m-%dT%H:%M"),
            "date": dt_local.strftime("%Y-%m-%d"),
            "hour": dt_local.hour,
            "temp": float(main.get("temp") or 0),
            "feels": float(main.get("feels_like", main.get("temp", 0)) or 0),
            "hum": float(main.get("humidity") or 0),
            "pp": round(float(entry.get("pop") or 0) * 100),
            "mm": float(rain_obj.get("3h") or 0),
            "code": _ow_condition_code(entry),
            "vis": float(entry.get("visibility") if entry.get("visibility") is not None else 10000) / 1000.0,
            "wind": float(wind.get("speed") or 0) * 3.6,
            "gust": float(wind.get("gust", wind.get("speed", 0)) or 0) * 3.6,
            "wdir": float(wind.get("deg") or 0),
            "uv": 0.0,  # UV is not included in the standard 5-day forecast API.
            "cloud": float((entry.get("clouds") or {}).get("all") or 0),
            "day": int(6 <= dt_local.hour < 18),
        })

    grouped = {}
    for x in hourly:
        grouped.setdefault(x["date"], []).append(x)

    daily = []
    for date, samples in grouped.items():
        max_sample = max(samples, key=lambda x: x["temp"])
        min_sample = min(samples, key=lambda x: x["temp"])
        wind_max = max(x["wind"] for x in samples)
        gust_max = max(x["gust"] for x in samples)
        rain_sum = sum(x["mm"] for x in samples)
        severe = max(samples, key=lambda x: (
            x["code"] in (95, 96, 99),
            x["code"] in (61, 65, 71, 82),
            x["code"]
        ))
        daily.append({
            "date": date,
            "tmax": max_sample["temp"],
            "tmin": min_sample["temp"],
            "pp": max(x["pp"] for x in samples),
            "mm": rain_sum,
            "wind": wind_max,
            "gust": gust_max,
            "uv": 0.0,
            "et0": 4.0,  # fallback; not supplied by the standard forecast API
            "code": severe["code"],
            "sunrise": "",
            "sunset": "",
        })

    bundle = {
        "hourly": hourly,
        "daily": daily,
        "offset": offset,
        "today": now_local.strftime("%Y-%m-%d"),
        "interval_hours": 3,
        "source": "openweather",
    }
    return cache_set(key, bundle)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

LEVEL_RANK = {"extreme": 0, "warning": 1, "advisory": 2, "ok": 3}


def compute_alerts(b, lang):
    h24 = b["hourly"][:8]  # 8 three-hour steps ~= 24 hours
    if not h24:
        return []
    alerts = []

    def add(level, kind, hours, **kw):
        alerts.append({"id": kind, "level": level, "title": tr(lang, kind + "_t"),
                       "message": tr(lang, kind + "_m", when=span(hours) if hours else "", **kw)})

    storm = [x for x in h24 if x["code"] in (95, 96, 99)]
    if storm:
        add("extreme" if any(x["code"] == 99 for x in storm) else "warning", "th", storm)

    total = sum(x["mm"] for x in h24)
    intense = [x for x in h24 if x["mm"] >= 7.6]
    if total >= 115.6:
        add("extreme", "rain", [x for x in h24 if x["mm"] > 0], val=round(total))
    elif total >= 64.5 or intense:
        add("warning", "rain", intense or [x for x in h24 if x["mm"] > 0], val=round(total))
    elif total >= 15:
        add("advisory", "rain", [x for x in h24 if x["mm"] > 0.5], val=round(total))

    peak = max(x["temp"] for x in h24)
    hot = [x for x in h24 if x["temp"] >= min(peak, 37) - 0.01 and x["temp"] >= 37]
    if peak >= 45:
        add("extreme", "heat", hot, val=round(peak))
    elif peak >= 40:
        add("warning", "heat", hot, val=round(peak))
    elif peak >= 37 or max(x["feels"] for x in h24) >= 41:
        add("advisory", "heat", hot, val=round(peak))

    gust = max(x["gust"] for x in h24)
    windy = [x for x in h24 if x["gust"] >= 35]
    if gust >= 75:
        add("extreme", "wind", windy, val=round(gust))
    elif gust >= 50:
        add("warning", "wind", windy, val=round(gust))
    elif gust >= 35:
        add("advisory", "wind", windy, val=round(gust))

    low = min(x["temp"] for x in h24)
    if low <= 0:
        add("warning", "cold", [], val=round(low))
    elif low <= 4:
        add("advisory", "cold", [], val=round(low))

    foggy = [x for x in h24 if x["vis"] < 1.0]
    if foggy:
        add("advisory", "fog", foggy)

    uv = max(x["uv"] for x in h24)
    if uv >= 11:
        add("warning", "uv", [], val=round(uv))
    elif uv >= 8:
        add("advisory", "uv", [], val=round(uv))

    if not alerts:
        alerts.append({"id": "ok", "level": "ok", "title": tr(lang, "ok_t"), "message": tr(lang, "ok_m")})
    alerts.sort(key=lambda a: LEVEL_RANK[a["level"]])
    return alerts


# ---------------------------------------------------------------------------
# Travel intelligence
# ---------------------------------------------------------------------------

def hour_penalty(x):
    rain = min(35.0, x["pp"] * 0.2 + x["mm"] * 2.5)
    wind = min(25.0, max(0.0, x["gust"] - 25.0) * 0.6)
    f = x["feels"]
    temp = min(20.0, max(0.0, f - 35.0) * 3.0) + min(15.0, max(0.0, 5.0 - f) * 2.0)
    vis = min(20.0, max(0.0, 5.0 - x["vis"]) * 4.0)
    cond = 25.0 if x["code"] in (95, 96, 99) else (10.0 if x["code"] in (45, 48, 65, 67, 75, 82, 86) else 0.0)
    return {"rain": rain, "wind": wind, "temp": temp, "vis": vis, "cond": cond}


def score_of(x):
    return max(0.0, 100.0 - sum(hour_penalty(x).values()))


def status_of(pen):
    return "ok" if pen < 5 else ("warn" if pen < 15 else "bad")


def compute_travel(b, lang):
    hours = b["hourly"]
    if not hours:
        return {}
    nxt = hours[:1]  # first available 3-hour forecast step
    score = round(sum(score_of(x) for x in nxt) / len(nxt))
    verdict_key = "v_excellent" if score >= 80 else "v_good" if score >= 60 else "v_risky" if score >= 40 else "v_avoid"

    six = hours[:2]  # 6 hours represented by two 3-hour steps
    pen = hour_penalty({
        "pp": max(x["pp"] for x in six), "mm": sum(x["mm"] for x in six), "gust": max(x["gust"] for x in six),
        "feels": hours[0]["feels"], "vis": min(x["vis"] for x in six),
        "code": max((x["code"] for x in six), key=lambda c: (c in (95, 96, 99), c in (45, 48, 65, 67, 82), c)),
    })
    factors = [
        {"key": "rain", "status": status_of(pen["rain"]), "value": round(max(x["pp"] for x in six)), "extra": round(sum(x["mm"] for x in six), 1)},
        {"key": "wind", "status": status_of(pen["wind"]), "value": round(max(x["gust"] for x in six))},
        {"key": "temp", "status": status_of(pen["temp"]), "value": round(hours[0]["feels"])},
        {"key": "vis", "status": status_of(pen["vis"]), "value": round(min(x["vis"] for x in six), 1)},
        {"key": "cond", "status": status_of(pen["cond"]), "value": cond_group(max((x["code"] for x in six), key=lambda c: (c in (95, 96, 99), c)))},
    ]

    window_len = 3
    scored = []
    for i in range(0, max(0, min(8, len(hours)) - window_len + 1)):
        w = hours[i:i + window_len]
        avg = sum(score_of(x) for x in w) / window_len
        daytime = all(5 <= x["hour"] <= 21 for x in w)
        scored.append((avg, daytime, w))
    pool = [s for s in scored if s[1]] or scored
    best = max(pool, key=lambda s: (s[0], -hours.index(s[2][0]))) if pool else None
    worst = min(scored, key=lambda s: s[0]) if scored else None

    out = {"score": score, "verdict": tr(lang, verdict_key), "level": verdict_key[2:], "factors": factors}
    out["summary"] = tr(lang, "tr_sum", score=score, verdict=out["verdict"])
    if best:
        out["best"] = {"when": span(best[2]), "score": round(best[0]), "text": tr(lang, "tr_best", when=span(best[2]), score=round(best[0]))}
    if worst and worst[0] < 60:
        out["avoid"] = {"when": span(worst[2]), "score": round(worst[0]), "text": tr(lang, "tr_avoid", when=span(worst[2]))}
    return out


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def compute_recommendations(b, lang, travel):
    h = b["hourly"]
    now = h[0]
    h12 = h[:4]  # approximately next 12 hours
    daily0 = b["daily"][0] if b["daily"] else {"uv": now["uv"]}
    rain_p = max(x["pp"] for x in h12)
    rain_hours = [x for x in h12 if x["pp"] >= 50 or x["mm"] >= 0.5]
    uv = max(daily0.get("uv", 0), now["uv"])
    feels = now["feels"]

    # clothing
    if feels >= 35:
        c = ["c_hot"]
    elif feels >= 28:
        c = ["c_warm"]
    elif feels >= 20:
        c = ["c_mild"]
    elif feels >= 12:
        c = ["c_cool"]
    else:
        c = ["c_cold"]
    if rain_p >= 50:
        c.append("c_rain")
    clothing = [tr(lang, k) for k in c]

    # umbrella
    if rain_p >= 60:
        umb = [tr(lang, "u_yes", p=round(rain_p), when=span(rain_hours))]
    elif rain_p >= 30:
        umb = [tr(lang, "u_maybe", p=round(rain_p))]
    else:
        umb = [tr(lang, "u_no", p=round(rain_p))]
    if uv >= 6 and rain_p < 60:
        umb.append(tr(lang, "u_sun"))

    # outdoor
    ok_hours = [x for x in h[:8] if 6 <= x["hour"] <= 20 and x["pp"] < 30 and x["mm"] == 0 and x["feels"] <= 34 and x["gust"] < 35]
    score_now = score_of(now)
    if score_now >= 75 and now["feels"] <= 34:
        out = [tr(lang, "o_good")]
    elif score_now >= 50:
        out = [tr(lang, "o_ok")]
    else:
        out = [tr(lang, "o_poor")]
    if ok_hours:
        best = min(ok_hours, key=lambda x: x["feels"])
        i = h.index(best)
        run = [best]
        for x in h[i + 1:i + 3]:
            if x in ok_hours:
                run.append(x)
        out.append(tr(lang, "o_best", when=span(run)))

    # sun protection
    key = "s_low" if uv < 3 else "s_mod" if uv < 6 else "s_high" if uv < 8 else "s_vhigh" if uv < 11 else "s_ext"
    sun = [tr(lang, key, uv=round(uv, 1))]

    # health
    health = []
    if feels >= 35 or now["temp"] >= 35:
        health.append(tr(lang, "h_heat"))
    if now["hum"] >= 80:
        health.append(tr(lang, "h_humid"))
    if feels <= 12:
        health.append(tr(lang, "h_cold"))
    if rain_p >= 60:
        health.append(tr(lang, "h_rain"))
    if not health:
        health.append(tr(lang, "h_ok"))

    travel_tips = [travel.get("summary", "")]
    if travel.get("best"):
        travel_tips.append(travel["best"]["text"])

    return [
        {"id": "clothing", "icon": "👕", "tips": clothing},
        {"id": "umbrella", "icon": "☂️", "tips": umb},
        {"id": "outdoor", "icon": "🏃", "tips": out},
        {"id": "sun", "icon": "🧴", "tips": sun, "uv": round(uv, 1)},
        {"id": "health", "icon": "❤️", "tips": health},
        {"id": "travel", "icon": "🚗", "tips": [t for t in travel_tips if t]},
    ]


# ---------------------------------------------------------------------------
# Farmer advisory
# ---------------------------------------------------------------------------

CROPS = {"rice": 1.2, "cotton": 1.0, "chilli": 0.9, "maize": 1.0, "groundnut": 0.9,
         "tobacco": 0.9, "banana": 1.1, "sugarcane": 1.2, "tomato": 1.0, "wheat": 1.0}


def day_label(b, date, lang):
    today = b["today"]
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    if date == today:
        return tr(lang, "day_today")
    if date == tomorrow:
        return tr(lang, "day_tomorrow")
    return date[5:]


def compute_farm(b, lang, crop):
    kc = CROPS.get(crop, 1.0)
    h, d = b["hourly"], b["daily"]
    h48, h24 = h[:16], h[:8]  # 48h and 24h using 3-hour forecast steps
    cards = []

    # irrigation
    rain48 = sum(x["mm"] for x in h48)
    rain72 = sum(x["mm"] for x in d[:3])
    et3 = sum(x["et0"] for x in d[:3]) * kc
    balance = rain72 - et3
    if rain48 >= 10:
        irr = ("good", tr(lang, "i_skip", mm=round(rain48)))
    elif balance <= -8:
        irr = ("caution", tr(lang, "i_now", mm=round(-balance)))
    else:
        irr = ("good", tr(lang, "i_light"))
    cards.append({"id": "irrigation", "icon": "💧", "status": irr[0], "text": irr[1]})

    # spraying windows
    ok = []
    for i, x in enumerate(h48):
        nxt = h48[i + 1:i + 4]
        good = (x["wind"] <= 15 and x["gust"] <= 28 and x["pp"] <= 25 and x["mm"] == 0 and x["temp"] <= 33
                and 5 <= x["hour"] <= 19 and all(y["mm"] == 0 and y["pp"] <= 40 for y in nxt))
        ok.append(good)
    runs, cur = [], []
    for i, g in enumerate(ok):
        if g:
            cur.append(h48[i])
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    windows = []
    top = sorted(runs, key=lambda r: (-len(r), r[0]["time"]))[:2]
    for r in sorted(top, key=lambda r: r[0]["time"]):
        windows.append("%s %s" % (day_label(b, r[0]["date"], lang), span(r)))
    if windows:
        spray = ("good", tr(lang, "sp_window", when=" · ".join(windows)) + " " + tr(lang, "sp_tip"))
    else:
        spray = ("alert", tr(lang, "sp_none"))
    cards.append({"id": "spraying", "icon": "🧪", "status": spray[0], "text": spray[1], "windows": windows})

    # pest & disease
    avg_h = sum(x["hum"] for x in h24) / len(h24)
    avg_t = sum(x["temp"] for x in h24) / len(h24)
    wet = max(x["pp"] for x in h24) >= 50 or sum(x["mm"] for x in h24) > 2
    if avg_h >= 85 and 20 <= avg_t <= 32 and wet:
        pest = ("alert", tr(lang, "p_high", h=round(avg_h)))
    elif avg_h >= 75 and 18 <= avg_t <= 34:
        pest = ("caution", tr(lang, "p_med"))
    elif avg_t >= 32 and avg_h <= 55:
        pest = ("caution", tr(lang, "p_suck"))
    else:
        pest = ("good", tr(lang, "p_low"))
    cards.append({"id": "pest", "icon": "🐛", "status": pest[0], "text": pest[1]})

    # harvest
    run = 0
    for x in d[:5]:
        if x["mm"] < 2 and x["pp"] < 40:
            run += 1
        else:
            break
    rain_soon = next((x for x in h24 if x["pp"] >= 60 or x["mm"] >= 1), None)
    if run >= 3:
        hv = ("good", tr(lang, "hv_good", days=run))
    elif rain_soon:
        hv = ("alert", tr(lang, "hv_rain", when="%s %s" % (day_label(b, rain_soon["date"], lang), fmt_hour(rain_soon["hour"]))))
    else:
        hv = ("caution", tr(lang, "hv_wait"))
    cards.append({"id": "harvest", "icon": "🌾", "status": hv[0], "text": hv[1]})

    # protection
    msgs, status = [], "good"
    gust = max(x["gust"] for x in h24)
    rain24 = sum(x["mm"] for x in h24)
    tmax = max(x["temp"] for x in h24)
    tmin = min(x["temp"] for x in h24)
    if any(x["code"] in (95, 96, 99) for x in h24):
        msgs.append(tr(lang, "pr_storm")); status = "alert"
    if gust >= 45:
        msgs.append(tr(lang, "pr_wind", g=round(gust))); status = "alert" if gust >= 60 else max(status, "caution", key=["good", "caution", "alert"].index)
    if rain24 >= 50:
        msgs.append(tr(lang, "pr_rain")); status = "alert"
    if tmax >= 40:
        msgs.append(tr(lang, "pr_heat", t=round(tmax))); status = "alert" if tmax >= 43 else max(status, "caution", key=["good", "caution", "alert"].index)
    if tmin <= 5:
        msgs.append(tr(lang, "pr_cold", t=round(tmin))); status = max(status, "caution", key=["good", "caution", "alert"].index)
    if not msgs:
        msgs.append(tr(lang, "pr_ok"))
    cards.append({"id": "protection", "icon": "🛡️", "status": status, "text": " ".join(msgs)})

    return {"crop": crop, "cards": cards, "balance": round(balance, 1), "rain48": round(rain48, 1)}


# ---------------------------------------------------------------------------
# Overview payload
# ---------------------------------------------------------------------------

def build_overview(lat, lon, lang, crop):
    b = fetch_bundle(lat, lon)
    if not b["hourly"]:
        raise ValueError("No forecast data available for this location.")
    now = b["hourly"][0]
    travel = compute_travel(b, lang)
    return {
        "lat": lat, "lon": lon, "language": lang, "offset": b["offset"],
        "now": {"temp": now["temp"], "feels": now["feels"], "hum": now["hum"], "wind": now["wind"], "gust": now["gust"],
                "wdir": now["wdir"], "uv": max(now["uv"], 0), "uv_max": b["daily"][0]["uv"] if b["daily"] else now["uv"],
                "pp": now["pp"], "vis": now["vis"], "cloud": now["cloud"], "group": cond_group(now["code"]), "day": now["day"]},
        "hourly": [dict(x, group=cond_group(x["code"])) for x in b["hourly"][:48]],
        "daily": [dict(x, group=cond_group(x["code"])) for x in b["daily"]],
        "alerts": compute_alerts(b, lang),
        "recommendations": compute_recommendations(b, lang, travel),
        "travel": travel,
        "farm": compute_farm(b, lang, crop),
        "summary": fallback_summary(b, lang),
    }


def fallback_summary(b, lang):
    d = b["daily"]
    if not d:
        return ""
    t0 = d[0]
    later = d[1:4]
    trend = "trend_flat"
    if later:
        avg = sum(x["tmax"] for x in later) / len(later)
        trend = "trend_up" if avg - t0["tmax"] >= 2 else "trend_down" if t0["tmax"] - avg >= 2 else "trend_flat"
    return tr(lang, "f_sum", tmin=round(t0["tmin"]), tmax=round(t0["tmax"]), p=round(t0["pp"]), trend=tr(lang, trend))


@bp.route("/api/overview")
def api_overview():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    lang = norm_lang(request.args.get("language"))
    crop = request.args.get("crop", "rice").lower()
    crop = crop if crop in CROPS else "rice"
    try:
        return jsonify(build_overview(lat, lon, lang, crop))
    except Exception as e:  # network / parsing
        return jsonify({"error": "Unable to load forecast intelligence: %s" % e}), 502


# ---------------------------------------------------------------------------
# AI helpers (forecast explanation + crop advice) and chat context
# ---------------------------------------------------------------------------

def facts_text(b, place):
    d = b["daily"]
    h = b["hourly"]
    lines = ["Location: %s" % place]
    if h:
        n = h[0]
        lines.append("Now: %.0f°C (feels %.0f°C), humidity %.0f%%, wind %.0f km/h gusts %.0f km/h, UV %.1f, rain chance %.0f%%." %
                     (n["temp"], n["feels"], n["hum"], n["wind"], n["gust"], n["uv"], n["pp"]))
        nxt = []
        for x in h[:24:3]:
            nxt.append("%s %s %.0f°C rain %.0f%% (%.1f mm)" % (x["date"][5:], fmt_hour(x["hour"]), x["temp"], x["pp"], x["mm"]))
        lines.append("Next 24h (every 3h): " + "; ".join(nxt))
    for i, x in enumerate(d[:7]):
        lines.append("Day %d (%s): %.0f–%.0f°C, rain chance %.0f%%, %.1f mm, max wind %.0f km/h, %s." %
                     (i, x["date"], x["tmin"], x["tmax"], x["pp"], x["mm"], x["wind"], cond_group(x["code"])))
    return "\n".join(lines)


def forecast_context(lat, lon, place=""):
    """Compact forecast text injected into the chat prompt so the AI can answer
    'will it rain today?' and 'what about tomorrow?'."""
    try:
        text = facts_text(fetch_bundle(float(lat), float(lon)), place or "selected location")
        try:
            from reliability import reliability_facts
            text += "\n" + reliability_facts(lat, lon)
        except Exception:
            pass
        return text
    except Exception:
        return ""


@bp.route("/api/forecast-explain", methods=["POST"])
def api_forecast_explain():
    data = request.get_json(silent=True) or {}
    lat, lon = get_coords(data)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    lang = norm_lang(data.get("language"))
    place = str(data.get("location", "this location"))[:120]
    try:
        b = fetch_bundle(lat, lon)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    fallback = fallback_summary(b, lang)
    groq = _ctx["groq"]
    if not groq:
        return jsonify({"explanation": fallback, "source": "rules"})
    try:
        from reliability import reliability_facts
        conf = reliability_facts(lat, lon)
    except Exception:
        conf = ""
    prompt = ("You are WeatherGPT. %s\nExplain this forecast to an ordinary person in 4 short sentences: "
              "what the next 24 hours look like (including rain timing), the temperature trend over the week, "
              "and one practical tip. If the confidence data below shows low-confidence days, mention in one clause how far "
              "the forecast can be trusted. No markdown, no bullet points.\n\n%s\n%s") % (LANG_INSTRUCTION[lang], facts_text(b, place), conf)
    text, err = groq(prompt)
    if err or not text:
        return jsonify({"explanation": fallback, "source": "rules"})
    return jsonify({"explanation": text, "source": "ai"})


@bp.route("/api/farmer-ai", methods=["POST"])
def api_farmer_ai():
    data = request.get_json(silent=True) or {}
    lat, lon = get_coords(data)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    lang = norm_lang(data.get("language"))
    crop = str(data.get("crop", "rice")).lower()
    crop = crop if crop in CROPS else "rice"
    place = str(data.get("location", "this location"))[:120]
    stage = str(data.get("stage", "")).strip()[:40]
    try:
        b = fetch_bundle(lat, lon)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    farm = compute_farm(b, "en", crop)
    rules = "\n".join("- %s: %s" % (c["id"], c["text"]) for c in farm["cards"])
    groq = _ctx["groq"]
    if not groq:
        return jsonify({"error": "AI service unavailable."}), 503
    prompt = ("You are WeatherGPT's agriculture advisor for Indian farmers. %s\n"
              "Crop: %s%s. Give 5 short, practical bullet points (start each with '-') covering irrigation, "
              "spraying, pest/disease, harvest and crop protection, specific to this crop and the weather below. "
              "No markdown headings.\n\nWeather facts:\n%s\n\nRule-based checks:\n%s") % (
        LANG_INSTRUCTION[lang], crop, (" (growth stage: %s)" % stage) if stage else "", facts_text(b, place), rules)
    text, err = groq(prompt)
    if err or not text:
        return jsonify({"error": "AI service unavailable."}), 502
    return jsonify({"advice": text})


# ---------------------------------------------------------------------------
# Climate history is not available from OpenWeather's standard forecast API.
# ---------------------------------------------------------------------------

@bp.route("/api/climate")
def api_climate():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    return jsonify({
        "error": (
            "Long-term climate history is not provided by the standard OpenWeather "
            "forecast API. This feature is disabled rather than returning fabricated data."
        ),
        "source": "openweather",
        "available": False,
    }), 503


# ---------------------------------------------------------------------------
# Map tiles (proxy keeps the OpenWeather key on the server) + reverse geocode
# ---------------------------------------------------------------------------

TILE_LAYERS = {"precipitation_new", "wind_new", "temp_new", "clouds_new", "pressure_new"}
_BLANK_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@bp.route("/map-tile/<layer>/<int:z>/<int:x>/<int:y>.png")
def map_tile(layer, z, x, y):
    key = _ctx["weather_key"]
    headers = {"Cache-Control": "public, max-age=600"}
    if layer not in TILE_LAYERS or not key or not (0 <= z <= 12):
        return Response(_BLANK_PNG, mimetype="image/png", headers=headers)
    try:
        r = requests.get("https://tile.openweathermap.org/map/%s/%d/%d/%d.png" % (layer, z, x, y),
                         params={"appid": key}, timeout=8)
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image"):
            return Response(r.content, mimetype="image/png", headers=headers)
    except requests.RequestException:
        pass
    return Response(_BLANK_PNG, mimetype="image/png", headers={"Cache-Control": "no-store"})


@bp.route("/reverse")
def reverse_geocode():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    try:
        r = requests.get("https://nominatim.openstreetmap.org/reverse",
                         params={"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 12, "addressdetails": 1},
                         headers={"User-Agent": "WeatherGPT/1.0 (reverse)", "Accept-Language": "en"}, timeout=8)
        a = (r.json() or {}).get("address", {}) or {}
        name = next((a[k] for k in ("village", "hamlet", "town", "suburb", "city_district", "city") if a.get(k)), "")
        parts = [name, a.get("county") or a.get("state_district") or "", a.get("state", ""), a.get("country", "")]
        label = ", ".join(p for p in parts if p) or "Selected location"
        return jsonify({"name": name or "Selected location", "label": label})
    except Exception:
        return jsonify({"name": "Selected location", "label": "Selected location"})