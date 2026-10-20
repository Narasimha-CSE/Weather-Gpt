# -*- coding: utf-8 -*-
"""WeatherGPT forecast-reliability module.

Answers one question: "How much should I trust this forecast, day by day, for the next 10 days?"

How it works
------------
1. Multi-model spread   - the same location is forecast by several independent global models
                          (ECMWF, GFS, ICON, GEM through Open-Meteo). When they disagree, the forecast is fragile.
2. Bust-risk model      - a small logistic-regression model turns the spread (+ lead time) into the probability
                          that the forecast will be a "forecast bust". Weights come from
                          data/reliability_model.json (written by train_reliability.py) or, if that file does not
                          exist yet, from the built-in PRIOR weights (heuristic, NOT trained).
3. Verification         - the track-record endpoint compares what the model said 1/3/5/7 days ago with what actually
                          happened (ERA5 reanalysis) at the selected location.

Definition of a "forecast bust" (used by training, verification and the UI)
---------------------------------------------------------------------------
A day is a bust when the consensus (mean of models) forecast is wrong versus the observed/reanalysis value by

    |max temperature error|  >= 4 C      OR
    |daily rain error|       >= 10 mm    OR
    |max wind gust error|    >= 25 km/h
"""

import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, jsonify, request

bp = Blueprint("reliability", __name__)
_ctx = {"groq": None}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_FILE = os.path.join(BASE_DIR, "data", "reliability_model.json")

_UA = {"User-Agent": "WeatherGPT/1.0 (weather app; open-meteo client)"}


def om_get(url, params, timeout=20, tries=3):
    """GET with a User-Agent, retries on 429/5xx/timeouts, and a readable error message."""
    last = None
    host = url.split("/")[2]
    for n in range(tries):
        try:
            r = requests.get(url, params=params, headers=_UA, timeout=timeout)
            if r.status_code == 200:
                return r
            try:
                reason = r.json().get("reason") or r.text[:160]
            except Exception:
                reason = r.text[:160]
            last = "HTTP %s from %s: %s" % (r.status_code, host, reason)
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            last = "%s while contacting %s" % (type(e).__name__, host)
        time.sleep(0.8 * (n + 1))
    raise RuntimeError(last or "request failed")


OM_FORECAST = "https://api.open-meteo.com/v1/forecast"
OM_PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
OM_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

MODELS = [
    ("ecmwf_ifs025", "ECMWF"),
    ("gfs_seamless", "GFS"),
    ("icon_seamless", "ICON"),
    ("gem_seamless", "GEM"),
]
MODEL_LABEL = dict(MODELS)
MODEL_LABEL["best_match"] = "Open-Meteo"

BUST = {"tmax": 4.0, "rain": 10.0, "gust": 25.0}      # thresholds that define a forecast bust
WET_MM = 1.0                                           # a day counts as "wet" from 1 mm
FEATURES = ["lead", "sT", "lsP", "sG", "wetdis", "lmeanP"]

# Heuristic prior used until train_reliability.py has produced real weights.
PRIOR = {
    "source": "prior",
    "bias": -3.3,
    "weights": {"lead": 0.15, "sT": 0.40, "lsP": 0.75, "sG": 0.03, "wetdis": 0.90, "lmeanP": 0.25},
    "means": {k: 0.0 for k in FEATURES},
    "scales": {k: 1.0 for k in FEATURES},
    "meta": {},
}


def init_reliability(app, groq_fn):
    _ctx["groq"] = groq_fn
    app.register_blueprint(bp)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_cache = {}


def cache_get(key, ttl):
    item = _cache.get(key)
    if item and time.time() - item[0] < ttl:
        return item[1]
    return None


def cache_set(key, value):
    if len(_cache) > 120:
        for k in list(_cache)[:40]:
            _cache.pop(k, None)
    _cache[key] = (time.time(), value)
    return value


def norm_lang(value):
    v = str(value or "en").strip().lower()
    return "te" if v.startswith("te") else "hi" if v.startswith("hi") else "en"


def get_coords(src):
    try:
        lat, lon = float(src.get("lat")), float(src.get("lon"))
    except (TypeError, ValueError):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def fnum(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def mean(v):
    return sum(v) / len(v) if v else 0.0


def std(v):
    if len(v) < 2:
        return 0.0
    m = mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# ---------------------------------------------------------------------------
# bust-risk model (shared by the live endpoint and train_reliability.py)
# ---------------------------------------------------------------------------

def build_features(lead, tmax, rain, gust):
    """tmax / rain / gust: lists of the individual model values for ONE day (None already removed).
    Returns a feature dict, or None when fewer than 2 models are available."""
    n = min(len(tmax), len(rain), len(gust))
    if n < 2:
        return None
    wet = sum(1 for r in rain if r >= WET_MM) / float(len(rain))
    return {
        "lead": float(lead),
        "sT": std(tmax),
        "lsP": math.log1p(std(rain)),
        "sG": std(gust),
        "wetdis": 4.0 * wet * (1.0 - wet),
        "lmeanP": math.log1p(mean(rain)),
    }


def estimated_features(lead):
    """Typical spread growth with lead time - used when a day is beyond the range of all but one model."""
    return {"lead": float(lead), "sT": 0.5 + 0.35 * lead, "lsP": math.log1p(0.5 + 0.6 * lead),
            "sG": 3.0 + 1.6 * lead, "wetdis": 0.35, "lmeanP": math.log1p(2.0)}


def load_model():
    try:
        mtime = os.path.getmtime(MODEL_FILE)
    except OSError:
        return PRIOR
    hit = cache_get(("model", mtime), 3600 * 24)
    if hit:
        return hit
    try:
        with open(MODEL_FILE, "r", encoding="utf-8") as fh:
            m = json.load(fh)
        if all(k in m.get("weights", {}) for k in FEATURES):
            m["source"] = "trained"
            return cache_set(("model", mtime), m)
    except Exception:
        pass
    return PRIOR


def bust_probability(feat, model=None):
    model = model or load_model()
    z = model["bias"]
    for k in FEATURES:
        sc = model["scales"].get(k) or 1.0
        z += model["weights"][k] * ((feat[k] - model["means"].get(k, 0.0)) / sc)
    return sigmoid(z)


def contributions(feat, model=None):
    """Signed contribution of each feature to the risk logit (used for the 'why' explanation)."""
    model = model or load_model()
    out = {}
    for k in FEATURES:
        sc = model["scales"].get(k) or 1.0
        out[k] = model["weights"][k] * ((feat[k] - model["means"].get(k, 0.0)) / sc)
    return out


def label_for(conf):
    return "high" if conf >= 70 else "medium" if conf >= 45 else "low"


def is_bust(fc_t, fc_r, fc_g, ob_t, ob_r, ob_g):
    return (abs(fc_t - ob_t) >= BUST["tmax"]) or (abs(fc_r - ob_r) >= BUST["rain"]) or (abs(fc_g - ob_g) >= BUST["gust"])


# ---------------------------------------------------------------------------
# Open-Meteo multi-model fetch
# ---------------------------------------------------------------------------

DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max"


def _model_series(daily, var, model, multi):
    keys = [var + "_" + model, var] if multi else [var, var + "_" + model]
    for k in keys:
        if k in daily:
            return daily[k]
    return None


def _parse_daily(daily, models):
    """-> {model: {"tmax":[...], "tmin":[...], "rain":[...], "gust":[...]}} plus the date list."""
    multi = len(models) > 1
    out = {}
    for m in models:
        ser = {
            "tmax": _model_series(daily, "temperature_2m_max", m, multi),
            "tmin": _model_series(daily, "temperature_2m_min", m, multi),
            "rain": _model_series(daily, "precipitation_sum", m, multi),
            "gust": _model_series(daily, "wind_gusts_10m_max", m, multi),
        }
        if all(v is not None for v in ser.values()):
            out[m] = {k: [fnum(x) for x in v] for k, v in ser.items()}
    return out


def fetch_models(lat, lon, days=10):
    """Returns (dates, {model: series}) using the models that answered."""
    key = ("multi", round(lat, 2), round(lon, 2), days)
    hit = cache_get(key, 1800)
    if hit:
        return hit
    ids = [m for m, _ in MODELS]
    base = {"latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "auto",
            "forecast_days": days, "wind_speed_unit": "kmh"}
    dates, series, err = [], {}, None
    try:
        r = om_get(OM_FORECAST, dict(base, models=",".join(ids)), timeout=20)
        j = r.json()
        dates = j.get("daily", {}).get("time", [])
        series = _parse_daily(j.get("daily", {}), ids)
    except Exception as e:
        series, err = {}, e
    if len(series) < 2:                    # combined call failed: ask the models one by one
        series = {}
        for m in ids:
            try:
                j = om_get(OM_FORECAST, dict(base, models=m), timeout=15, tries=2).json()
                parsed = _parse_daily(j.get("daily", {}), [m])
                if parsed:
                    series.update(parsed)
                    dates = dates or j.get("daily", {}).get("time", [])
            except Exception as e:
                err = e
                continue
    if not series:                         # last resort: Open-Meteo's own blended forecast (one model)
        try:
            j = om_get(OM_FORECAST, base, timeout=15, tries=2).json()
            series = _parse_daily(j.get("daily", {}), ["best_match"])
            dates = j.get("daily", {}).get("time", [])
        except Exception as e:
            err = e
    if not series:
        raise RuntimeError("No forecast model answered (%s)." % (err or "empty response"))
    return cache_set(key, (dates, series))


def day_values(series, i):
    """Per-model values for day i with None removed and per-variable alignment."""
    t, tn, r, g, names = [], [], [], [], []
    for m, s in series.items():
        try:
            vt, vtn, vr, vg = s["tmax"][i], s["tmin"][i], s["rain"][i], s["gust"][i]
        except IndexError:
            continue
        if None in (vt, vtn, vr, vg):
            continue
        t.append(vt); tn.append(vtn); r.append(vr); g.append(vg); names.append(m)
    return names, t, tn, r, g


# ---------------------------------------------------------------------------
# Text in three languages
# ---------------------------------------------------------------------------

TXT = {
    "en": {
        "lvl_high": "High", "lvl_medium": "Medium", "lvl_low": "Low",
        "d_temp": "Models disagree on max temperature: {lo:.0f}–{hi:.0f} °C ({a} says {amax:.0f}, {b} says {bmin:.0f}).",
        "d_rain": "Models disagree on rain: {a} expects {amax:.0f} mm while {b} expects {bmin:.0f} mm.",
        "d_wet": "Some models give rain, others stay dry – the wet/dry call is uncertain.",
        "d_wind": "Wind gust forecasts range from {lo:.0f} to {hi:.0f} km/h between models.",
        "d_lead": "It is {n} days ahead – forecast skill naturally falls with lead time.",
        "d_few": "Only one model reaches this far, so the confidence is an estimate from lead time alone.",
        "d_good": "All models agree closely on temperature, rain and wind – this forecast is solid.",
        "a_title": "Low forecast confidence – {day}",
        "a_title_hz": "Possible {hazard} but models disagree – {day}",
        "a_msg": "Bust risk {p}%. {why} Check again closer to the day before making firm plans.",
        "hz_rain": "heavy rain", "hz_wind": "strong winds", "hz_heat": "extreme heat",
        "sum_all": "Next 10 days: average confidence {avg}%. Most reliable: {best}. Least reliable: {worst}.",
        "ai_prompt": "Explain in 3 short sentences, in plain words, why the forecast for {day} at {place} is {lvl} confidence "
                     "and what a person should do about it. No markdown.",
    },
    "te": {
        "lvl_high": "అధికం", "lvl_medium": "మధ్యస్థం", "lvl_low": "తక్కువ",
        "d_temp": "గరిష్ట ఉష్ణోగ్రతపై మోడళ్ల మధ్య భేదం ఉంది: {lo:.0f}–{hi:.0f} °C ({a}: {amax:.0f}, {b}: {bmin:.0f}).",
        "d_rain": "వర్షంపై మోడళ్ల మధ్య భేదం: {a} ప్రకారం {amax:.0f} మి.మీ, {b} ప్రకారం {bmin:.0f} మి.మీ.",
        "d_wet": "కొన్ని మోడళ్లు వర్షం చూపిస్తున్నాయి, మరికొన్ని పొడి వాతావరణం – వర్షం వస్తుందా లేదా అనేది అనిశ్చితం.",
        "d_wind": "గాలి ఝంఝా అంచనాలు మోడళ్ల మధ్య {lo:.0f} నుంచి {hi:.0f} కి.మీ/గం వరకు ఉన్నాయి.",
        "d_lead": "ఇది {n} రోజుల ముందు అంచనా – రోజులు పెరిగే కొద్దీ కచ్చితత్వం తగ్గుతుంది.",
        "d_few": "ఇంత దూరం ఒకే మోడల్ చూపిస్తోంది, కాబట్టి నమ్మకం రోజుల ఆధారంగా అంచనా మాత్రమే.",
        "d_good": "ఉష్ణోగ్రత, వర్షం, గాలిపై అన్ని మోడళ్లు ఏకీభవిస్తున్నాయి – ఈ అంచనా నమ్మదగినది.",
        "a_title": "అంచనాపై తక్కువ నమ్మకం – {day}",
        "a_title_hz": "{hazard} అవకాశం, కానీ మోడళ్లు ఏకీభవించలేదు – {day}",
        "a_msg": "అంచనా తప్పే ప్రమాదం {p}%. {why} ఖచ్చితమైన ప్రణాళికలు వేసే ముందు ఆ రోజు దగ్గరపడ్డాక మళ్లీ చూడండి.",
        "hz_rain": "భారీ వర్షం", "hz_wind": "బలమైన గాలులు", "hz_heat": "తీవ్రమైన వేడి",
        "sum_all": "తదుపరి 10 రోజులు: సగటు నమ్మకం {avg}%. అత్యంత నమ్మదగిన రోజు: {best}. తక్కువ నమ్మదగినది: {worst}.",
        "ai_prompt": "{place}లో {day} నాటి అంచనా {lvl} నమ్మకంతో ఎందుకు ఉందో, ప్రజలు ఏం చేయాలో 3 చిన్న వాక్యాల్లో సరళ తెలుగులో చెప్పండి. మార్క్‌డౌన్ వద్దు.",
    },
    "hi": {
        "lvl_high": "उच्च", "lvl_medium": "मध्यम", "lvl_low": "कम",
        "d_temp": "अधिकतम तापमान पर मॉडलों में मतभेद है: {lo:.0f}–{hi:.0f} °C ({a}: {amax:.0f}, {b}: {bmin:.0f}).",
        "d_rain": "बारिश पर मॉडलों में मतभेद: {a} के अनुसार {amax:.0f} मिमी, {b} के अनुसार {bmin:.0f} मिमी.",
        "d_wet": "कुछ मॉडल बारिश दिखाते हैं, कुछ सूखा मौसम – बारिश होगी या नहीं, यह अनिश्चित है.",
        "d_wind": "हवा के झोंकों का अनुमान मॉडलों के बीच {lo:.0f} से {hi:.0f} किमी/घं तक है.",
        "d_lead": "यह {n} दिन आगे का पूर्वानुमान है – दिन बढ़ने पर सटीकता घटती है.",
        "d_few": "इतनी दूर तक सिर्फ एक मॉडल देखता है, इसलिए भरोसा केवल दिनों के आधार पर अनुमानित है.",
        "d_good": "तापमान, बारिश और हवा पर सभी मॉडल सहमत हैं – यह पूर्वानुमान भरोसेमंद है.",
        "a_title": "पूर्वानुमान पर कम भरोसा – {day}",
        "a_title_hz": "{hazard} की संभावना, पर मॉडल असहमत – {day}",
        "a_msg": "पूर्वानुमान गलत होने का जोखिम {p}%. {why} पक्की योजना बनाने से पहले उस दिन के करीब फिर जाँचें.",
        "hz_rain": "भारी बारिश", "hz_wind": "तेज हवाएँ", "hz_heat": "अत्यधिक गर्मी",
        "sum_all": "अगले 10 दिन: औसत भरोसा {avg}%. सबसे भरोसेमंद: {best}. सबसे कम भरोसेमंद: {worst}.",
        "ai_prompt": "{place} में {day} का पूर्वानुमान {lvl} भरोसे का क्यों है और व्यक्ति को क्या करना चाहिए, यह 3 छोटे वाक्यों में सरल हिंदी में बताइए. मार्कडाउन नहीं.",
    },
}

LANG_INSTR = {
    "en": "Answer completely in fluent English.",
    "te": "Answer completely in pure Telugu script (తెలుగు). Do not use English words.",
    "hi": "Answer completely in pure Hindi using Devanagari script (हिन्दी). Do not use English words.",
}


def T(lang, key, **kw):
    text = TXT.get(lang, TXT["en"]).get(key) or TXT["en"].get(key, key)
    try:
        return text.format(**kw)
    except Exception:
        return text


def day_name(date_str, lang):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    days = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "te": ["సోమ", "మంగళ", "బుధ", "గురు", "శుక్ర", "శని", "ఆది"],
            "hi": ["सोम", "मंगल", "बुध", "गुरु", "शुक्र", "शनि", "रवि"]}[lang]
    return "%s %d/%d" % (days[d.weekday()], d.day, d.month)


def drivers_for(i, names, t, r, g, feat, contrib, lang):
    """Plain-language reasons, strongest first. Returns list of {kind, text}."""
    out = []
    lab = [MODEL_LABEL.get(n, n) for n in names]
    if feat is None:
        out.append({"kind": "few", "w": 99, "text": T(lang, "d_few")})
    else:
        if feat["sT"] >= 1.5 and t:
            a, b = t.index(max(t)), t.index(min(t))
            out.append({"kind": "temp", "w": contrib["sT"], "text": T(lang, "d_temp", lo=min(t), hi=max(t), a=lab[a], amax=t[a], b=lab[b], bmin=t[b])})
        if r and (max(r) - min(r)) >= 4:
            a, b = r.index(max(r)), r.index(min(r))
            out.append({"kind": "rain", "w": contrib["lsP"], "text": T(lang, "d_rain", a=lab[a], amax=r[a], b=lab[b], bmin=r[b])})
        if feat["wetdis"] >= 0.7:
            out.append({"kind": "wet", "w": contrib["wetdis"], "text": T(lang, "d_wet")})
        if feat["sG"] >= 8 and g:
            out.append({"kind": "wind", "w": contrib["sG"], "text": T(lang, "d_wind", lo=min(g), hi=max(g))})
    if i >= 4:
        out.append({"kind": "lead", "w": contrib["lead"] if contrib else 0.1, "text": T(lang, "d_lead", n=i)})
    out.sort(key=lambda x: -x["w"])
    if not out or (len(out) == 1 and out[0]["kind"] == "lead" and feat and feat["sT"] < 1.5):
        out.insert(0, {"kind": "good", "w": 0, "text": T(lang, "d_good")})
    return [{"kind": o["kind"], "text": o["text"]} for o in out[:4]]


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def sub_scores(feat):
    """Separate 0-100 confidence for temperature, rain and wind."""
    temp = 100.0 * math.exp(-feat["sT"] / 3.5)
    rain = 100.0 * math.exp(-(0.9 * feat["wetdis"] + math.expm1(feat["lsP"]) / (2.0 + math.expm1(feat["lmeanP"]))) / 1.3)
    wind = 100.0 * math.exp(-feat["sG"] / 20.0)
    return int(round(temp)), int(round(rain)), int(round(wind))


def compute_days(dates, series, lang, model=None):
    model = model or load_model()
    days = []
    for i, date in enumerate(dates):
        names, t, tn, r, g = day_values(series, i)
        feat = build_features(i, t, r, g)
        estimated = feat is None
        if estimated:
            feat = estimated_features(i)
        p = bust_probability(feat, model)
        if estimated:
            p = max(p, 0.35)               # we cannot verify agreement - never claim high confidence
        conf = int(round(100 * (1 - p)))
        contrib = contributions(feat, model)
        st, sr, sw = sub_scores(feat)
        rows = []
        for n, vt, vtn, vr, vg in zip(names, t, tn, r, g):
            rows.append({"model": MODEL_LABEL.get(n, n), "tmax": round(vt, 1), "tmin": round(vtn, 1),
                         "rain": round(vr, 1), "gust": round(vg, 0)})
        day = {
            "date": date, "label": day_name(date, lang), "lead": i,
            "confidence": conf, "level": label_for(conf), "bust_risk": int(round(100 * p)),
            "temp_conf": st, "rain_conf": sr, "wind_conf": sw,
            "tmax": round(mean(t), 1) if t else None, "tmin": round(mean(tn), 1) if tn else None,
            "tmax_lo": round(min(t), 1) if t else None, "tmax_hi": round(max(t), 1) if t else None,
            "rain": round(mean(r), 1) if r else None, "rain_lo": round(min(r), 1) if r else None, "rain_hi": round(max(r), 1) if r else None,
            "gust": round(mean(g)) if g else None, "gust_lo": round(min(g)) if g else None, "gust_hi": round(max(g)) if g else None,
            "models": rows, "estimated": estimated,
            "spread": {"temp": round(feat["sT"], 1), "rain": round(math.expm1(feat["lsP"]), 1), "gust": round(feat["sG"], 1)},
            "drivers": drivers_for(i, names, t, r, g, None if estimated else feat, contrib, lang),
        }
        days.append(day)
    return days


def make_alerts(days, lang):
    alerts = []
    for d in days:
        if d["lead"] < 1:
            continue
        p = d["bust_risk"] / 100.0
        hazard = None
        if (d["rain_hi"] or 0) >= 40:
            hazard = "hz_rain"
        elif (d["gust_hi"] or 0) >= 60:
            hazard = "hz_wind"
        elif (d["tmax_hi"] or 0) >= 42:
            hazard = "hz_heat"
        if p < 0.5 and not (hazard and p >= 0.35):
            continue
        why = d["drivers"][0]["text"] if d["drivers"] else ""
        title = T(lang, "a_title_hz", hazard=T(lang, hazard), day=d["label"]) if hazard else T(lang, "a_title", day=d["label"])
        alerts.append({
            "id": "rel", "level": "warning" if (p >= 0.7 or hazard) else "advisory",
            "title": title, "message": T(lang, "a_msg", p=d["bust_risk"], why=why),
            "date": d["date"], "p": d["bust_risk"],
        })
    alerts.sort(key=lambda a: (0 if a["level"] == "warning" else 1, -a["p"]))
    return alerts[:3]


def model_card(model):
    meta = model.get("meta") or {}
    return {
        "source": model.get("source", "prior"),
        "trained_at": meta.get("trained_at"),
        "auc": meta.get("auc"), "auc_baseline": meta.get("auc_baseline"),
        "precision": meta.get("precision"), "recall": meta.get("recall"), "brier": meta.get("brier"),
        "bust_rate": meta.get("bust_rate"), "n_train": meta.get("n_train"), "n_test": meta.get("n_test"),
        "cities": meta.get("cities"),
        "definition": {"tmax_c": BUST["tmax"], "rain_mm": BUST["rain"], "gust_kmh": BUST["gust"]},
    }


def build_reliability(lat, lon, lang):
    dates, series = fetch_models(lat, lon, 10)
    model = load_model()
    days = compute_days(dates, series, lang, model)
    alerts = make_alerts(days, lang)
    future = [d for d in days if d["lead"] >= 1] or days
    avg = int(round(mean([d["confidence"] for d in future]))) if future else 0
    best = max(future, key=lambda d: d["confidence"]) if future else None
    worst = min(future, key=lambda d: d["confidence"]) if future else None
    summary = T(lang, "sum_all", avg=avg, best=best["label"] if best else "-", worst=worst["label"] if worst else "-")
    return {
        "lat": lat, "lon": lon,
        "models_used": [MODEL_LABEL.get(m, m) for m in series.keys()],
        "days": days, "alerts": alerts, "average": avg, "summary": summary,
        "model_card": model_card(model),
    }


def get_cached(lat, lon, lang):
    key = ("rel", round(lat, 2), round(lon, 2), lang)
    hit = cache_get(key, 900)
    return hit or cache_set(key, build_reliability(lat, lon, lang))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route("/api/reliability")
def api_reliability():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    lang = norm_lang(request.args.get("language"))
    try:
        return jsonify(get_cached(lat, lon, lang))
    except Exception as e:
        return jsonify({"error": "Unable to load forecast reliability: %s" % e}), 502


@bp.route("/api/reliability-explain", methods=["POST"])
def api_reliability_explain():
    data = request.get_json(silent=True) or {}
    lat, lon = get_coords(data)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    lang = norm_lang(data.get("language"))
    try:
        idx = int(data.get("day", 1))
    except (TypeError, ValueError):
        idx = 1
    place = str(data.get("location", "this location"))[:120]
    try:
        rel = get_cached(lat, lon, lang)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    if not (0 <= idx < len(rel["days"])):
        return jsonify({"error": "Day out of range."}), 400
    d = rel["days"][idx]
    fallback = " ".join(x["text"] for x in d["drivers"])
    groq = _ctx["groq"]
    if not groq:
        return jsonify({"explanation": fallback, "source": "rules"})
    facts = "\n".join("- %s: max %.1f°C, rain %.1f mm, gusts %.0f km/h" % (m["model"], m["tmax"], m["rain"], m["gust"]) for m in d["models"])
    prompt = "You are WeatherGPT. %s\n%s\n\nForecast confidence %d%% (bust risk %d%%).\nModel forecasts:\n%s\nReasons found:\n%s" % (
        LANG_INSTR[lang],
        T(lang, "ai_prompt", day=d["label"], place=place, lvl=T(lang, "lvl_" + d["level"])),
        d["confidence"], d["bust_risk"], facts or "- (single model)", fallback)
    text, err = groq(prompt)
    if err or not text:
        return jsonify({"explanation": fallback, "source": "rules"})
    return jsonify({"explanation": text.replace("*", "").replace("#", "").strip(), "source": "ai"})


def reliability_facts(lat, lon, lang="en"):
    """One short paragraph appended to the AI forecast explanation / chat prompts."""
    try:
        rel = get_cached(float(lat), float(lon), "en")
    except Exception:
        return ""
    lows = [d for d in rel["days"] if d["lead"] >= 1 and d["level"] == "low"]
    txt = "Forecast confidence (multi-model agreement, %s): average %d%% over 10 days." % (", ".join(rel["models_used"]), rel["average"])
    if lows:
        txt += " Low-confidence days: " + ", ".join("%s (%d%%)" % (d["label"], d["confidence"]) for d in lows[:4]) + "."
    return txt


# ---------------------------------------------------------------------------
# Verification: how did past forecasts do at this location?
# ---------------------------------------------------------------------------

LEADS = (1, 3, 5, 7)


def _daily_from_hourly(times, values, fn):
    out = {}
    for t, v in zip(times, values):
        if v is None:
            continue
        out.setdefault(t[:10], []).append(float(v))
    return {d: fn(vs) for d, vs in out.items() if len(vs) >= 20}


def fetch_verification_data(lat, lon, start, end):
    """Returns (observed_daily, {lead: forecast_daily}) both as {date: {tmax, rain, gust}}."""
    hv = {"tmax": "temperature_2m", "rain": "precipitation", "gust": "wind_gusts_10m"}
    agg = {"tmax": max, "rain": sum, "gust": max}
    p_arch = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "hourly": ",".join(hv.values()), "timezone": "auto", "wind_speed_unit": "kmh"}
    a = om_get(OM_ARCHIVE, p_arch, timeout=30)
    ah = a.json().get("hourly", {})
    obs = {k: _daily_from_hourly(ah.get("time", []), ah.get(v, []), agg[k]) for k, v in hv.items()}

    hourly = []
    for v in hv.values():
        hourly += ["%s_previous_day%d" % (v, L) for L in LEADS]
    p_prev = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "hourly": ",".join(hourly), "timezone": "auto", "wind_speed_unit": "kmh"}
    f = om_get(OM_PREVIOUS, p_prev, timeout=30)
    fh = f.json().get("hourly", {})
    fc = {}
    for L in LEADS:
        fc[L] = {k: _daily_from_hourly(fh.get("time", []), fh.get("%s_previous_day%d" % (v, L), []), agg[k]) for k, v in hv.items()}
    return obs, fc


def score_verification(obs, fc):
    """Pure function (unit-testable): -> per-lead metrics + a recent series for the chart."""
    rows = []
    for L in LEADS:
        et, er, eg, busts, hits, n = [], [], [], 0, 0, 0
        for d in sorted(obs["tmax"]):
            try:
                ot, orr, og = obs["tmax"][d], obs["rain"][d], obs["gust"][d]
                ft, fr, fg = fc[L]["tmax"][d], fc[L]["rain"][d], fc[L]["gust"][d]
            except KeyError:
                continue
            n += 1
            et.append(abs(ft - ot)); er.append(abs(fr - orr)); eg.append(abs(fg - og))
            busts += 1 if is_bust(ft, fr, fg, ot, orr, og) else 0
            hits += 1 if (ft >= WET_MM) == (orr >= WET_MM) else 0
        if n:
            rows.append({"lead": L, "n": n, "tmax_mae": round(mean(et), 1), "rain_mae": round(mean(er), 1),
                         "gust_mae": round(mean(eg), 1), "bust_rate": round(100.0 * busts / n),
                         "wet_dry_hit": round(100.0 * hits / n)})
    series = []
    ref = 3
    for d in sorted(obs["tmax"]):
        if d in fc.get(ref, {}).get("tmax", {}):
            series.append({"date": d, "obs": round(obs["tmax"][d], 1), "fc": round(fc[ref]["tmax"][d], 1)})
    return {"leads": rows, "series": series[-28:]}


@bp.route("/api/reliability-verify")
def api_reliability_verify():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    key = ("verify", round(lat, 2), round(lon, 2))
    hit = cache_get(key, 6 * 3600)
    if hit:
        return jsonify(hit)
    end = (datetime.now(timezone.utc) - timedelta(days=6)).date()      # reanalysis lags a few days
    start = end - timedelta(days=44)
    try:
        obs, fc = fetch_verification_data(lat, lon, start.isoformat(), end.isoformat())
        result = score_verification(obs, fc)
    except Exception as e:
        return jsonify({"error": "Verification data unavailable: %s" % e}), 502
    if not result["leads"]:
        return jsonify({"error": "Not enough verification data for this location yet."}), 404
    result.update({"start": start.isoformat(), "end": end.isoformat(),
                   "definition": {"tmax_c": BUST["tmax"], "rain_mm": BUST["rain"], "gust_kmh": BUST["gust"]}})
    return jsonify(cache_set(key, result))


# ---------------------------------------------------------------------------
# Map grid: bust risk around the selected location for every day
# ---------------------------------------------------------------------------

GRID_N = 5
GRID_STEP = 0.5


@bp.route("/api/reliability-grid")
def api_reliability_grid():
    lat, lon = get_coords(request.args)
    if lat is None:
        return jsonify({"error": "Valid lat and lon are required."}), 400
    key = ("grid", round(lat, 1), round(lon, 1))
    hit = cache_get(key, 1800)
    if hit:
        return jsonify(hit)
    half = GRID_N // 2
    pts = [(round(lat + (r - half) * GRID_STEP, 3), round(lon + (c - half) * GRID_STEP, 3))
           for r in range(GRID_N) for c in range(GRID_N)]
    pts = [(a, b) for a, b in pts if -90 <= a <= 90 and -180 <= b <= 180]
    ids = [m for m, _ in MODELS]
    per_point = [dict() for _ in pts]
    dates = []
    for m in ids:
        try:
            r = om_get(OM_FORECAST, {
                "latitude": ",".join(str(p[0]) for p in pts), "longitude": ",".join(str(p[1]) for p in pts),
                "daily": DAILY, "timezone": "auto", "forecast_days": 10, "wind_speed_unit": "kmh", "models": m}, timeout=30, tries=2)
            j = r.json()
            j = j if isinstance(j, list) else [j]
            for idx, item in enumerate(j[:len(pts)]):
                parsed = _parse_daily(item.get("daily", {}), [m])
                if parsed:
                    per_point[idx].update(parsed)
                    dates = dates or item.get("daily", {}).get("time", [])
        except Exception:
            continue
    model = load_model()
    out = []
    for (a, b), series in zip(pts, per_point):
        if not series:
            continue
        row = []
        for i in range(len(dates)):
            names, t, tn, rr, g = day_values(series, i)
            feat = build_features(i, t, rr, g)
            p = bust_probability(feat, model) if feat else max(bust_probability(estimated_features(i), model), 0.35)
            row.append(int(round(100 * p)))
        out.append({"lat": a, "lon": b, "risk": row})
    if not out:
        return jsonify({"error": "Reliability grid unavailable."}), 502
    return jsonify(cache_set(key, {"dates": dates, "points": out, "step": GRID_STEP}))
