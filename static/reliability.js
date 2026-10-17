/* =====================================================================
   WeatherGPT - forecast reliability
   10-day confidence cards, model-spread chart, "why" explanations, track record,
   bust-risk map layer (inside the existing weather map) and alerts merged into Smart Alerts.
===================================================================== */
(function () {
    "use strict";

    const $ = (id) => document.getElementById(id);
    const qa = (sel, root) => Array.from((root || document).querySelectorAll(sel));
    const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const lang = () => (window.WG && window.WG.getLanguage && window.WG.getLanguage()) || "en";
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const TXT = {
        en: {
            label: "FORECAST RELIABILITY", title: "How much can you trust the next 10 days?", empty: "Search for a city to see this section.",
            avg_title: "Average 10-day confidence", t_temp: "🌡️ Temperature", t_rain: "🌧️ Rain", t_wind: "💨 Wind gusts",
            chart_note: "Each line is one forecast model. The wider the lines spread apart, the less reliable that day is.",
            v_title: "📋 Track record at this location", m_title: "🧠 Bust-risk model", layer_rel: "🎯 Reliability",
            loading: "Loading…", fail: "Could not load forecast reliability.", conf: "confidence", risk: "Bust risk",
            high: "High", medium: "Medium", low: "Low", today: "Today",
            c_temp: "Temperature", c_rain: "Rain", c_wind: "Wind", models: "models",
            th_model: "Model", th_tmax: "Max °C", th_rain: "Rain mm", th_gust: "Gust km/h", consensus: "Consensus",
            why: "Why this confidence?", ai_btn: "🤖 Explain with AI", ai_wait: "Thinking…", ai_fail: "Explanation unavailable.",
            est_note: "Estimated from lead time only (just one model reaches this far).",
            v_none: "Track record unavailable for this location right now.", v_lead: "Forecast made", v_days: "days ahead", v_days_s: "d ahead",
            v_bust: "Bust rate", v_mae: "Max-temp error", v_hit: "Wet/dry right", v_n: "days checked",
            v_intro: "How the forecast from {n} days earlier compared with what really happened ({a} to {b}, ERA5 reanalysis).",
            v_chart: "3-day-ahead forecast vs observed max temp (°C)", ds_fc: "Forecast (3 days ahead)", ds_obs: "Observed",
            m_trained: "Trained", m_prior: "Prior (not trained yet)", m_src: "Weights", m_auc: "Accuracy on unseen data (AUC)", m_base: "Baseline using lead time only",
            m_prec: "Precision", m_rec: "Recall", m_data: "Training samples", m_cities: "Cities", m_when: "Trained on",
            m_def: "A forecast “bust” = consensus off by ≥ {t}°C max temperature, or ≥ {r} mm rain, or ≥ {g} km/h gusts versus reanalysis.",
            m_prior_note: "These risk numbers use heuristic starting weights. Run train_reliability.py to fit and evaluate the model on real forecast history.",
            alert_tag: "RELIABILITY", map_day: "Day", map_fail: "Reliability map unavailable.", map_tip: "Bust risk",
            ok_all: "Models agree well on this day.",
        },
        te: {
            label: "అంచనా నమ్మకం", title: "తదుపరి 10 రోజుల అంచనాను ఎంత నమ్మవచ్చు?", empty: "ఈ విభాగం చూడటానికి నగరాన్ని వెతకండి.",
            avg_title: "10 రోజుల సగటు నమ్మకం", t_temp: "🌡️ ఉష్ణోగ్రత", t_rain: "🌧️ వర్షం", t_wind: "💨 గాలి ఝంఝా",
            chart_note: "ప్రతి గీత ఒక అంచనా మోడల్. గీతల మధ్య దూరం ఎక్కువైతే ఆ రోజు అంచనా తక్కువ నమ్మదగినది.",
            v_title: "📋 ఈ ప్రాంతంలో గత పనితీరు", m_title: "🧠 అంచనా-తప్పిదం మోడల్", layer_rel: "🎯 నమ్మకం",
            loading: "లోడ్ అవుతోంది…", fail: "అంచనా నమ్మకాన్ని లోడ్ చేయలేకపోయాం.", conf: "నమ్మకం", risk: "తప్పే ప్రమాదం",
            high: "అధికం", medium: "మధ్యస్థం", low: "తక్కువ", today: "ఈ రోజు",
            c_temp: "ఉష్ణోగ్రత", c_rain: "వర్షం", c_wind: "గాలి", models: "మోడళ్లు",
            th_model: "మోడల్", th_tmax: "గరిష్ఠ °C", th_rain: "వర్షం మి.మీ", th_gust: "ఝంఝా కి.మీ/గం", consensus: "సగటు అంచనా",
            why: "ఈ నమ్మకం ఎందుకు?", ai_btn: "🤖 AIతో వివరించు", ai_wait: "ఆలోచిస్తోంది…", ai_fail: "వివరణ అందుబాటులో లేదు.",
            est_note: "రోజుల దూరం ఆధారంగా మాత్రమే అంచనా (ఒకే మోడల్ ఇంత దూరం చూపిస్తోంది).",
            v_none: "ఈ ప్రాంతానికి గత పనితీరు ప్రస్తుతం అందుబాటులో లేదు.", v_lead: "అంచనా వేసినది", v_days: "రోజుల ముందు", v_days_s: "రోజుల ముందు",
            v_bust: "తప్పిన శాతం", v_mae: "గరిష్ఠ ఉష్ణోగ్రత తేడా", v_hit: "వర్షం ఉందా/లేదా సరైనది", v_n: "రోజులు పరిశీలించాం",
            v_intro: "{n} రోజుల ముందు చేసిన అంచనా వాస్తవంతో ఎలా పోలిందో ({a} నుంచి {b}, ERA5).",
            v_chart: "3 రోజుల ముందు అంచనా vs వాస్తవ గరిష్ఠ ఉష్ణోగ్రత (°C)", ds_fc: "అంచనా (3 రోజుల ముందు)", ds_obs: "వాస్తవం",
            m_trained: "శిక్షణ పొందినది", m_prior: "ప్రాథమిక (ఇంకా శిక్షణ లేదు)", m_src: "బరువులు", m_auc: "కొత్త డేటాపై కచ్చితత్వం (AUC)", m_base: "రోజుల ఆధారిత బేస్‌లైన్",
            m_prec: "ప్రెసిషన్", m_rec: "రీకాల్", m_data: "శిక్షణ నమూనాలు", m_cities: "నగరాలు", m_when: "శిక్షణ తేదీ",
            m_def: "అంచనా “తప్పు” అంటే: గరిష్ఠ ఉష్ణోగ్రత ≥ {t}°C, వర్షం ≥ {r} మి.మీ, లేదా గాలి ఝంఝా ≥ {g} కి.మీ/గం తేడా.",
            m_prior_note: "ఈ ప్రమాద సంఖ్యలు ప్రాథమిక బరువులపై ఆధారపడినవి. నిజమైన డేటాపై శిక్షణ కోసం train_reliability.py నడపండి.",
            alert_tag: "నమ్మకం", map_day: "రోజు", map_fail: "నమ్మకం మ్యాప్ అందుబాటులో లేదు.", map_tip: "తప్పే ప్రమాదం",
            ok_all: "ఈ రోజుపై మోడళ్లు ఏకీభవిస్తున్నాయి.",
        },
        hi: {
            label: "पूर्वानुमान भरोसा", title: "अगले 10 दिनों के पूर्वानुमान पर कितना भरोसा करें?", empty: "यह सेक्शन देखने के लिए शहर खोजें.",
            avg_title: "10 दिनों का औसत भरोसा", t_temp: "🌡️ तापमान", t_rain: "🌧️ बारिश", t_wind: "💨 हवा के झोंके",
            chart_note: "हर रेखा एक पूर्वानुमान मॉडल है. रेखाएँ जितनी दूर होंगी, उस दिन का पूर्वानुमान उतना कम भरोसेमंद है.",
            v_title: "📋 इस स्थान पर पिछला प्रदर्शन", m_title: "🧠 गलत-पूर्वानुमान जोखिम मॉडल", layer_rel: "🎯 भरोसा",
            loading: "लोड हो रहा है…", fail: "पूर्वानुमान भरोसा लोड नहीं हो सका.", conf: "भरोसा", risk: "गलत होने का जोखिम",
            high: "उच्च", medium: "मध्यम", low: "कम", today: "आज",
            c_temp: "तापमान", c_rain: "बारिश", c_wind: "हवा", models: "मॉडल",
            th_model: "मॉडल", th_tmax: "अधिकतम °C", th_rain: "बारिश मिमी", th_gust: "झोंके किमी/घं", consensus: "औसत अनुमान",
            why: "यह भरोसा क्यों?", ai_btn: "🤖 AI से समझाएँ", ai_wait: "सोच रहा है…", ai_fail: "स्पष्टीकरण उपलब्ध नहीं.",
            est_note: "केवल दिनों की दूरी से अनुमानित (इतनी दूर सिर्फ एक मॉडल देखता है).",
            v_none: "इस स्थान के लिए पिछला प्रदर्शन अभी उपलब्ध नहीं.", v_lead: "पूर्वानुमान बना", v_days: "दिन पहले", v_days_s: "दिन पहले",
            v_bust: "गलत होने की दर", v_mae: "अधिकतम तापमान त्रुटि", v_hit: "बारिश हाँ/ना सही", v_n: "दिन जाँचे गए",
            v_intro: "{n} दिन पहले का पूर्वानुमान असल मौसम से कैसा रहा ({a} से {b}, ERA5).",
            v_chart: "3 दिन पहले का पूर्वानुमान बनाम वास्तविक अधिकतम तापमान (°C)", ds_fc: "पूर्वानुमान (3 दिन पहले)", ds_obs: "वास्तविक",
            m_trained: "प्रशिक्षित", m_prior: "प्रारंभिक (अभी प्रशिक्षित नहीं)", m_src: "वज़न", m_auc: "नए डेटा पर सटीकता (AUC)", m_base: "केवल दिनों पर आधारित बेसलाइन",
            m_prec: "प्रिसीजन", m_rec: "रिकॉल", m_data: "प्रशिक्षण नमूने", m_cities: "शहर", m_when: "प्रशिक्षण तिथि",
            m_def: "पूर्वानुमान “गलत” = अधिकतम तापमान में ≥ {t}°C, बारिश में ≥ {r} मिमी, या झोंकों में ≥ {g} किमी/घं का अंतर.",
            m_prior_note: "ये जोखिम संख्याएँ प्रारंभिक वज़न पर आधारित हैं. असली डेटा पर प्रशिक्षण के लिए train_reliability.py चलाएँ.",
            alert_tag: "भरोसा", map_day: "दिन", map_fail: "भरोसा मैप उपलब्ध नहीं.", map_tip: "गलत होने का जोखिम",
            ok_all: "इस दिन पर मॉडल सहमत हैं.",
        },
    };
    const tx = (k) => (TXT[lang()] && TXT[lang()][k]) || TXT.en[k] || k;
    const fill = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => (o[k] == null ? "" : o[k]));

    const COLOR = { high: "#38d996", medium: "#fbbf24", low: "#f87171" };
    const MODEL_COLORS = { ECMWF: "#5d78ff", GFS: "#38bdf8", ICON: "#38d996", GEM: "#fb923c" };

    const R = { lat: null, lon: null, name: "", data: null, sel: 3, view: "tmax", chart: null, vchart: null, token: 0,
                alerts: [], map: null, layer: null, grid: null, gridKey: "", mapOn: false };

    /* ---------------------------------------------------------------- static labels */
    function applyStatic() {
        qa("[data-ri]").forEach((el) => { el.textContent = tx(el.dataset.ri); });
        const d = $("relMapDayLabel"); if (d) d.textContent = tx("map_day");
    }

    function setState(state) { // empty | loading | ready
        const sec = $("relSection"); if (!sec) return;
        sec.querySelector(".fx-empty").hidden = state !== "empty";
        sec.querySelector(".fx-body").hidden = state === "empty";
        sec.classList.toggle("loading", state === "loading");
    }

    function fail(msg) {
        const sec = $("relSection"); if (!sec) return;
        sec.classList.remove("loading");
        sec.querySelector(".fx-empty").hidden = true;
        const body = sec.querySelector(".fx-body"); body.hidden = false;
        body.insertAdjacentHTML("afterbegin", '<div class="fx-error rel-fail">' + esc(msg || tx("fail")) + "</div>");
    }

    /* ---------------------------------------------------------------- loading */
    async function load() {
        if (R.lat == null) return;
        const token = ++R.token;
        qa(".rel-fail").forEach((n) => n.remove());
        setState("loading");
        try {
            const res = await fetch("/api/reliability?lat=" + R.lat + "&lon=" + R.lon + "&language=" + lang());
            const j = await res.json();
            if (token !== R.token) return;
            if (!res.ok) throw new Error(j.error || tx("fail"));
            R.data = j;
            R.alerts = j.alerts || [];
            if (R.sel >= j.days.length) R.sel = 0;
            setState("ready");
            render();
            window.WGRel.mergeAlerts();
            loadVerify(token);
            if (R.mapOn) loadMapLayer();
        } catch (err) {
            if (token === R.token) fail(err.message);
        }
    }

    /* ---------------------------------------------------------------- rendering */
    function render() {
        const j = R.data; if (!j) return;
        const models = $("relModels");
        if (models) { models.hidden = false; models.textContent = "🛰️ " + j.models_used.length + " " + tx("models") + ": " + j.models_used.join(" · "); }
        const avg = j.average, lvl = avg >= 70 ? "high" : avg >= 45 ? "medium" : "low";
        const ring = $("relRing"); ring.style.setProperty("--c", COLOR[lvl]); ring.style.setProperty("--p", avg);
        animateNumber($("relAvg"), avg);
        $("relSummary").textContent = j.summary;
        $("relDays").innerHTML = j.days.map((d, i) =>
            '<button type="button" class="rel-day lvl-' + d.level + (i === R.sel ? " on" : "") + (d.estimated ? " est" : "") + '" data-i="' + i + '" style="--i:' + i + '" aria-label="' + esc(d.label + " " + d.confidence + "% " + tx("conf")) + '">' +
            '<div class="dn">' + esc(i === 0 ? tx("today") : d.label) + "</div>" +
            '<div class="pc">' + d.confidence + "<small>%</small></div>" +
            '<div class="bar"><i style="--w:' + d.confidence + '%"></i></div>' +
            '<div class="lv">' + esc(tx(d.level)) + "</div>" +
            '<div class="mini">' + (d.tmax_lo != null ? Math.round(d.tmax_lo) + "–" + Math.round(d.tmax_hi) + "°C" : "–") + "</div></button>").join("");
        renderChart();
        renderDetail();
        renderCard(j.model_card);
    }

    function animateNumber(el, to) {
        if (reduce) { el.textContent = to; return; }
        const from = Number(el.textContent) || 0, t0 = performance.now(), ms = 900;
        (function step(now) {
            const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
            el.textContent = Math.round(from + (to - from) * e);
            if (k < 1) requestAnimationFrame(step);
        })(t0);
    }

    function chartColors() { return { tick: "#9fb0c6", grid: "rgba(255,255,255,.08)" }; }

    function renderChart() {
        const j = R.data, cv = $("relChart"); if (!cv || !window.Chart || !j) return;
        const key = R.view, labels = j.days.map((d) => d.label);
        const names = j.models_used;
        const ds = names.map((n) => ({
            label: n, borderColor: MODEL_COLORS[n] || "#fff", backgroundColor: MODEL_COLORS[n] || "#fff",
            data: j.days.map((d) => { const m = d.models.find((x) => x.model === n); return m ? m[key] : null; }),
            tension: .3, borderWidth: 2, pointRadius: 3, spanGaps: false,
        }));
        const c = chartColors();
        const units = { tmax: "°C", rain: "mm", gust: "km/h" };
        if (R.chart) R.chart.destroy();
        R.chart = new Chart(cv, {
            type: "line", data: { labels, datasets: ds },
            options: {
                responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 700 },
                interaction: { mode: "index", intersect: false },
                plugins: { legend: { labels: { color: c.tick, usePointStyle: true, boxWidth: 8 } },
                           tooltip: { callbacks: { label: (ctx) => ctx.dataset.label + ": " + (ctx.parsed.y == null ? "–" : ctx.parsed.y + " " + units[key]) } } },
                scales: { x: { ticks: { color: c.tick, maxRotation: 0, autoSkip: true }, grid: { color: c.grid } },
                          y: { ticks: { color: c.tick, callback: (v) => v + " " + units[key] }, grid: { color: c.grid }, beginAtZero: key !== "tmax" } },
                onClick: (e, els) => { if (els && els.length) select(els[0].index); },
            },
        });
    }

    function meter(label, val) {
        const lvl = val >= 70 ? "high" : val >= 45 ? "medium" : "low";
        return '<div class="rel-meter lvl-' + lvl + '"><small><span>' + esc(label) + "</span><b>" + val + '%</b></small><div class="bar"><i style="--w:' + val + '%"></i></div></div>';
    }

    function renderDetail() {
        const j = R.data, el = $("relDetail"); if (!j || !el) return;
        const d = j.days[R.sel]; if (!d) { el.innerHTML = ""; return; }
        const rows = d.models.map((m) => "<tr><td>" + esc(m.model) + "</td><td>" + m.tmax + "</td><td>" + m.rain + "</td><td>" + m.gust + "</td></tr>").join("");
        const cons = d.models.length ? '<tr class="cons"><td>' + esc(tx("consensus")) + "</td><td>" + d.tmax + "</td><td>" + d.rain + "</td><td>" + d.gust + "</td></tr>" : "";
        el.className = "rel-detail lvl-" + d.level;
        el.innerHTML =
            "<h3>" + esc(d.lead === 0 ? tx("today") + " · " + d.label : d.label) + ' <span class="chip">' + esc(tx(d.level)) + " · " + d.confidence + "% " + esc(tx("conf")) + '</span> <span class="chip" style="--c:#8fa8ff">' + esc(tx("risk")) + " " + d.bust_risk + "%</span></h3>" +
            '<div class="rel-meters">' + meter(tx("c_temp"), d.temp_conf) + meter(tx("c_rain"), d.rain_conf) + meter(tx("c_wind"), d.wind_conf) + "</div>" +
            (rows ? '<div class="rel-table-wrap"><table class="rel-table"><thead><tr><th>' + esc(tx("th_model")) + "</th><th>" + esc(tx("th_tmax")) + "</th><th>" + esc(tx("th_rain")) + "</th><th>" + esc(tx("th_gust")) + "</th></tr></thead><tbody>" + rows + cons + "</tbody></table></div>" : "") +
            '<div class="small-label" style="margin-bottom:8px">' + esc(tx("why")) + "</div>" +
            '<ul class="rel-why">' + d.drivers.map((x) => '<li class="' + esc(x.kind) + '">' + esc(x.text) + "</li>").join("") + "</ul>" +
            (d.estimated ? '<p class="rel-note">' + esc(tx("est_note")) + "</p>" : "") +
            '<button type="button" class="fx-btn" id="relAiBtn">' + esc(tx("ai_btn")) + "</button>" +
            '<div class="rel-ai" id="relAiOut" hidden></div>';
        $("relAiBtn").addEventListener("click", explainAI);
    }

    async function explainAI() {
        const out = $("relAiOut"), btn = $("relAiBtn"); if (!out) return;
        out.hidden = false; out.textContent = tx("ai_wait"); btn.disabled = true;
        const sel = R.sel;
        try {
            const res = await fetch("/api/reliability-explain", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ lat: R.lat, lon: R.lon, day: sel, language: lang(), location: R.name }) });
            const j = await res.json();
            if (!res.ok) throw new Error(j.error);
            if (sel === R.sel) out.textContent = j.explanation;
        } catch (_) { out.textContent = tx("ai_fail"); }
        btn.disabled = false;
    }

    function select(i) {
        if (!R.data || i === R.sel) return;
        R.sel = i;
        qa("#relDays .rel-day").forEach((b) => b.classList.toggle("on", Number(b.dataset.i) === i));
        renderDetail();
        const sl = $("relMapDay"); if (sl && R.mapOn) { sl.value = i; paintMap(); }
    }

    function renderCard(c) {
        const el = $("relCardBody"); if (!el || !c) return;
        const trained = c.source === "trained";
        let html = '<div class="rel-kv"><span>' + esc(tx("m_src")) + '</span><span><i class="rel-pill ' + (trained ? "trained" : "prior") + '">' + esc(trained ? tx("m_trained") : tx("m_prior")) + "</i></span>";
        if (trained && c.auc != null) {
            html += "<span>" + esc(tx("m_auc")) + "</span><span>" + c.auc + "</span>" +
                "<span>" + esc(tx("m_base")) + "</span><span>" + c.auc_baseline + "</span>" +
                "<span>" + esc(tx("m_prec")) + " / " + esc(tx("m_rec")) + "</span><span>" + Math.round((c.precision || 0) * 100) + "% / " + Math.round((c.recall || 0) * 100) + "%</span>" +
                "<span>" + esc(tx("m_data")) + "</span><span>" + ((c.n_train || 0) + (c.n_test || 0)) + "</span>" +
                "<span>" + esc(tx("m_cities")) + "</span><span>" + (c.cities || "–") + "</span>" +
                "<span>" + esc(tx("m_when")) + "</span><span>" + esc((c.trained_at || "").slice(0, 10)) + "</span>";
        }
        html += "</div>";
        if (!trained) html += '<p class="rel-muted">' + esc(tx("m_prior_note")) + "</p>";
        html += '<p class="rel-muted" style="margin-top:8px">' + esc(fill(tx("m_def"), { t: c.definition.tmax_c, r: c.definition.rain_mm, g: c.definition.gust_kmh })) + "</p>";
        el.innerHTML = html;
    }

    /* ---------------------------------------------------------------- verification */
    async function loadVerify(token) {
        const el = $("relVerifyBody"); if (!el) return;
        el.innerHTML = esc(tx("loading"));
        if (R.vchart) { R.vchart.destroy(); R.vchart = null; }
        try {
            const res = await fetch("/api/reliability-verify?lat=" + R.lat + "&lon=" + R.lon);
            const j = await res.json();
            if (token !== R.token) return;
            if (!res.ok) throw new Error(j.error);
            const n = j.leads.length ? j.leads[0].n : 0;
            let html = '<p class="rel-muted" style="margin-bottom:10px">' + esc(fill(tx("v_intro"), { n: "1–7", a: j.start, b: j.end })) + "</p>" +
                '<div class="rel-table-wrap"><table class="rel-table"><thead><tr><th>' + esc(tx("v_lead")) + "</th><th>" + esc(tx("v_bust")) + "</th><th>" + esc(tx("v_mae")) + "</th><th>" + esc(tx("v_hit")) + "</th></tr></thead><tbody>" +
                j.leads.map((r) => "<tr><td>" + r.lead + " " + esc(tx("v_days_s")) + "</td><td>" + r.bust_rate + "%</td><td>±" + r.tmax_mae + "°C</td><td>" + r.wet_dry_hit + "%</td></tr>").join("") +
                "</tbody></table></div>" +
                '<p class="rel-note">' + n + " " + esc(tx("v_n")) + '</p><div class="small-label" style="margin-top:10px">' + esc(tx("v_chart")) + '</div><div class="rel-vchart"><canvas id="relVerifyChart"></canvas></div>';
            el.innerHTML = html;
            drawVerifyChart(j.series);
        } catch (_) {
            if (token === R.token) el.textContent = tx("v_none");
        }
    }

    function drawVerifyChart(series) {
        const cv = $("relVerifyChart"); if (!cv || !window.Chart || !series || !series.length) return;
        const c = chartColors();
        R.vchart = new Chart(cv, {
            type: "line",
            data: { labels: series.map((s) => s.date.slice(5)), datasets: [
                { label: tx("ds_fc"), data: series.map((s) => s.fc), borderColor: "#8b5cf6", backgroundColor: "#8b5cf6", tension: .3, borderWidth: 2, pointRadius: 0 },
                { label: tx("ds_obs"), data: series.map((s) => s.obs), borderColor: "#38d996", backgroundColor: "#38d996", tension: .3, borderWidth: 2, pointRadius: 0 },
            ] },
            options: { responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 600 }, interaction: { mode: "index", intersect: false },
                plugins: { legend: { labels: { color: c.tick, boxWidth: 8, usePointStyle: true, font: { size: 11 } } } },
                scales: { x: { ticks: { color: c.tick, maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } }, y: { ticks: { color: c.tick }, grid: { color: c.grid } } } },
        });
    }

    /* ---------------------------------------------------------------- map layer (lives inside the existing weather map) */
    const riskColor = (p) => (p < 30 ? "#38d996" : p < 50 ? "#fbbf24" : p < 70 ? "#fb923c" : "#f87171");

    async function loadMapLayer() {
        if (!R.map || R.lat == null) return;
        const key = R.lat.toFixed(1) + "," + R.lon.toFixed(1);
        if (R.grid && R.gridKey === key) { paintMap(); return; }
        try {
            const res = await fetch("/api/reliability-grid?lat=" + R.lat + "&lon=" + R.lon);
            const j = await res.json();
            if (!res.ok) throw new Error(j.error);
            if (!R.mapOn) return;
            R.grid = j; R.gridKey = key;
            const sl = $("relMapDay"); sl.max = Math.max(0, j.dates.length - 1); sl.value = Math.min(R.sel, sl.max);
            paintMap();
        } catch (_) {
            const lg = $("mapLegend"); if (lg && R.mapOn) lg.insertAdjacentHTML("beforeend", '<div class="note">' + esc(tx("map_fail")) + "</div>");
        }
    }

    function paintMap() {
        if (!R.map || !R.grid || !window.L) return;
        const day = Number($("relMapDay").value) || 0;
        if (R.layer) { R.map.removeLayer(R.layer); R.layer = null; }
        const half = (R.grid.step || 0.5) * 55000;           // ~55 km per 0.5 degree
        R.layer = L.layerGroup(R.grid.points.map((p) => {
            const risk = p.risk[day] == null ? 0 : p.risk[day];
            return L.circle([p.lat, p.lon], { radius: half, stroke: false, fillColor: riskColor(risk), fillOpacity: .42, pane: "overlayPane2", interactive: true })
                .bindTooltip(esc(tx("map_tip")) + " " + risk + "% · " + (100 - risk) + "% " + esc(tx("conf")), { className: "rel-map-tip", direction: "top" });
        })).addTo(R.map);
        const date = R.grid.dates[day] || "";
        $("relMapDate").textContent = date.slice(5);
    }

    /* ---------------------------------------------------------------- public API used by features.js */
    window.WGRel = {
        mapLayer: function (map) {
            R.map = map; R.mapOn = true;
            const bar = $("relMapBar"); if (bar) bar.hidden = false;
            loadMapLayer();
        },
        clearMap: function () {
            R.mapOn = false;
            if (R.layer && R.map) { R.map.removeLayer(R.layer); }
            R.layer = null;
            const bar = $("relMapBar"); if (bar) bar.hidden = true;
        },
        /* Adds reliability alerts to the existing Smart Alerts list (called after every alerts render). */
        mergeAlerts: function () {
            const list = $("alertsList"); if (!list) return;
            qa(".rel-alert", list).forEach((n) => n.remove());
            if (!R.alerts.length) return;
            const base = list.children.length;
            const html = R.alerts.map((a, i) =>
                '<div class="alert rel-alert ' + esc(a.level) + '" style="--i:' + (base + i) + '"><div class="ai">🎯</div><div><h4>' + esc(a.title) +
                ' <span class="tag">' + esc(tx("alert_tag")) + "</span></h4><p>" + esc(a.message) + "</p></div></div>").join("");
            list.insertAdjacentHTML("beforeend", html);
            const link = document.querySelector('.feature-nav a[href="#alertsSection"]');
            if (link) {
                const real = qa(".alert", list).filter((n) => !n.classList.contains("ok")).length;
                link.dataset.count = real;
            }
        },
    };

    /* ---------------------------------------------------------------- wiring */
    function wire() {
        applyStatic();
        const days = $("relDays");
        if (days) days.addEventListener("click", (e) => { const b = e.target.closest(".rel-day"); if (b) select(Number(b.dataset.i)); });
        const tabs = $("relTabs");
        if (tabs) tabs.addEventListener("click", (e) => {
            const b = e.target.closest("button"); if (!b) return;
            R.view = b.dataset.v; qa("#relTabs button").forEach((x) => x.classList.toggle("on", x === b)); renderChart();
        });
        const sl = $("relMapDay");
        if (sl) sl.addEventListener("input", () => { paintMap(); const k = Number(sl.value); if (R.data && k !== R.sel) select(k); });
        const ls = $("languageSelect");
        if (ls) ls.addEventListener("change", () => setTimeout(() => { applyStatic(); if (R.lat != null) load(); }, 80));
        setState("empty");
    }

    window.addEventListener("wg:weather", (e) => {
        const d = e.detail || {};
        const lat = Number(d.latitude), lon = Number(d.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        R.lat = lat; R.lon = lon; R.name = d.city || ""; R.data = null; R.alerts = []; R.grid = null; R.gridKey = "";
        load();
    });

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire); else wire();
})();
