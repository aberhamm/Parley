import { beforeEach, describe, expect, it, vi } from "vitest";
import fixturePolicy from "./analytics-policy.json";
// Only this test module injects synthetic policy pins. Production has no
// window/global/env override for fixed telemetry fields.
vi.mock("./analytics-policy.json", async (importOriginal) => {
  const actual = await importOriginal<{ default: typeof fixturePolicy }>();
  return { default: { ...actual.default, website: "test-site", hostname: "localhost", title: "Scrum Pro" } };
});
let analytics: typeof import("./analytics");
beforeEach(async () => {
  vi.resetModules();
  fixturePolicy.website = "test-site"; fixturePolicy.hostname = "localhost"; fixturePolicy.title = "Scrum Pro";
  document.head.innerHTML = '<meta name="app-analytics" data-website-id="test-site" data-domains="localhost" data-named-events="false">';
  localStorage.clear();
  history.replaceState({}, "", "/o/private-org/s/private-space/settings?token=SECRET#SECRET");
  Object.defineProperty(navigator, "doNotTrack", { configurable: true, value: "0" });
  delete window.doNotTrack;
  delete window.umami;
  analytics = await import("./analytics");
});
function load(named = false) {
  document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]')!.dataset.namedEvents = String(named);
  const track = vi.fn(() => Promise.resolve());
  window.umami = { track };
  analytics.initializeAnalytics();
  document.querySelector<HTMLScriptElement>("#umami-pageviews")!.onload!(new Event("load"));
  track.mockClear();
  return track;
}

describe("analytics adapter", () => {
  it("installs one manually driven tracker and defines its guard before loading", () => {
    analytics.initializeAnalytics(); analytics.initializeAnalytics();
    expect(document.querySelectorAll("#umami-pageviews").length).toBe(1);
    expect(typeof window.appUmamiBeforeSend).toBe("function");
    expect(document.querySelector<HTMLScriptElement>("#umami-pageviews")!.dataset.autoTrack).toBe("false");
  });
  it("projects all page fields into the fixed route category", () => {
    load();
    expect(window.appUmamiBeforeSend!("event", {url: location.href, title: "SECRET", referrer:"SECRET", id:"SECRET", hostname:"SECRET"})).toEqual({website:"test-site",hostname:"localhost",url:"/workspace-settings",title:"Scrum Pro",referrer:""});
    history.replaceState({},"","/session/SECRET");
    expect(window.appUmamiBeforeSend!("event", {})).toMatchObject({url:"/session"});
  });
  it("reevaluates opt-out for every send and late callback", () => {
    const track = load(true);
    analytics.setAnalyticsDisabled(true);
    expect(analytics.analyticsPreference()).toBe("disabled");
    analytics.trackAnalyticsPage(); analytics.trackAnalyticsEvent("workspace_created");
    expect(track).not.toHaveBeenCalled();
    expect(window.appUmamiBeforeSend!("event", {})).toBe(false);
    analytics.setAnalyticsDisabled(false);
    expect(localStorage.getItem("umami.disabled")).toBeNull();
    localStorage.setItem("umami.disabled", "1");
    expect(window.appUmamiBeforeSend!("event", {})).toBe(false);
  });
  it("reevaluates DNT after readiness and refuses initial loading", () => {
    Object.defineProperty(navigator,"doNotTrack",{configurable:true,value:"1"});
    analytics.initializeAnalytics();
    expect(document.querySelector("#umami-pageviews")).toBeNull();
    Object.defineProperty(navigator,"doNotTrack",{configurable:true,value:"0"});
    load(); window.doNotTrack="1";
    expect(window.appUmamiBeforeSend!("event", {})).toBe(false);
  });
  it("does not load for preview hosts, initial optout or excluded routes", () => {
    document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]')!.dataset.domains="production.example";
    analytics.initializeAnalytics(); expect(document.querySelector("#umami-pageviews")).toBeNull();
    document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]')!.dataset.domains="localhost";
    localStorage.setItem("umami.disabled","1");
    analytics.initializeAnalytics(); expect(document.querySelector("#umami-pageviews")).toBeNull();
    localStorage.clear(); history.replaceState({},"","/embed/meet/mainstage");
    analytics.initializeAnalytics(); expect(document.querySelector("#umami-pageviews")).toBeNull();
  });
  it("keeps named collection defaultoff and rejects unknown payload types", () => {
    const track=load(); analytics.trackAnalyticsEvent("workspace_created");
    expect(track).not.toHaveBeenCalled();
    expect(window.appUmamiBeforeSend!("event", {name:"workspace_created"})).toBe(false);
    for(const type of ["identify","session","performance","replay","heatmap"]) expect(window.appUmamiBeforeSend!(type,{})).toBe(false);
  });
  it("rejects unknown named payloads and projects only the approved primitive catalog", () => {
    load(true);
    expect(window.appUmamiBeforeSend!("event",{name:"private-click",data:{}})).toBe(false);
    expect(window.appUmamiBeforeSend!("event",{name:"session_created",data:{kind:"poker",id:"SECRET"}})).toBe(false);
    expect(window.appUmamiBeforeSend!("event",{name:"session_created",data:{kind:"poker"},extra:"SECRET"})).toEqual({website:"test-site",hostname:"localhost",url:"/workspace-settings",title:"Scrum Pro",referrer:"",name:"session_created",data:{schema:1,kind:"poker"}});
    expect(window.appUmamiBeforeSend!("event",{data:{id:"SECRET"}})).toBe(false);
  });
  it("drops absent, failed and rejecting transports without interrupting an action", async () => {
    expect(()=>analytics.trackAnalyticsEvent("workspace_created")).not.toThrow();
    const track=load(true);
    track.mockImplementation(()=>Promise.reject(new Error("offline")));
    expect(()=>analytics.trackAnalyticsEvent("workspace_created")).not.toThrow();
    await Promise.resolve();
    track.mockImplementation(()=>{throw new Error("blocked")});
    expect(()=>analytics.trackAnalyticsPage()).not.toThrow();
    document.querySelector<HTMLScriptElement>("#umami-pageviews")!.onerror!(new Event("error"));
    track.mockClear(); analytics.trackAnalyticsPage(); expect(track).not.toHaveBeenCalled();
  });
  it("fails closed before loading when storage cannot be read", () => {
    vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw new Error("denied")});
    analytics.initializeAnalytics();
    expect(document.querySelector("#umami-pageviews")).toBeNull();
    expect(analytics.analyticsPreference()).toBe("temporary-disabled");
  });
  it("deduplicates initial readiness and React route effects", () => {
    const track = load();
    analytics.trackAnalyticsPage(); analytics.trackAnalyticsPage();
    expect(track).not.toHaveBeenCalled();
    history.replaceState({},"","/session/new-room");
    analytics.trackAnalyticsPage(); analytics.trackAnalyticsPage();
    expect(track).toHaveBeenCalledTimes(1);
  });
  it.each(["createElement", "src", "appendChild"])("drops optional loader failure at %s without aborting app boot", (stage) => {
    const error = new DOMException("blocked", "SecurityError");
    if (stage === "createElement") vi.spyOn(document,"createElement").mockImplementation(()=>{throw error});
    if (stage === "src") vi.spyOn(HTMLScriptElement.prototype,"src","set").mockImplementation(()=>{throw error});
    if (stage === "appendChild") vi.spyOn(document.head,"appendChild").mockImplementation(()=>{throw error});
    expect(()=>analytics.initializeAnalytics()).not.toThrow();
    expect(()=>analytics.trackAnalyticsPage()).not.toThrow();
  });
  it("refuses malformed outer payloads without executing accessors", () => {
    load(true);
    let reads=0;
    const getter=()=>{reads++;return "workspace_created"};
    const samples=[
      Object.defineProperty({},"name",{get:getter}),
      Object.defineProperty({name:"workspace_created"},"data",{get(){reads++;return {}}}),
      Object.defineProperty({},"url",{get:getter}),
      Object.create({name:"workspace_created"}),[],new Date(),
      {[Symbol("private")]:"private"},
    ];
    const {proxy,revoke}=Proxy.revocable({},{});revoke();samples.push(proxy);
    for(const payload of samples) expect(window.appUmamiBeforeSend!("event",payload)).toBe(false);
    expect(reads).toBe(0);
  });
  it("records reentry after an excluded route while retaining duplicate-effect suppression", () => {
    const track=load();
    analytics.trackAnalyticsPage();expect(track).not.toHaveBeenCalled();
    history.replaceState({},"","/o/private/admin/plugins");analytics.trackAnalyticsPage();
    expect(track).not.toHaveBeenCalled();
    history.replaceState({},"","/o/private-org/s/private-space/settings");
    analytics.trackAnalyticsPage();analytics.trackAnalyticsPage();
    expect(track).toHaveBeenCalledTimes(1);
  });
  it("keeps document opt-out when storage cannot be accessed", () => {
    load(true);
    vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw new Error("denied")});
    vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw new Error("denied")});
    analytics.setAnalyticsDisabled(true);
    expect(analytics.analyticsPreference()).toBe("temporary-disabled");
    expect(window.appUmamiBeforeSend!("event",{})).toBe(false);
  });
});

it("suppresses initial and late collection in embedded frames", () => {
  const original = window;
  const frame = new Proxy(original, { get(target, key) { return key === "top" ? {} : Reflect.get(target, key); } });
  vi.stubGlobal("window", frame);
  try {
    analytics.initializeAnalytics();
    expect(document.querySelector("#umami-pageviews")).toBeNull();
  } finally { vi.unstubAllGlobals(); }
  const track = load(true);
  vi.stubGlobal("window", frame);
  try {
    analytics.trackAnalyticsPage(); analytics.trackAnalyticsEvent("workspace_created");
    expect(window.appUmamiBeforeSend!("event", {})).toBe(false);
    expect(track).not.toHaveBeenCalled();
  } finally { vi.unstubAllGlobals(); }
});

it("consumes canonical fixed pins in the actual adapter and rejects metadata drift", () => {
  fixturePolicy.title = "Canonical fixture title";
  load();
  expect(window.appUmamiBeforeSend!("event", {})).toEqual({ website: fixturePolicy.website, hostname: fixturePolicy.hostname, url: "/workspace-settings", title: fixturePolicy.title, referrer: "" });
});
it("refuses an independently selected metadata website", () => {
  document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]')!.dataset.websiteId = "other-site";
  analytics.initializeAnalytics();
  expect(document.querySelector("#umami-pageviews")).toBeNull();
});
it("refuses a document outside the canonical host even if metadata allows it", () => {
  fixturePolicy.hostname = "other.example.invalid";
  analytics.initializeAnalytics();
  expect(document.querySelector("#umami-pageviews")).toBeNull();
});
