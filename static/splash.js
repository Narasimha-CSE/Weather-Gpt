/* WeatherGPT - logo animation shown once after a successful login (email+captcha, OTP, Google, phone). */
(function () {
    "use strict";
    var fromGoogle = /(^|[?&])welcome=1(&|$)/.test(location.search), flagged = false;
    try { flagged = sessionStorage.getItem("wg_splash") === "1"; sessionStorage.removeItem("wg_splash"); } catch (e) { /* ignore */ }
    if (!fromGoogle && !flagged) return;
    try { history.replaceState(null, "", location.pathname + location.hash); } catch (e) { /* ignore */ }

    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var letters = "WeatherGPT".split("").map(function (c, i) { return '<span style="--i:' + i + '">' + c + "</span>"; }).join("");
    var drops = "";
    for (var n = 0; n < 26; n++) drops += '<i style="left:' + (Math.random() * 100).toFixed(1) + '%;animation-delay:' + (Math.random() * 1.6).toFixed(2) + 's;animation-duration:' + (0.9 + Math.random() * 0.8).toFixed(2) + 's"></i>';

    var el = document.createElement("div");
    el.id = "wgSplash";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = '<div class="wgs-rain">' + drops + '</div><div class="wgs-box">' +
        '<svg class="wgs-logo" viewBox="0 0 120 100" width="150" height="125">' +
        '<g class="wgs-sun"><circle cx="78" cy="38" r="17" fill="#ffc83d"/>' +
        '<g stroke="#ffc83d" stroke-width="4" stroke-linecap="round"><path d="M78 10v7M78 59v7M50 38h7M99 38h7M58 18l5 5M93 53l5 5M98 18l-5 5M63 53l-5 5"/></g></g>' +
        '<path class="wgs-cloud" d="M36 82h50a16 16 0 0 0 1-32 22 22 0 0 0-42-4 17 17 0 0 0-9 36z" fill="#eaf6ff" stroke="#38d996" stroke-width="3" stroke-linejoin="round"/>' +
        '<g class="wgs-drops" stroke="#38d996" stroke-width="3.5" stroke-linecap="round"><path d="M48 90l-3 7M62 90l-3 7M76 90l-3 7"/></g></svg>' +
        '<div class="wgs-name">' + letters + '</div><div class="wgs-tag">AI Weather Intelligence</div>' +
        '<div class="wgs-bar"><i></i></div></div>';

    var root = document.documentElement;
    root.classList.add("wg-splashing");
    root.appendChild(el);
    var hold = reduce ? 700 : 2800;
    setTimeout(function () { el.classList.add("out"); }, hold);
    setTimeout(function () { el.remove(); root.classList.remove("wg-splashing"); }, hold + 700);
})();
