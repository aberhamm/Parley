/* Shared Umami pageviews. Configuration is public; never put account data here. */
(() => {
  "use strict";
  const config = document.currentScript || document.getElementById("app-analytics");
  if (!config || window.__appUmamiInstalled) return;
  const website = config.dataset.websiteId;
  const domains = (config.dataset.domains || "").split(",").filter(Boolean);
  if (!website || !domains.includes(location.hostname)) return;
  if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;
  try { if (localStorage.getItem("umami.disabled") === "1") return; } catch { /* Storage is optional. */ }
  const title = config.dataset.appName || "Application";
  const sections = new Set((config.dataset.sections || "").split(",").filter(Boolean));
  const excluded = new Set(["api", "auth", "login", "logout", "signin", "sign-in", "callback", "internal", "sso"]);
  window.__appUmamiInstalled = true;
  window.appUmamiBeforeSend = (type, payload) => {
    if (type !== "event" || !payload || payload.name) return false;
    const parts = location.pathname.split("/").filter(Boolean);
    if (["en", "de", "fr"].includes(parts[0])) parts.shift();
    if (excluded.has((parts[0] || "").toLowerCase())) return false;
    const url = parts.length ? (sections.has(parts[0]) ? "/" + parts[0] : "/other") : "/";
    return { website, hostname: location.hostname, url, title, referrer: "" };
  };
  const script = document.createElement("script");
  script.id = "umami-pageviews";
  script.src = "/a/script.js";
  script.defer = true;
  script.referrerPolicy = "no-referrer";
  script.dataset.websiteId = website;
  script.dataset.beforeSend = "appUmamiBeforeSend";
  script.dataset.doNotTrack = "true";
  script.dataset.excludeSearch = "true";
  script.dataset.excludeHash = "true";
  document.head.appendChild(script);
})();
