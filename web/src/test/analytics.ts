import { vi } from "vitest";
import { initializeAnalytics } from "../lib/analytics";

// Synthetic pins belong only to this Vitest fixture. Keep the production
// adapter's canonical policy checks and the complete payload assertions intact.
vi.mock("../lib/analytics-policy.json", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/analytics-policy.json")>();
  return { default: { ...actual.default, website: "synthetic-site", hostname: "localhost", title: "Scrum Pro" } };
});

/** Synthetic tracker: exercise the real adapter and its full before-send projection. */
export function captureAnalytics(path: string) {
  history.replaceState(null, "", path);
  localStorage.removeItem("umami.disabled");
  Object.defineProperty(navigator, "doNotTrack", { configurable: true, value: "0" });
  delete window.doNotTrack;
  let meta = document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "app-analytics";
    document.head.appendChild(meta);
  }
  meta.dataset.websiteId = "synthetic-site";
  meta.dataset.domains = location.hostname;
  meta.dataset.namedEvents = "true";
  const payloads: Record<string, unknown>[] = [];
  window.umami = { track(name, data) {
    const payload = window.appUmamiBeforeSend?.("event", {
      name, data, url: location.href, title: "PRIVATE TITLE", referrer: "PRIVATE REFERRER",
    });
    if (payload && name) payloads.push(payload);
  } };
  initializeAnalytics();
  document.querySelector<HTMLScriptElement>("#umami-pageviews")?.onload?.(new Event("load"));
  return {
    payloads,
    events: () => payloads.map(({ name, data }) => ({ name, data })),
  };
}
