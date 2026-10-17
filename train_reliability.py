# -*- coding: utf-8 -*-
"""Train and evaluate the WeatherGPT forecast-bust model.

    python train_reliability.py                # real data from Open-Meteo (needs internet, ~3-6 minutes)
    python train_reliability.py --days 120     # longer history
    python train_reliability.py --synthetic    # offline smoke test with fake data (does NOT produce a usable model)

What it does
------------
For many Indian cities and many past days it rebuilds what the four models (ECMWF, GFS, ICON, GEM) predicted
1, 2, 3, 5 and 7 days ahead (Open-Meteo "previous runs" API), compares the consensus with what actually happened
(ERA5 reanalysis), labels every (city, day, lead) as bust / not bust using the definition in reliability.py, and
fits a logistic regression that predicts the bust from model disagreement + lead time.

The data is split BY TIME (older 70% train, newest 30% test) so the reported numbers are honest out-of-sample
numbers. Output: data/reliability_model.json (weights + metrics), which the web app loads automatically.
"""

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import reliability as rel

CITIES = {
    "Hyderabad": (17.385, 78.487), "Vijayawada": (16.506, 80.648), "Visakhapatnam": (17.687, 83.218),
    "Tirupati": (13.628, 79.419), "Chennai": (13.083, 80.270), "Bengaluru": (12.972, 77.594),
    "Mumbai": (19.076, 72.878), "Pune": (18.520, 73.857), "Delhi": (28.614, 77.209),
    "Jaipur": (26.912, 75.787), "Lucknow": (26.847, 80.947), "Kolkata": (22.573, 88.364),
    "Guwahati": (26.145, 91.736), "Bhopal": (23.260, 77.413), "Ahmedabad": (23.023, 72.572),
    "Nagpur": (21.146, 79.088), "Kochi": (9.931, 76.267), "Patna": (25.594, 85.137),
}
LEADS = (1, 2, 3, 5, 7)
HV = {"tmax": "temperature_2m", "rain": "precipitation", "gust": "wind_gusts_10m"}
AGG = {"tmax": max, "rain": sum, "gust": max}


# --------------------------------------------------------------------------- data

def get_json(url, params, tries=3):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=40)
            if r.status_code == 429:
                time.sleep(8 * (k + 1))
                continue
            r.raise_for_status()
            return r.json()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


def pick(hourly, var, model):
    for key in (var + "_" + model, var):
        if key in hourly:
            return hourly[key]
    return None


def daily_of(times, values, fn):
    out = {}
    for t, v in zip(times, values):
        if v is not None:
            out.setdefault(t[:10], []).append(float(v))
    return {d: fn(v) for d, v in out.items() if len(v) >= 20}


def city_rows(name, lat, lon, start, end):
    obs_j = get_json(rel.OM_ARCHIVE, {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                                      "hourly": ",".join(HV.values()), "timezone": "auto", "wind_speed_unit": "kmh"})
    oh = obs_j.get("hourly", {})
    obs = {k: daily_of(oh.get("time", []), oh.get(v, []), AGG[k]) for k, v in HV.items()}

    fc = {}                                                  # fc[model][lead][var] -> {date: value}
    for m, _ in rel.MODELS:
        hourly_vars = ["%s_previous_day%d" % (v, L) for v in HV.values() for L in LEADS]
        try:
            j = get_json(rel.OM_PREVIOUS, {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                                           "hourly": ",".join(hourly_vars), "models": m, "timezone": "auto",
                                           "wind_speed_unit": "kmh"})
        except Exception as e:
            print("   skip %s/%s: %s" % (name, m, e))
            continue
        h = j.get("hourly", {})
        fc[m] = {L: {k: daily_of(h.get("time", []), pick(h, "%s_previous_day%d" % (v, L), m) or [], AGG[k])
                     for k, v in HV.items()} for L in LEADS}
    rows = []
    for d in sorted(obs["tmax"]):
        for L in LEADS:
            t, r, g = [], [], []
            for m in fc:
                try:
                    t.append(fc[m][L]["tmax"][d]); r.append(fc[m][L]["rain"][d]); g.append(fc[m][L]["gust"][d])
                except KeyError:
                    continue
            feat = rel.build_features(L, t, r, g)
            if not feat or d not in obs["rain"] or d not in obs["gust"]:
                continue
            y = 1 if rel.is_bust(rel.mean(t), rel.mean(r), rel.mean(g), obs["tmax"][d], obs["rain"][d], obs["gust"][d]) else 0
            rows.append({"city": name, "date": d, "x": feat, "y": y})
    return rows


def synthetic_rows(n_days=120):
    """Fake data with a learnable pattern - only to prove the pipeline runs offline."""
    rnd = random.Random(7)
    start = datetime(2025, 1, 1)
    rows = []
    for c in range(8):
        for i in range(n_days):
            d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            for L in LEADS:
                sT = abs(rnd.gauss(0.4 + 0.3 * L, 0.6)); sP = abs(rnd.gauss(0.5 + 0.8 * L, 2)); sG = abs(rnd.gauss(3 + 1.5 * L, 3))
                wet = rnd.random()
                feat = {"lead": float(L), "sT": sT, "lsP": math.log1p(sP), "sG": sG, "wetdis": 4 * wet * (1 - wet), "lmeanP": math.log1p(abs(rnd.gauss(3, 4)))}
                p = rel.sigmoid(-3.3 + 0.15 * L + 0.4 * sT + 0.75 * feat["lsP"] + 0.03 * sG + 0.9 * feat["wetdis"])
                rows.append({"city": "C%d" % c, "date": d, "x": feat, "y": 1 if rnd.random() < p else 0})
    return rows


# --------------------------------------------------------------------------- model

def fit_logistic(X, y, epochs=900, lr=0.15, l2=0.01):
    n, k = len(X), len(X[0])
    w, b = [0.0] * k, math.log(max(sum(y), 1) / max(n - sum(y), 1))
    for _ in range(epochs):
        gw, gb = [0.0] * k, 0.0
        for xi, yi in zip(X, y):
            err = rel.sigmoid(b + sum(wj * xj for wj, xj in zip(w, xi))) - yi
            gb += err
            for j in range(k):
                gw[j] += err * xi[j]
        b -= lr * gb / n
        for j in range(k):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
    return w, b


def auc(y, p):
    pairs = sorted(zip(p, y))
    pos = sum(y); neg = len(y) - pos
    if not pos or not neg:
        return None
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        rank_sum += avg_rank * sum(1 for q in pairs[i:j] if q[1] == 1)
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="days of history per city")
    ap.add_argument("--synthetic", action="store_true", help="offline smoke test with fake data")
    ap.add_argument("--out", default=rel.MODEL_FILE)
    args = ap.parse_args()

    if args.synthetic:
        rows = synthetic_rows()
        print("SYNTHETIC mode - the result is only a pipeline test.")
        out = args.out + ".synthetic"
    else:
        end = (datetime.now(timezone.utc) - timedelta(days=6)).date()
        start = end - timedelta(days=args.days)
        rows = []
        for i, (name, (la, lo)) in enumerate(CITIES.items(), 1):
            print("[%d/%d] %s ..." % (i, len(CITIES), name), flush=True)
            try:
                got = city_rows(name, la, lo, start.isoformat(), end.isoformat())
                rows += got
                print("   %d samples" % len(got))
            except Exception as e:
                print("   failed:", e)
            time.sleep(1.0)
        out = args.out
    if len(rows) < 300:
        sys.exit("Not enough samples (%d). Check your internet connection and try again." % len(rows))

    rows.sort(key=lambda r: r["date"])
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]
    F = rel.FEATURES
    means = {k: sum(r["x"][k] for r in train) / len(train) for k in F}
    scales = {k: (math.sqrt(sum((r["x"][k] - means[k]) ** 2 for r in train) / len(train)) or 1.0) for k in F}

    def vec(r):
        return [(r["x"][k] - means[k]) / scales[k] for k in F]

    w, b = fit_logistic([vec(r) for r in train], [r["y"] for r in train])
    model = {"bias": b, "weights": dict(zip(F, w)), "means": means, "scales": scales}

    p_test = [rel.bust_probability(r["x"], dict(model, source="trained")) for r in test]
    y_test = [r["y"] for r in test]
    base_auc = auc(y_test, [r["x"]["lead"] for r in test])       # baseline: "longer lead = riskier" only
    # threshold that maximises F1 on the TRAINING set (so the test set stays untouched)
    p_train = [rel.bust_probability(r["x"], dict(model, source="trained")) for r in train]
    best_t, best_f1 = 0.5, -1
    for t in [i / 100.0 for i in range(10, 90, 2)]:
        tp = sum(1 for p, r in zip(p_train, train) if p >= t and r["y"]); fp = sum(1 for p, r in zip(p_train, train) if p >= t and not r["y"])
        fn = sum(1 for p, r in zip(p_train, train) if p < t and r["y"])
        f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0
        if f1 > best_f1:
            best_t, best_f1 = t, f1
    tp = sum(1 for p, y in zip(p_test, y_test) if p >= best_t and y); fp = sum(1 for p, y in zip(p_test, y_test) if p >= best_t and not y)
    fn = sum(1 for p, y in zip(p_test, y_test) if p < best_t and y)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    brier = sum((p - y) ** 2 for p, y in zip(p_test, y_test)) / len(y_test)
    meta = {
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "n_train": len(train), "n_test": len(test), "cities": len({r["city"] for r in rows}),
        "bust_rate": round(sum(r["y"] for r in rows) / len(rows), 3),
        "auc": round(auc(y_test, p_test) or 0, 3), "auc_baseline": round(base_auc or 0, 3),
        "precision": round(precision, 3), "recall": round(recall, 3), "threshold": best_t, "brier": round(brier, 3),
        "bust_definition": rel.BUST, "split": "time-ordered 70/30", "synthetic": bool(args.synthetic),
    }
    model["meta"] = meta
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2)
    print("\nSaved", out)
    print(json.dumps(meta, indent=2))
    print("\nHow to read this: AUC 0.5 = guessing, 1.0 = perfect. 'auc_baseline' uses lead time alone;")
    print("the model is only useful if its AUC is clearly above the baseline on the held-out (newest) data.")


if __name__ == "__main__":
    main()
