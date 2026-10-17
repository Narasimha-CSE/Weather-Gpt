# WeatherGPT — setup

## Run (Windows PowerShell)
```powershell
cd WeatherGPT
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000 — you will be sent to the **login page**. Click *Create an account* the first time.

Your `.env` must contain `WEATHER_API_KEY` (OpenWeather) and `GROQ_API_KEY`.
Email OTP login uses Gmail SMTP: `.env` also needs `SMTP_EMAIL` and `SMTP_APP_PASSWORD` (a Google App Password).
Optional: add `SECRET_KEY=any-long-random-string` (otherwise one is generated and stored in `data/secret.key`).

## What was added
| Area | Where |
|---|---|
| Login / Register with emailed 6-digit OTP (SQLite, sessions, Gmail SMTP, no passwords) | `auth.py`, `templates/auth.html`, `static/auth.css`, `static/auth.js` |
| Forecast, alerts, advice, travel score, farmer advisory, climate, map APIs | `features.py`, `i18n_data.py` (English / Telugu / Hindi text) |
| New website sections + animations | `templates/index.html`, `static/features.css`, `static/features.js` |
| Chat AI now sees the forecast (answers "tomorrow?" questions) | `app.py` |

User accounts are stored in `data/weathergpt.db` (created automatically). Delete the `data/` folder to reset all accounts.

## Data sources
* OpenWeather — current weather, geocoding, map tiles (proxied by the server so your key is never sent to the browser)
* Open-Meteo (no key) — hourly/daily forecast, UV, wind direction, 10–20 year climate history
* RainViewer (no key) — animated radar
* Groq — chat, forecast explanation, crop advice

## Notes
* Weather map layers (rain/wind/temp/clouds) need an OpenWeather key that has access to the *Weather Maps* tiles; if your plan does not include them the layer is simply blank. Radar is independent of that.
* Internet access is required in the browser for Leaflet, Chart.js and map tiles (loaded from CDNs).


## Sign-in options
* **Email OTP (works out of the box)** - Create account: name + email -> code by email -> account created -> the *Log in* section opens with your email filled in -> Send OTP -> "Welcome, <name>!" with a done mark -> app.
  Needs `SMTP_EMAIL` and `SMTP_APP_PASSWORD` (Google App Password) in `.env`.
* **Google / Facebook** - fill `GOOGLE_CLIENT_ID/SECRET` or `FACEBOOK_APP_ID/SECRET` in `.env` and register these redirect URIs in the provider console:
  `http://127.0.0.1:5000/auth/social/google/callback` and `http://127.0.0.1:5000/auth/social/facebook/callback`
  (use your real domain in production, or set `OAUTH_REDIRECT_BASE`). Without keys the buttons show a "not set up yet" message.
* **Phone number** - SMS code through Twilio: fill `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`. For local testing only, set `PHONE_OTP_DEV=1` to print the code in the server console.

## Pages (bottom navigation after login)
| Page | Contents |
|------|----------|
| Home | weather animation scene, city search, live weather, WeatherGPT AI chat |
| Graphs | weather analytics (previous/next days + trend graph), hourly & 5-day forecast chart, climate history charts |
| Tools | interactive weather map, travel intelligence, unit converter, heat index / dew point, Beaufort wind scale |
| AI Advisory | smart insights and precautions, smart alerts, personal recommendations, farmer advisory |


## Forecast Reliability module (new)
Answers "how much can I trust this forecast?" - day by day for the next 10 days.

| Feature | Where |
|---|---|
| 10-day confidence cards, model-spread chart, per-day "why" + AI explanation | Graphs page -> **Reliability** section |
| Track record: what the forecast made 1/3/5/7 days ago said vs what really happened (ERA5) | same section, left card |
| Bust-risk map layer (5x5 grid around the city, day slider) | Tools page -> map -> **Reliability** button |
| Low-confidence / "heavy rain but models disagree" alerts | merged into **Smart Alerts** (AI Advisory page) |
| AI forecast explanation and chat now also know the confidence | `features.py` |

Files: `reliability.py` (API), `train_reliability.py` (training + evaluation), `static/reliability.js`, `static/reliability.css`.
API: `/api/reliability`, `/api/reliability-explain`, `/api/reliability-verify`, `/api/reliability-grid`. No new pip packages, no new API keys.

### Definition of a forecast "bust"
Consensus forecast (mean of ECMWF, GFS, ICON, GEM) is off versus reanalysis by **>= 4 C max temperature**, **or >= 10 mm daily rain**, **or >= 25 km/h wind gust**. Change `BUST` in `reliability.py` to tune it.

### Train the model (do this before demoing accuracy)
```powershell
python train_reliability.py            # ~3-6 min, needs internet, writes data/reliability_model.json
python train_reliability.py --days 120 # more history
```
It rebuilds past forecasts for 18 Indian cities, labels busts, trains a logistic regression on the OLDER 70 % of the data and reports AUC / precision / recall on the NEWEST 30 %, next to a lead-time-only baseline. The app picks the file up automatically and shows these numbers in the "Bust-risk model" card. **Until you run it the app uses heuristic prior weights and says so on screen.**


## SEO, Google Search Console and AdSense (merged from WeatherGpt-main)
| Item | Where |
|---|---|
| `/robots.txt` and `/sitemap.xml` (public, no login) | `app.py` |
| Search Console HTML-file verification `google825a0e9664b14fbc.html` (also served by route if the file is missing) | project root + `app.py` |
| Search Console meta-tag placeholder | `templates/index.html` `<head>` |
| Google AdSense account meta + script (`ca-pub-7653114847966237`) | `templates/auth.html` `<head>` |
| Auto-detect visitor location on the home page | `static/location.js` |
| Vercel deployment config | `vercel.json` |
| Brevo email OTP (used when `BREVO_API_KEY` is set, otherwise Gmail SMTP) | `auth.py` |
| New `.env` keys: `BREVO_API_KEY`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`, `SITE_URL`, `GOOGLE_VERIFICATION_FILE`, `COOKIE_SECURE`, `SECRET_KEY` | `.env`, `.env.example` |
| Existing accounts + session key from the main project | `data/weathergpt.db`, `data/secret.key` |
