import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
import policy from "./analytics-policy.json";

describe("pinned SDK relay response protocol", () => {
 it("accepts 200 empty-object JSON twice without reflecting native cache", async () => {
  const source = readFileSync("../internal/analyticsrelay/testdata/umami-3.0.3.js", "utf8");
  expect(createHash("sha256").update(source).digest("hex")).toBe(policy.tracker_sha256);
  const calls: { url: string; options: RequestInit }[] = [];
  const attributes: Record<string, string> = { "data-website-id": policy.website, "data-auto-track": "false", "data-before-send": "project" };
  const window = {
   screen: { width: 1000, height: 1000 }, navigator: { language: "en" },
   location: new URL("https://scrum.matthew.systems/session/SECRET"),
   document: { currentScript: { src: "https://scrum.matthew.systems/a/script.js", getAttribute: (name: string) => attributes[name] ?? null }, referrer: "", title: "PRIVATE" },
   history: {}, localStorage: { getItem: () => null },
   project: () => ({ website: policy.website, hostname: policy.hostname, url: "/session", title: policy.title, referrer: "" }),
   umami: undefined as undefined | { track: () => Promise<void> },
  };
  runInNewContext(source, { window, URL, fetch: async (url: string, options: RequestInit) => { calls.push({ url, options }); return { json: async () => ({}) }; } });
  await window.umami!.track(); await window.umami!.track();
  expect(calls).toHaveLength(2);
  for (const call of calls) {
   expect(call.url).toBe("https://scrum.matthew.systems/a/api/send");
   expect(call.options.credentials).toBe("omit");
   expect(call.options.headers).toEqual({ "Content-Type": "application/json" });
   expect(JSON.parse(String(call.options.body))).toEqual({ type: "event", payload: window.project() });
  }
 });
});
