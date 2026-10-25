/* WeatherGPT - login animation.
   Part 1: "how weather helps every field" - farming, fishing, travel, logistics, construction, energy,
           health, sports & events, water & dams, safety.
   Part 2: the WeatherGPT logo animation.   Click / Esc / "Skip" closes it. */
(function () {
    "use strict";
    var fromGoogle = /(^|[?&])welcome=1(&|$)/.test(location.search), flagged = false;
    try { flagged = sessionStorage.getItem("wg_splash") === "1"; sessionStorage.removeItem("wg_splash"); } catch (e) { /* ignore */ }
    if (!fromGoogle && !flagged) return;
    try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) { /* ignore */ }

    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var root = document.documentElement;
    var el = document.createElement("div");
    el.id = "wgSplash"; el.setAttribute("role", "img"); el.setAttribute("aria-label", "WeatherGPT: weather helps farming, fishing, travel, logistics, construction, energy, health, sports, water and safety");
    var cv = document.createElement("canvas");
    var skip = document.createElement("button");
    skip.type = "button"; skip.className = "wgs-skip"; skip.textContent = "Skip ›";
    el.appendChild(cv); el.appendChild(skip);
    root.classList.add("wg-splashing"); root.appendChild(el);

    var ctx = cv.getContext("2d"), W = 0, H = 0, S = 0, dpr = 1, raf = 0, done = false, t0 = 0;
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        W = window.innerWidth; H = window.innerHeight; S = Math.min(W, H);
        cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
        cv.style.width = W + "px"; cv.style.height = H + "px";
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    window.addEventListener("resize", resize); resize();

    /*@@SHARED-START@@*/
    var FIELDS = [
        { icon: "\ud83c\udf3e", name: "Farming", line: "Plan irrigation, spraying and harvest", fx: "farm" },
        { icon: "\ud83c\udfa3", name: "Fishing", line: "Know the wind, waves and storms before you sail", fx: "fish" },
        { icon: "\u2708\ufe0f", name: "Travel & flights", line: "Pick the safest, smoothest time to go", fx: "travel" },
        { icon: "\ud83d\ude9a", name: "Logistics", line: "Route deliveries around rain, fog and storms", fx: "logistics", isNew: true },
        { icon: "\ud83c\udfd7\ufe0f", name: "Construction", line: "Schedule cranes, concrete and roofing safely", fx: "construction", isNew: true },
        { icon: "\u26a1", name: "Energy", line: "Forecast wind and sun to plan power", fx: "energy" },
        { icon: "\u2764\ufe0f", name: "Health", line: "Heat, UV and air-comfort alerts", fx: "health" },
        { icon: "\ud83c\udfcf", name: "Sports & events", line: "Plan matches, weddings and festivals", fx: "sports", isNew: true },
        { icon: "\ud83d\udca7", name: "Water & dams", line: "Track rainfall, reservoirs and flood risk", fx: "water", isNew: true },
        { icon: "\ud83d\udea8", name: "Safety", line: "Early storm and flood warnings save lives", fx: "safety" }
    ];
    /* MOTION: speed of the ambient movement inside each scene (rain, waves, turbines, sun rays, clouds, wheels).
       1 = the original speed, lower = slower. The scenes and the total time stay the same. PER = seconds per field. */
    var MOTION = 0.5;
    var INTRO = 0.4, PER = 0.78, LOGO0 = INTRO + FIELDS.length * PER, TOTAL = reduce ? 1.6 : LOGO0 + 2.6;

    /* ---------- helpers ---------- */
    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
    function ease(v) { v = clamp(v, 0, 1); return v * v * (3 - 2 * v); }
    function seg(t, a, b) { return ease((t - a) / (b - a)); }
    function bg(c1, c2) { var g = ctx.createLinearGradient(0, 0, 0, H); g.addColorStop(0, c1); g.addColorStop(1, c2); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H); }
    function circle(x, y, r, fill) { ctx.fillStyle = fill; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill(); }
    function cloud(x, y, s, fill, a) {
        ctx.globalAlpha = a == null ? 1 : a; ctx.fillStyle = fill;
        [[0, 0, 1], [0.9, -0.25, 0.8], [-0.9, -0.1, 0.75], [0.35, -0.55, 0.85], [1.6, 0.1, 0.6], [-1.5, 0.15, 0.55]].forEach(function (p) { ctx.beginPath(); ctx.arc(x + p[0] * s, y + p[1] * s, p[2] * s, 0, 6.2832); ctx.fill(); });
        ctx.globalAlpha = 1;
    }
    function sun(x, y, r, t, rays) {
        var g = ctx.createRadialGradient(x, y, 0, x, y, r * 3.6); g.addColorStop(0, "rgba(255,230,140,.75)"); g.addColorStop(1, "rgba(255,170,60,0)");
        ctx.fillStyle = g; ctx.fillRect(x - r * 4, y - r * 4, r * 8, r * 8);
        if (rays) { ctx.strokeStyle = "#ffd45c"; ctx.lineWidth = Math.max(3, r * 0.14); ctx.lineCap = "round"; ctx.beginPath(); for (var i = 0; i < 12; i++) { var a = i * 0.5236 + t * 0.6; ctx.moveTo(x + Math.cos(a) * r * 1.3, y + Math.sin(a) * r * 1.3); ctx.lineTo(x + Math.cos(a) * r * 1.75, y + Math.sin(a) * r * 1.75); } ctx.stroke(); }
        circle(x, y, r, "#ffd45c");
    }
    function rain(n, t, x0, x1, y0, y1, a) {
        ctx.strokeStyle = "rgba(200,230,255," + a + ")"; ctx.lineWidth = 1.6; ctx.beginPath();
        for (var i = 0; i < n; i++) { var f = (t * (0.9 + (i % 5) * 0.12) + i * 0.173) % 1, x = x0 + ((i * 0.6180339) % 1) * (x1 - x0), y = y0 + f * (y1 - y0); ctx.moveTo(x, y); ctx.lineTo(x - 4, y + S * 0.025); }
        ctx.stroke();
    }
    function txt(s, x, y, size, weight, fill, align) { ctx.font = weight + " " + Math.round(size) + "px Segoe UI, system-ui, sans-serif"; ctx.fillStyle = fill; ctx.textAlign = align || "center"; ctx.fillText(s, x, y); }
    function emoji(s, x, y, size, rot, a) {
        ctx.save(); ctx.globalAlpha = a == null ? 1 : a; ctx.translate(x, y); if (rot) ctx.rotate(rot);
        ctx.font = Math.round(size) + "px 'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(s, 0, 0); ctx.restore();
    }

    function pill(s, cx, cy, size, fill, fg, a) {
        ctx.save(); ctx.globalAlpha = a; ctx.font = "700 " + Math.round(size) + "px Segoe UI, system-ui, sans-serif";
        var w = ctx.measureText(s).width + size * 1.6, h = size * 1.95;
        ctx.fillStyle = fill; ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(cx - w / 2, cy - h / 2, w, h, h / 2); else ctx.rect(cx - w / 2, cy - h / 2, w, h); ctx.fill();
        ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(s, cx, cy + 1); ctx.restore();
    }

    /* ---------- the field scenes: u = 0..1 progress inside the scene ---------- */
    function farm(u, t) {
        bg("#7ec8f5", "#e2f4ff"); sun(W * 0.82, H * 0.18, S * 0.06, t, true);
        cloud(W * 0.3, H * 0.2, S * 0.09, "#eef3f8"); rain(36, t, W * 0.16, W * 0.44, H * 0.26, H * 0.72, 0.65);
        ctx.fillStyle = "#6b4a2b"; ctx.fillRect(0, H * 0.7, W, H * 0.3);
        var g = ease(u * 1.25);
        for (var r = 0; r < 3; r++) for (var j = 0; j < 8; j++) {
            var x = W * (0.08 + 0.12 * j + (r % 2) * 0.05), y = H * (0.76 + r * 0.075), h = S * (0.02 + 0.075 * g) * (1 + r * 0.15);
            ctx.strokeStyle = "#3f9a3a"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - h); ctx.stroke();
            ctx.fillStyle = "#58b948"; ctx.beginPath(); ctx.ellipse(x - h * 0.28, y - h * 0.55, h * 0.3, h * 0.12, -0.5, 0, 6.2832); ctx.ellipse(x + h * 0.28, y - h * 0.4, h * 0.3, h * 0.12, 0.5, 0, 6.2832); ctx.fill();
            if (u > 0.6) circle(x, y - h, S * 0.012 * seg(u, 0.6, 0.9), "#f2c744");
        }
    }
    function fish(u, t) {
        bg("#4a86c8", "#bfe3ff"); sun(W * 0.2, H * 0.2, S * 0.05, t, false);
        var y0 = H * 0.58; cloud(W * 0.84, H * 0.2, S * 0.07, "#4a5568");
        if (Math.sin(t * 9) > 0.8) { ctx.strokeStyle = "#fff6b0"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(W * 0.84, H * 0.25); ctx.lineTo(W * 0.82, H * 0.32); ctx.lineTo(W * 0.85, H * 0.32); ctx.lineTo(W * 0.83, H * 0.4); ctx.stroke(); }
        ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 2; ctx.beginPath();
        for (var k = 0; k < 5; k++) { var yy = H * (0.3 + k * 0.05), xx = ((t * 0.5 + k * 0.23) % 1.2 - 0.1) * W; ctx.moveTo(xx, yy); ctx.lineTo(xx + S * 0.12, yy); }
        ctx.stroke();
        var wave = function (x, ph, amp) { return y0 + Math.sin(x * 0.012 + t * 2 + ph) * amp * S * 0.012 + Math.sin(x * 0.006 - t * 1.3 + ph) * amp * S * 0.01; };
        var bx = W * (0.25 + 0.5 * u), by = wave(bx, 0, 1) - S * 0.02, tilt = Math.atan2(wave(bx + 8, 0, 1) - wave(bx - 8, 0, 1), 16);
        ctx.save(); ctx.translate(bx, by); ctx.rotate(tilt); var b = S * 0.09;
        ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.moveTo(0, -b * 1.5); ctx.lineTo(b * 0.75, -b * 0.12); ctx.lineTo(0, -b * 0.12); ctx.fill();
        ctx.fillStyle = "#e8505b"; ctx.beginPath(); ctx.moveTo(-b, 0); ctx.lineTo(b, 0); ctx.lineTo(b * 0.72, b * 0.38); ctx.lineTo(-b * 0.72, b * 0.38); ctx.fill(); ctx.restore();
        [["rgba(30,90,160,.8)", 0, 2], ["rgba(20,70,140,.9)", 1.7, 2.6]].forEach(function (L, n) {
            ctx.fillStyle = L[0]; ctx.beginPath(); ctx.moveTo(0, H);
            for (var x = 0; x <= W; x += 8) ctx.lineTo(x, wave(x, L[1], L[2]) + n * S * 0.04); ctx.lineTo(W, H); ctx.fill();
        });
        if (u > 0.45) { var a = seg(u, 0.45, 0.7); ctx.globalAlpha = a; circle(W * 0.5, H * 0.16, S * 0.055, "rgba(56,217,150,.95)"); ctx.strokeStyle = "#06322a"; ctx.lineWidth = 5; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(W * 0.5 - S * 0.025, H * 0.16); ctx.lineTo(W * 0.5 - S * 0.005, H * 0.16 + S * 0.02); ctx.lineTo(W * 0.5 + S * 0.03, H * 0.16 - S * 0.02); ctx.stroke(); txt("Safe window", W * 0.5, H * 0.16 + S * 0.09, S * 0.03, "700", "#eafff6"); ctx.globalAlpha = 1; }
    }
    function travel(u, t) {
        bg("#3f86df", "#d6ecff"); sun(W * 0.86, H * 0.16, S * 0.05, t, false);
        [0.2, 0.55, 0.8].forEach(function (x, i) { cloud(((x + t * (0.02 + i * 0.01)) % 1.3 - 0.15) * W, H * (0.25 + i * 0.2), S * (0.07 + i * 0.01), "#ffffff", 0.9); });
        var P0 = [W * 0.12, H * 0.74], P1 = [W * 0.5, H * 0.08], P2 = [W * 0.88, H * 0.42], p = ease(u);
        ctx.setLineDash([10, 10]); ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(P0[0], P0[1]); ctx.quadraticCurveTo(P1[0], P1[1], P2[0], P2[1]); ctx.stroke(); ctx.setLineDash([]);
        circle(P0[0], P0[1], S * 0.014, "#fff"); circle(P2[0], P2[1], S * 0.014, "#ffc83d");
        var x = (1 - p) * (1 - p) * P0[0] + 2 * (1 - p) * p * P1[0] + p * p * P2[0], y = (1 - p) * (1 - p) * P0[1] + 2 * (1 - p) * p * P1[1] + p * p * P2[1];
        var tx = 2 * (1 - p) * (P1[0] - P0[0]) + 2 * p * (P2[0] - P1[0]), ty = 2 * (1 - p) * (P1[1] - P0[1]) + 2 * p * (P2[1] - P1[1]);
        emoji("✈️", x, y, S * 0.1, Math.atan2(ty, tx) - Math.PI / 4);
        if (u > 0.5) { ctx.globalAlpha = seg(u, 0.5, 0.75); txt("Clear skies · smooth flight", W * 0.5, H * 0.9 - S * 0.12, S * 0.03, "700", "#0b2a55"); ctx.globalAlpha = 1; }
    }
    function health(u, t) {
        bg("#ff9a4a", "#ffe5a8"); sun(W * 0.32, H * 0.42, S * 0.11, t, true);
        var x = W * 0.7, top = H * 0.2, bot = H * 0.66, w = S * 0.05, fill = 0.25 + 0.7 * ease(u);
        ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.beginPath(); ctx.moveTo(x - w, top + w); ctx.arc(x, top + w, w, Math.PI, 0); ctx.lineTo(x + w, bot); ctx.lineTo(x - w, bot); ctx.fill();
        circle(x, bot + w * 0.8, w * 1.7, "rgba(255,255,255,.9)"); circle(x, bot + w * 0.8, w * 1.25, "#e53935");
        ctx.fillStyle = "#e53935"; ctx.fillRect(x - w * 0.45, bot - (bot - top - w) * fill, w * 0.9, (bot - top - w) * fill + w * 0.8);
        txt(Math.round(28 + 12 * ease(u)) + "°C", x + w * 2.2, top + S * 0.05, S * 0.05, "800", "#7a1d12", "left");
        var pulse = 1 + 0.08 * Math.sin(t * 6); ctx.globalAlpha = seg(u, 0.3, 0.6);
        ctx.fillStyle = "#7a1d12"; ctx.beginPath(); ctx.roundRect ? ctx.roundRect(W * 0.12, H * 0.74, S * 0.2 * pulse, S * 0.075, 14) : ctx.rect(W * 0.12, H * 0.74, S * 0.2, S * 0.075); ctx.fill();
        txt("UV " + Math.round(4 + 6 * ease(u)), W * 0.12 + S * 0.1 * pulse, H * 0.74 + S * 0.052, S * 0.04, "800", "#fff"); emoji("💧", W * 0.5, H * 0.78, S * 0.08, 0, 0.5 + 0.5 * Math.sin(t * 5) * 0.5 + 0.5); ctx.globalAlpha = 1;
    }
    function energy(u, t) {
        bg("#2d63ae", "#c8e8ff"); sun(W * 0.84, H * 0.17, S * 0.06, t, true);
        ctx.fillStyle = "#2e6b3a"; ctx.beginPath(); ctx.moveTo(0, H); ctx.lineTo(0, H * 0.78); ctx.quadraticCurveTo(W * 0.3, H * 0.62, W * 0.6, H * 0.8); ctx.quadraticCurveTo(W * 0.85, H * 0.7, W, H * 0.78); ctx.lineTo(W, H); ctx.fill();
        [[0.28, 0.72, 1], [0.5, 0.78, 0.8], [0.7, 0.74, 0.9]].forEach(function (T, i) {
            var x = W * T[0], y = H * T[1], h = S * 0.26 * T[2], a0 = t * (2.4 + i * 0.5);
            ctx.strokeStyle = "#f2f6fa"; ctx.lineWidth = 5; ctx.lineCap = "round"; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x, y - h); ctx.stroke();
            for (var b = 0; b < 3; b++) { var a = a0 + b * 2.0944; ctx.beginPath(); ctx.moveTo(x, y - h); ctx.lineTo(x + Math.cos(a) * h * 0.55, y - h + Math.sin(a) * h * 0.55); ctx.stroke(); }
            circle(x, y - h, 5, "#d0d8e0");
        });
        ctx.save(); ctx.translate(W * 0.1, H * 0.86); ctx.transform(1, 0, -0.5, 1, 0, 0); ctx.fillStyle = "#1a3d7a"; ctx.fillRect(0, -S * 0.1, S * 0.2, S * 0.1);
        ctx.strokeStyle = "rgba(255,255,255,.5)"; ctx.lineWidth = 1; ctx.beginPath(); for (var k = 1; k < 4; k++) { ctx.moveTo(k * S * 0.05, -S * 0.1); ctx.lineTo(k * S * 0.05, 0); } ctx.moveTo(0, -S * 0.05); ctx.lineTo(S * 0.2, -S * 0.05); ctx.stroke(); ctx.restore();
        emoji("⚡", W * 0.5, H * 0.3, S * (0.09 + 0.012 * Math.sin(t * 7)), 0, seg(u, 0.1, 0.4));
        txt(Math.round(40 + 55 * ease(u)) + "% clean power", W * 0.5, H * 0.3 + S * 0.1, S * 0.034, "800", "#08284f");
    }
    function safety(u, t) {
        bg("#141a28", "#3b4559"); var cx = W * 0.5, cy = H * 0.4;
        ctx.strokeStyle = "rgba(220,235,255,.8)"; ctx.lineWidth = 3; ctx.beginPath();
        for (var k = 0; k < 90; k++) { var a = k * 0.28 + t * 3.2, r = k * S * 0.0046; ctx.lineTo(cx + Math.cos(a) * r * 1.5, cy + Math.sin(a) * r * 0.55); } ctx.stroke();
        circle(cx, cy, S * 0.02, "rgba(0,0,0,.5)"); rain(60, t, 0, W, 0, H, 0.5);
        if (Math.sin(t * 8) > 0.75) { ctx.fillStyle = "rgba(220,235,255,.18)"; ctx.fillRect(0, 0, W, H); }
        var p = 1 + 0.1 * Math.sin(t * 8), s = S * 0.09 * p * seg(u, 0.1, 0.4), ax = W * 0.5, ay = H * 0.72;
        ctx.fillStyle = "#ffc83d"; ctx.beginPath(); ctx.moveTo(ax, ay - s); ctx.lineTo(ax + s * 1.05, ay + s * 0.8); ctx.lineTo(ax - s * 1.05, ay + s * 0.8); ctx.closePath(); ctx.fill();
        txt("!", ax, ay + s * 0.55, s * 1.2, "900", "#3a1b00"); ctx.globalAlpha = seg(u, 0.4, 0.7); txt("Storm alert sent in time", W * 0.5, H * 0.9 - S * 0.12, S * 0.032, "700", "#ffe9b0"); ctx.globalAlpha = 1;
    }

    /* ---- added fields: logistics, construction, sports & events, water & dams ---- */
    function logistics(u, t) {
        var clear = ease(u * 1.15), ry = H * 0.56, rh = H * 0.19, s = S * 0.075;
        bg("#8aa6c3", "#e7eef6"); sun(W * 0.85, H * 0.17, S * 0.045, t, false);
        cloud(W * 0.24, H * 0.2, S * 0.085, "#98a6b6", 1 - clear * 0.6);
        rain(30, t, W * 0.04, W * 0.52, H * 0.27, ry, 0.55 * (1 - clear));
        ctx.fillStyle = "#6c8f6a"; ctx.beginPath(); ctx.moveTo(0, ry); ctx.quadraticCurveTo(W * 0.25, H * 0.34, W * 0.5, H * 0.5); ctx.quadraticCurveTo(W * 0.78, H * 0.36, W, H * 0.5); ctx.lineTo(W, ry); ctx.fill();
        ctx.fillStyle = "#58764f"; ctx.fillRect(0, ry + rh, W, H);
        ctx.fillStyle = "#3b4048"; ctx.fillRect(0, ry, W, rh);
        ctx.fillStyle = "#e9eef4"; var off = (t * S * 0.45) % (S * 0.16);
        for (var x = -off; x < W; x += S * 0.16) ctx.fillRect(x, ry + rh * 0.5, S * 0.08, 4);
        var tx = W * (0.2 + 0.52 * ease(u)), ty = ry + rh * 0.78 + Math.sin(t * 14) * 1.2;
        ctx.fillStyle = "#f5f7fa"; ctx.fillRect(tx - s * 2.7, ty - s * 1.7, s * 2.8, s * 1.7);
        ctx.fillStyle = "#e8505b"; ctx.fillRect(tx - s * 2.7, ty - s * 0.75, s * 2.8, s * 0.26);
        ctx.fillStyle = "#2f6fe0"; ctx.beginPath(); ctx.moveTo(tx + s * 0.18, ty - s * 1.2); ctx.lineTo(tx + s * 0.18, ty); ctx.lineTo(tx + s * 1.25, ty); ctx.lineTo(tx + s * 1.25, ty - s * 0.5); ctx.lineTo(tx + s * 0.85, ty - s * 1.2); ctx.fill();
        ctx.fillStyle = "#cfe8ff"; ctx.beginPath(); ctx.moveTo(tx + s * 0.4, ty - s * 1.0); ctx.lineTo(tx + s * 0.4, ty - s * 0.5); ctx.lineTo(tx + s * 1.05, ty - s * 0.5); ctx.lineTo(tx + s * 0.78, ty - s * 1.0); ctx.fill();
        [-1.9, -0.9, 0.75].forEach(function (wx) {
            var cx2 = tx + wx * s, cy2 = ty + s * 0.02, a = t * 9;
            circle(cx2, cy2, s * 0.3, "#15181d"); circle(cx2, cy2, s * 0.13, "#9aa4b0");
            ctx.strokeStyle = "#9aa4b0"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(cx2 + Math.cos(a) * s * 0.26, cy2 + Math.sin(a) * s * 0.26); ctx.lineTo(cx2 - Math.cos(a) * s * 0.26, cy2 - Math.sin(a) * s * 0.26); ctx.stroke();
        });
        for (var i = 0; i < 4; i++) {
            var fx = ((t * 0.05 + i * 0.31) % 1.5 - 0.25) * W;
            ctx.globalAlpha = 0.55 * (1 - clear) * (0.7 + 0.3 * Math.sin(t * 1.3 + i)); ctx.fillStyle = "#f2f5f9";
            ctx.beginPath(); ctx.ellipse(fx, H * (0.4 + i * 0.1), W * 0.34, S * 0.05, 0, 0, 6.2832); ctx.fill();
        }
        ctx.globalAlpha = 1;
        if (u > 0.45) pill("Route clear · arriving on time", W * 0.5, H * 0.9 - S * 0.13, S * 0.03, "rgba(56,217,150,.96)", "#04301f", seg(u, 0.45, 0.7));
    }
    function construction(u, t) {
        var gy = H * 0.78, fh = S * 0.07, bx = W * 0.12, bw = W * 0.3, floors = 1 + Math.floor(4 * ease(u * 1.1));
        bg("#86c5f2", "#f6ecd2"); sun(W * 0.13, H * 0.2, S * 0.05, t, true); cloud(W * 0.5, H * 0.17, S * 0.07, "#f3f6fa", 0.9);
        ctx.fillStyle = "#9a9588"; ctx.fillRect(0, gy, W, H - gy);
        for (var f = 0; f < floors; f++) {
            var fy = gy - (f + 1) * fh, top = f === floors - 1 && u < 0.95;
            if (top) {
                ctx.strokeStyle = "#d9772b"; ctx.lineWidth = 3; ctx.strokeRect(bx, fy, bw, fh);
                ctx.beginPath(); ctx.moveTo(bx, fy + fh); ctx.lineTo(bx + bw / 2, fy); ctx.lineTo(bx + bw, fy + fh); ctx.stroke();
            } else {
                ctx.fillStyle = "#cfd5dc"; ctx.fillRect(bx, fy, bw, fh);
                ctx.fillStyle = "#3d5a80"; for (var w = 0; w < 4; w++) ctx.fillRect(bx + bw * (0.08 + w * 0.23), fy + fh * 0.25, bw * 0.14, fh * 0.5);
            }
        }
        var mx = W * 0.66, jy = H * 0.22, m = S * 0.016;
        ctx.strokeStyle = "#f2b134"; ctx.lineWidth = 4; ctx.beginPath();
        ctx.moveTo(mx - m, gy); ctx.lineTo(mx - m, jy); ctx.moveTo(mx + m, gy); ctx.lineTo(mx + m, jy);
        for (var z = 0; z < 9; z++) { var y1 = gy - (gy - jy) * z / 9, y2 = gy - (gy - jy) * (z + 1) / 9; ctx.moveTo(mx - m, z % 2 ? y1 : y2); ctx.lineTo(mx + m, z % 2 ? y2 : y1); }
        ctx.stroke();
        ctx.lineWidth = 7; ctx.beginPath(); ctx.moveTo(W * 0.3, jy); ctx.lineTo(W * 0.82, jy); ctx.stroke();
        ctx.fillStyle = "#555d68"; ctx.fillRect(W * 0.76, jy, S * 0.07, S * 0.06); ctx.fillStyle = "#f2b134"; ctx.fillRect(mx - m * 1.6, jy - S * 0.04, m * 3.2, S * 0.04);
        var p = ease(clamp(u * 1.4, 0, 1)), cx = W * 0.4 + Math.sin(t * 3) * S * 0.006 * (0.4 + p), beamY = gy - S * 0.045 - p * (gy - H * 0.38 - S * 0.045);
        ctx.strokeStyle = "#2b2f36"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(W * 0.4, jy); ctx.lineTo(cx, beamY - S * 0.03); ctx.stroke();
        ctx.fillStyle = "#d9772b"; ctx.fillRect(cx - S * 0.075, beamY, S * 0.15, S * 0.022); ctx.fillStyle = "#2b2f36"; ctx.fillRect(cx - 4, beamY - S * 0.035, 8, S * 0.035);
        var fyTop = jy - S * 0.07; ctx.strokeStyle = "#555d68"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(mx, jy - S * 0.04); ctx.lineTo(mx, fyTop); ctx.stroke();
        ctx.fillStyle = "#e8505b"; ctx.beginPath(); ctx.moveTo(mx, fyTop); ctx.lineTo(mx + S * 0.055, fyTop + S * 0.012 + Math.sin(t * 7) * S * 0.008); ctx.lineTo(mx, fyTop + S * 0.026); ctx.fill();
        if (u > 0.5) pill("Wind 12 km/h · safe to lift", W * 0.5, H * 0.9 - S * 0.13, S * 0.03, "rgba(56,217,150,.96)", "#04301f", seg(u, 0.5, 0.75));
    }
    function sports(u, t) {
        var clear = ease(u * 1.1), crowd = ["#ffd45c", "#ff7a7a", "#7dd3fc", "#c4b5fd", "#ffffff"];
        bg("#79c0f7", "#eaf6ff");
        ctx.globalAlpha = clear; sun(W * 0.16, H * 0.3, S * 0.05, t, true); ctx.globalAlpha = 1;
        ctx.fillStyle = "#27324d"; ctx.fillRect(0, H * 0.5, W, H * 0.19);
        for (var r = 0; r < 3; r++) for (var c = 0; c < 28; c++) circle(W * (0.05 + c * 0.0335), H * (0.545 + r * 0.04) - Math.max(0, Math.sin(t * 6 + c * 1.7 + r)) * 3 * clear, S * 0.0085, crowd[(c * 7 + r * 3) % 5]);
        ctx.fillStyle = "#3f9e52"; ctx.fillRect(0, H * 0.69, W, H * 0.31);
        ctx.fillStyle = "#4cb061"; for (var k = 0; k < 8; k++) if (k % 2 === 0) ctx.fillRect(W * k / 8, H * 0.69, W / 8, H * 0.31);
        [0.08, 0.92].forEach(function (lx) {
            ctx.strokeStyle = "#cfd6df"; ctx.lineWidth = 4; ctx.beginPath(); ctx.moveTo(W * lx, H * 0.5); ctx.lineTo(W * lx, H * 0.3); ctx.stroke();
            ctx.fillStyle = "#e9eef5"; ctx.fillRect(W * lx - S * 0.035, H * 0.27, S * 0.07, S * 0.03);
            var g = ctx.createRadialGradient(W * lx, H * 0.285, 0, W * lx, H * 0.285, S * 0.16); g.addColorStop(0, "rgba(255,244,190," + (0.55 * (1 - clear * 0.6)) + ")"); g.addColorStop(1, "rgba(255,244,190,0)"); ctx.fillStyle = g; ctx.fillRect(W * lx - S * 0.2, H * 0.285 - S * 0.2, S * 0.4, S * 0.4);
        });
        var cxm = W * (0.35 + 0.85 * clear);
        if (cxm < W + S * 0.2) { cloud(cxm, H * 0.2, S * 0.1, "#6b7788"); rain(30, t, cxm - S * 0.22, cxm + S * 0.22, H * 0.27, H * 0.68, 0.6 * (1 - clear)); }
        var bx = W * (0.28 + 0.44 * ((t * 0.32) % 1)), bounce = Math.abs(Math.sin(t * 5)), by = H * 0.78 - bounce * S * 0.13, br = S * 0.024;
        ctx.fillStyle = "rgba(0,0,0,.22)"; ctx.beginPath(); ctx.ellipse(bx, H * 0.805, br * (1.4 - bounce * 0.5), br * 0.4, 0, 0, 6.2832); ctx.fill();
        circle(bx, by, br, "#c62828"); ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(bx, by, br * 0.7, -0.9 + t * 4, 0.9 + t * 4); ctx.stroke();
        if (u > 0.5) pill("Match on · dry from 4 PM", W * 0.5, H * 0.9 - S * 0.13 - H * 0.04, S * 0.03, "rgba(56,217,150,.96)", "#04301f", seg(u, 0.5, 0.75));
    }
    function water(u, t) {
        var e = ease(u), lvl = H * (0.67 - 0.2 * e), dam = W * 0.46;
        bg("#6d8cb0", "#d6e6f5"); cloud(W * 0.2, H * 0.16, S * 0.09, "#7b8ba0"); cloud(W * 0.42, H * 0.12, S * 0.07, "#8996ab");
        rain(40, t, W * 0.03, W * 0.48, H * 0.2, H * 0.6, 0.55);
        ctx.fillStyle = "#527a58"; ctx.beginPath(); ctx.moveTo(0, H * 0.62); ctx.quadraticCurveTo(W * 0.2, H * 0.38, W * 0.42, H * 0.5); ctx.lineTo(dam, H * 0.8); ctx.lineTo(0, H * 0.8); ctx.fill();
        ctx.fillStyle = "#6b9168"; ctx.beginPath(); ctx.moveTo(W * 0.56, H * 0.8); ctx.lineTo(W * 0.56, H * 0.56); ctx.quadraticCurveTo(W * 0.78, H * 0.4, W, H * 0.6); ctx.lineTo(W, H * 0.8); ctx.fill();
        var wg = ctx.createLinearGradient(0, lvl, 0, H); wg.addColorStop(0, "#4a93d4"); wg.addColorStop(1, "#1d4f91"); ctx.fillStyle = wg; ctx.beginPath(); ctx.moveTo(0, H); ctx.lineTo(0, lvl);
        for (var x = 0; x <= dam; x += 8) ctx.lineTo(x, lvl + Math.sin(x * 0.03 + t * 2) * S * 0.006);
        ctx.lineTo(dam, H); ctx.fill();
        ctx.fillStyle = "#4d93d6"; ctx.beginPath(); ctx.moveTo(W * 0.54, H * 0.8); ctx.lineTo(W, H * 0.8); ctx.lineTo(W, H); ctx.lineTo(W * 0.5, H); ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.55)"; ctx.lineWidth = 2; ctx.beginPath();
        for (var k = 0; k < 6; k++) { var fx = ((t * 0.35 + k * 0.19) % 0.55 + 0.52) * W, fy = H * (0.84 + (k % 3) * 0.05); ctx.moveTo(fx, fy); ctx.lineTo(fx + S * 0.07, fy); }
        ctx.stroke();
        ctx.fillStyle = "#c9ced6"; ctx.beginPath(); ctx.moveTo(dam, H * 0.8); ctx.lineTo(dam, H * 0.4); ctx.lineTo(W * 0.54, H * 0.4); ctx.lineTo(W * 0.6, H * 0.8); ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,.14)"; ctx.lineWidth = 2; ctx.beginPath(); [0.5, 0.6, 0.7].forEach(function (yy) { ctx.moveTo(dam, H * yy); ctx.lineTo(W * (0.54 + (yy - 0.4) * 0.2), H * yy); }); ctx.stroke();
        if (u > 0.55) { ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 5; ctx.setLineDash([8, 6]); ctx.lineDashOffset = -t * 40; ctx.beginPath(); ctx.moveTo(W * 0.575, H * 0.66); ctx.lineTo(W * 0.575, H * 0.8); ctx.stroke(); ctx.setLineDash([]); }
        var gx = W * 0.8, gt = H * 0.2, gb = H * 0.6, gw = S * 0.05, lv = 0.28 + 0.6 * e;
        ctx.fillStyle = "rgba(8,25,50,.6)"; ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(gx - gw / 2, gt, gw, gb - gt, gw / 2); else ctx.rect(gx - gw / 2, gt, gw, gb - gt); ctx.fill();
        ctx.fillStyle = lv > 0.78 ? "#ffc83d" : "#38d996"; var gh = (gb - gt - 6) * lv; ctx.beginPath(); if (ctx.roundRect) ctx.roundRect(gx - gw / 2 + 3, gb - 3 - gh, gw - 6, gh, gw / 2); else ctx.rect(gx - gw / 2 + 3, gb - 3 - gh, gw - 6, gh); ctx.fill();
        txt(Math.round(lv * 100) + "%", gx, gt - S * 0.025, S * 0.04, "800", "#0b2a55"); txt("Reservoir", gx, gb + S * 0.045, S * 0.026, "700", "#0b2a55");
        if (u > 0.55) pill("Controlled release · no flood", W * 0.5, H * 0.9 - S * 0.13, S * 0.03, "rgba(56,217,150,.96)", "#04301f", seg(u, 0.55, 0.8));
    }
    var FX = { farm: farm, fish: fish, travel: travel, logistics: logistics, construction: construction, energy: energy, health: health, sports: sports, water: water, safety: safety };
    var SCENES = FIELDS.map(function (f) { return FX[f.fx]; });

    /* ---------- the logo animation ---------- */
    function logoScene(lt, a) {
        var lm = lt * MOTION;
        var g = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H * 0.45, S * 0.9); g.addColorStop(0, "#12506a"); g.addColorStop(1, "#040a1c");
        ctx.globalAlpha = a; ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
        for (var i = 0; i < 40; i++) circle(((i * 0.6180339 * 7.3) % 1) * W, ((i * 0.3819660 * 5.1) % 1) * H, 0.6 + (i % 3) * 0.5, "rgba(255,255,255," + (0.25 + 0.25 * Math.sin(lm * 3 + i)) + ")");
        var cx = W / 2, cy = H * 0.42, conv = seg(lt, 0.15, 1.15), icons = ["☀️", "☁️", "💧", "💨", "❄️", "⛈️"];
        icons.forEach(function (ic, n) {
            var ang = n * 1.0472 + lm * 2.6, r = (1 - conv) * S * 0.4 + S * 0.02;
            emoji(ic, cx + Math.cos(ang) * r * 1.25, cy + Math.sin(ang) * r * 0.8, S * 0.07 * (1 - conv * 0.6), 0, a * (1 - seg(lt, 0.95, 1.2)) * seg(lt, 0, 0.25));
        });
        var pop = seg(lt, 1.0, 1.4), over = 1 + 0.12 * Math.sin(clamp((lt - 1.0) / 0.5, 0, 1) * 3.14159), br = S * 0.095 * pop * over;
        if (br > 1) {
            ctx.globalAlpha = a; ctx.shadowColor = "rgba(56,217,150,.65)"; ctx.shadowBlur = 34 + 12 * Math.sin(lm * 4);
            var bg2 = ctx.createLinearGradient(cx - br, cy - br, cx + br, cy + br); bg2.addColorStop(0, "#38d996"); bg2.addColorStop(1, "#ffc83d");
            circle(cx, cy, br, bg2); ctx.shadowBlur = 0;
            circle(cx - br * 0.28, cy + br * 0.18, br * 0.32, "#fff"); circle(cx + br * 0.12, cy - br * 0.02, br * 0.4, "#fff"); circle(cx + br * 0.42, cy + br * 0.22, br * 0.26, "#fff");
            ctx.fillStyle = "#fff"; ctx.fillRect(cx - br * 0.28, cy + br * 0.18, br * 0.7, br * 0.32);
            ctx.strokeStyle = "#ffe08a"; ctx.lineWidth = Math.max(2, br * 0.07); ctx.lineCap = "round"; ctx.beginPath(); for (var r2 = 0; r2 < 8; r2++) { var an = r2 * 0.7854 + lm; ctx.moveTo(cx + Math.cos(an) * br * 1.18, cy + Math.sin(an) * br * 1.18); ctx.lineTo(cx + Math.cos(an) * br * 1.38, cy + Math.sin(an) * br * 1.38); } ctx.stroke();
        }
        var name = "WeatherGPT", size = Math.max(32, Math.min(78, Math.round(W * 0.1)));
        ctx.globalAlpha = a; ctx.font = "800 " + size + "px Segoe UI, system-ui, sans-serif"; ctx.textAlign = "left";
        var total = ctx.measureText(name).width, x = W / 2 - total / 2, shown = Math.floor(name.length * seg(lt, 1.3, 2.0) + 0.001), ty = cy + br * 1.5 + size * 0.9;
        ctx.shadowColor = "rgba(0,0,0,.55)"; ctx.shadowBlur = 14;
        for (var n = 0; n < shown; n++) { ctx.fillStyle = n < 7 ? "#ffffff" : "#38d996"; ctx.fillText(name[n], x, ty); x += ctx.measureText(name[n]).width; }
        ctx.shadowBlur = 0; ctx.globalAlpha = a * seg(lt, 1.9, 2.4);
        txt("WEATHER & CLIMATE, UNDERSTOOD BY AI", W / 2, ty + size * 0.62, Math.max(12, size * 0.26), "600", "#cfe9ff");
        ctx.globalAlpha = 1;
    }

    /* ---------- field scenes with progress icons and captions ---------- */
    function fieldsFrame(t) {
        var k = clamp(Math.floor((t - INTRO) / PER), 0, FIELDS.length - 1), u = clamp((t - INTRO - k * PER) / PER, 0, 1), F = FIELDS[k];
        var tm = t * MOTION;
        SCENES[k](u, tm);
        if (t > LOGO0 - 0.2 && k === FIELDS.length - 1) { ctx.globalAlpha = seg(t, LOGO0 - 0.2, LOGO0); ctx.fillStyle = "#040a1c"; ctx.fillRect(0, 0, W, H); ctx.globalAlpha = 1; }
        else if (u > 0.86 && k < FIELDS.length - 1) { ctx.globalAlpha = seg(u, 0.86, 1); SCENES[k + 1](0, tm); ctx.globalAlpha = 1; }
        var fadeIn = seg(t, 0, INTRO);
        ctx.fillStyle = "rgba(4,10,28," + (0.55 * (1 - fadeIn)) + ")"; ctx.fillRect(0, 0, W, H);
        ctx.shadowColor = "rgba(0,0,0,.45)"; ctx.shadowBlur = 8;
        txt("How weather helps every field", W / 2, Math.max(26, H * 0.06), Math.max(13, Math.min(22, W * 0.026)), "700", "rgba(255,255,255,.92)");
        var sz = Math.max(18, Math.min(34, W * 0.05)), gap = Math.min(sz * 1.9, (W - 24) / FIELDS.length), x0, y0 = Math.max(26, H * 0.06) + sz * 1.2;
        sz = Math.min(sz, gap / 1.2); x0 = W / 2 - gap * (FIELDS.length - 1) / 2;
        FIELDS.forEach(function (f, n) { emoji(f.icon, x0 + n * gap, y0, sz * (n === k ? 1.25 : 0.95), 0, n === k ? 1 : 0.4); });
        ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.fillRect(x0 - gap / 2, y0 + sz * 0.9, gap * FIELDS.length * clamp((t - INTRO) / (PER * FIELDS.length), 0, 1), 3);
        var ca = seg(u, 0, 0.18) * (1 - seg(u, 0.86, 1)), by = H * 0.9;
        ctx.globalAlpha = ca; txt(F.name, W / 2, by - 8 * (1 - ca), Math.max(24, Math.min(46, W * 0.07)), "800", "#fff");
        txt(F.line, W / 2, by + Math.max(20, Math.min(30, W * 0.036)) - 8 * (1 - ca), Math.max(13, Math.min(20, W * 0.026)), "600", "rgba(255,255,255,.92)");
        ctx.globalAlpha = 1; ctx.shadowBlur = 0;
    }
    function frame(t) {
        if (t < LOGO0) fieldsFrame(t); else logoScene(t - LOGO0, 1);
    }

    /*@@SHARED-END@@*/

    function close() {
        if (done) return; done = true; cancelAnimationFrame(raf);
        el.classList.add("out");
        setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); root.classList.remove("wg-splashing"); window.removeEventListener("resize", resize); }, 650);
    }
    skip.addEventListener("click", close); el.addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" || e.key === "Enter") close(); });

    function loop(ts) {
        if (done) return;
        if (!t0) t0 = ts;
        var t = (ts - t0) / 1000;
        if (reduce) logoScene(2.6, clamp(t / 0.4, 0, 1)); else frame(t);
        if (t >= TOTAL) return close();
        raf = requestAnimationFrame(loop);
    }
    raf = requestAnimationFrame(loop);
    window.__wgSplash = { frame: frame, close: close, total: TOTAL };
})();
