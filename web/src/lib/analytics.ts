import { analyticsPageCategory, projectAnalyticsEvent, readAnalyticsData } from "./analyticsContract";

declare global {
  interface Window {
    appUmamiBeforeSend?: (type: string, payload: Record<string, unknown>) => Record<string, unknown> | false;
    umami?: { track: (name?: string, data?: Record<string, unknown>) => unknown };
    doNotTrack?: string;
  }
}

const listeners = new Set<() => void>();
let documentDisabled: boolean | undefined;
let persistenceFailed = false;
let ready = false;
let attempted = false;
let lastPage: string | undefined;
const notify = () => listeners.forEach((listener) => listener());

export function subscribeAnalytics(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
window.addEventListener("storage", (event) => {
  if (event.key === "umami.disabled" || event.key === null) notify();
});

export function analyticsPreference(): "enabled" | "disabled" | "temporary-enabled" | "temporary-disabled" {
  let disabled = documentDisabled ?? false;
  try {
    if (documentDisabled === undefined) disabled = localStorage.getItem("umami.disabled") === "1";
  } catch { persistenceFailed = true; disabled = documentDisabled ?? true; }
  return persistenceFailed ? (disabled ? "temporary-disabled" : "temporary-enabled") : (disabled ? "disabled" : "enabled");
}

export function analyticsDoNotTrack(): boolean {
  return navigator.doNotTrack === "1" || window.doNotTrack === "1";
}

export function setAnalyticsDisabled(disabled: boolean) {
  documentDisabled = disabled;
  try {
    if (disabled) localStorage.setItem("umami.disabled", "1");
    else localStorage.removeItem("umami.disabled");
    documentDisabled = undefined;
    persistenceFailed = false;
  } catch { persistenceFailed = true; }
  notify();
}

function allowed(): boolean {
  return !analyticsDoNotTrack() && !analyticsPreference().endsWith("disabled");
}
function configuration() {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]');
  if (!meta?.dataset.websiteId || !meta.dataset.domains?.split(",").includes(location.hostname)) return null;
  return { website: meta.dataset.websiteId, named: meta.dataset.namedEvents === "true" };
}

/** One bundled guard, installed before the version-compatible script can send. */
export function initializeAnalytics() {
  try { installAnalytics(); }
  catch { ready = false; attempted = true; }
}

function installAnalytics() {
  const config = configuration();
  if (attempted || !config || !allowed() || analyticsPageCategory(location.pathname) === null) return;
  attempted = true;
  window.appUmamiBeforeSend = (type, payload) => {
    try {
      if (!allowed() || type !== "event" || !payload || typeof payload !== "object") return false;
      const values = readAnalyticsData(payload);
      if (!values) return false;
      const url = analyticsPageCategory(location.pathname);
      if (url === null) return false;
      const base = { website: config.website, hostname: location.hostname, url, title: "Scrum Pro", referrer: "" };
      if (values.name !== undefined) {
        if (!config.named) return false;
        const event = projectAnalyticsEvent(values.name, values.data);
        if (!event) return false;
        return { ...base, name: event.name, data: event.data };
      }
      if (values.data !== undefined) return false;
      return base;
    } catch { return false; }
  };
  const script = document.createElement("script");
  script.id = "umami-pageviews";
  script.src = "/a/script.js";
  script.defer = true;
  script.referrerPolicy = "no-referrer";
  script.dataset.websiteId = config.website;
  script.dataset.beforeSend = "appUmamiBeforeSend";
  script.dataset.autoTrack = "false"; // Confirmed supported by the pinned 3.0.3 fixture.
  script.dataset.doNotTrack = "true";
  script.dataset.excludeSearch = "true";
  script.dataset.excludeHash = "true";
  script.onload = () => { ready = true; trackAnalyticsPage(); };
  script.onerror = () => { ready = false; };
  document.head.appendChild(script);
}

function send(name?: string, data?: Record<string, unknown>) {
  try {
    if (!ready || !allowed() || analyticsPageCategory(location.pathname) === null) return;
    // No queue/retry and no promise is returned into an app operation.
    void Promise.resolve(window.umami?.track(name, data)).catch(() => {});
  } catch { /* Optional analytics must never interrupt app operations. */ }
}
export function trackAnalyticsPage() {
  const category = analyticsPageCategory(location.pathname);
  if (category === null) { lastPage = undefined; return; }
  if (!ready || !allowed() || lastPage === location.pathname) return;
  lastPage = location.pathname;
  send();
}
export function trackAnalyticsEvent(name: unknown, data?: unknown): void {
  const event = projectAnalyticsEvent(name, data);
  if (!configuration()?.named || !event) return;
  send(event.name, event.data);
}
