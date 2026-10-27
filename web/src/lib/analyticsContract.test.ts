import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { analyticsPageCategory, projectAnalyticsEvent } from "./analyticsContract";

const noProperties = [
  "workspace_created", "workspace_joined", "invitation_accepted", "guest_link_redeemed",
  "poker_vote_saved", "poker_reveal_requested", "standup_participated",
];
const withKind = ["session_created", "room_opened", "session_closed"];

describe("analytics event projection", () => {
  it.each(noProperties)("projects %s with only the fixed numeric schema", (name) => {
    expect(projectAnalyticsEvent(name)).toEqual({ name, data: { schema: 1 } });
    expect(projectAnalyticsEvent(name, {})).toEqual({ name, data: { schema: 1 } });
    expect(projectAnalyticsEvent(name, { schema: 1 })).toEqual({ name, data: { schema: 1 } });
  });

  it.each(withKind)("requires a bounded ceremony kind for %s", (name) => {
    for (const kind of ["poker", "standup", "other"]) {
      expect(projectAnalyticsEvent(name, { kind })).toEqual({ name, data: { schema: 1, kind } });
    }
    for (const kind of [undefined, null, "plugin-private-name", 1, { value: "poker" }]) {
      expect(projectAnalyticsEvent(name, { kind })).toBeNull();
    }
    expect(projectAnalyticsEvent(name)).toBeNull();
  });

  it("keeps explicit rejection separate from an ambiguous creation outcome", () => {
    for (const flow of ["workspace_create", "session_create"]) {
      for (const category of ["rejected", "outcome_unknown"]) {
        expect(projectAnalyticsEvent("creation_failed", { flow, category })).toEqual({
          name: "creation_failed", data: { schema: 1, flow, category },
        });
      }
    }
    for (const data of [{}, { flow: "workspace_create" }, { category: "rejected" },
      { flow: "invite", category: "rejected" }, { flow: "session_create", category: "raw-error" }]) {
      expect(projectAnalyticsEvent("creation_failed", data)).toBeNull();
    }
  });

  it("rejects unknown event names, inherited object names and nonstring names", () => {
    for (const name of ["click", "identify", "constructor", "toString", "__proto__", "", null, 1, {}]) {
      expect(projectAnalyticsEvent(name, {})).toBeNull();
    }
  });

  it("rejects every extra field instead of filtering an arbitrary payload", () => {
    const samples = [
      ["workspace_created", {}], ["session_created", { kind: "poker" }],
      ["creation_failed", { flow: "session_create", category: "rejected" }],
    ] as const;
    const fields = ["id", "userId", "distinctId", "sessionId", "storyId", "name", "title", "url",
      "hostname", "referrer", "token", "value", "text", "count", "timestamp", "ip", "release", "testId"];
    for (const [name, data] of samples) {
      for (const key of fields) {
        expect(projectAnalyticsEvent(name, { ...data, [key]: "DONT-SEND-SECRET" })).toBeNull();
      }
    }
    expect(projectAnalyticsEvent("workspace_created", { kind: "poker" })).toBeNull();
    expect(projectAnalyticsEvent("session_created", { kind: "poker", flow: "session_create" })).toBeNull();
  });

  it("accepts only the fixed schema value, and reprojects already approved data", () => {
    for (const schema of ["1", 0, 2, null, undefined, {}, [1]]) {
      expect(projectAnalyticsEvent("session_created", { kind: "poker", schema })).toBeNull();
    }
    const projected = projectAnalyticsEvent("session_created", { kind: "standup" });
    expect(projectAnalyticsEvent(projected?.name, projected?.data)).toEqual(projected);
  });

  it("refuses arrays, instances, inherited properties, symbols and accessors without executing them", () => {
    for (const data of [null, [], new Date(), new Error("DONT-SEND-SECRET"), "poker", 1,
      Object.create({ kind: "poker" }), { kind: "poker", [Symbol("private")]: "DONT-SEND-SECRET" }]) {
      expect(projectAnalyticsEvent("session_created", data)).toBeNull();
    }
    let reads = 0;
    const accessor = Object.defineProperty({}, "kind", { get() { reads++; return "poker"; } });
    expect(projectAnalyticsEvent("session_created", accessor)).toBeNull();
    expect(reads).toBe(0);
    expect(projectAnalyticsEvent("workspace_created", Object.defineProperty({}, "private", {
      value: "DONT-SEND-SECRET", enumerable: false,
    }))).toBeNull();
    const hostile = new Proxy({}, { ownKeys() { throw new Error("DONT-SEND-SECRET"); } });
    expect(projectAnalyticsEvent("workspace_created", hostile)).toBeNull();
    expect(projectAnalyticsEvent("workspace_created", JSON.parse('{"__proto__":"private"}'))).toBeNull();
  });

  it("builds a fresh projection without mutating or retaining the caller's object", () => {
    const input = Object.freeze({ kind: "poker", schema: 1 });
    const projected = projectAnalyticsEvent("session_created", input);
    expect(projected).toEqual({ name: "session_created", data: { schema: 1, kind: "poker" } });
    expect(projected?.data).not.toBe(input);
    expect(input).toEqual({ kind: "poker", schema: 1 });
    const nullPrototype = Object.assign(Object.create(null), { kind: "other" });
    expect(projectAnalyticsEvent("room_opened", nullPrototype)).toEqual({
      name: "room_opened", data: { schema: 1, kind: "other" },
    });
  });

  it("refuses a revoked proxy without throwing into a user action", () => {
    const { proxy, revoke } = Proxy.revocable({}, {});
    revoke();
    expect(projectAnalyticsEvent("workspace_created", proxy)).toBeNull();
  });
});

const routes: Record<string, string | null> = {
  "/": "/", "/invite": "/invite", "/o/:org": "/directory",
  "/o/:org/admin/plugins": null, "/catalog": null,
  "/o/:org/s/:slug": "/workspace", "/o/:org/s/:slug/settings": "/workspace-settings",
  "/session/:id": "/session", "/session/:id/present": "/present", "/link": "/link",
  "/embed/meet/sidepanel": null, "/embed/meet/mainstage": null,
};

describe("analytics route projection", () => {
  it("classifies every registered SPA route explicitly so new routes require a decision", () => {
    const app = readFileSync("src/App.tsx", "utf8");
    const registered = [...app.matchAll(/<Route path="([^"]+)"/g)].map((match) => match[1]);
    expect(registered.sort()).toEqual(Object.keys(routes).sort());
    for (const [template, category] of Object.entries(routes)) {
      const path = template.replace(/:(org|slug|id)/g, "DONT-SEND-SECRET");
      expect(analyticsPageCategory(path)).toBe(category);
    }
  });

  it.each([
    ["/o/private-org/s/private-room", "/workspace"],
    ["/o/private-org/s/private-room/settings/", "/workspace-settings"],
    ["/o/%E2%98%83/s/%E2%9C%93", "/workspace"],
    ["/session/private-id?token=secret#private", "/session"],
    ["/invite#private-token", "/invite"], ["/?private=secret#secret", "/"],
    ["/SESSION/private-id/PRESENT", "/present"],
    ["/o/private-org/s/private-room/unregistered", "/other"],
    ["/s/legacy-private-slug", "/other"], ["/fr/session/private-id", "/other"],
    ["/unknown/private-content", "/other"], ["/%ZZ/private", "/other"],
    ["//o/private-org/s/private-room", "/other"], ["https://secret.invalid/private", "/other"],
  ])("maps %s to a fixed category", (path, category) => {
    expect(analyticsPageCategory(path)).toBe(category);
  });

  it.each([
    "/api/me", "/API/private", "/%61uth/callback", "/auth/callback", "/login", "/logout",
    "/auth%2Fcallback", "/api%2Fme", "/o/private-org/admin%2Fplugins", "/en/%61uth%2Fcallback",
    "/signin", "/sign-in", "/callback", "/internal/private", "/sso", "/de/auth/callback",
    "/catalog/private-plugin", "/plugin-ui/private-install", "/embed/meet/private",
    "/o/private-org/admin", "/o/private-org/admin/plugins", "/o/private-org/ADMIN/private",
  ])("excludes %s", (path) => {
    expect(analyticsPageCategory(path)).toBeNull();
  });
});
