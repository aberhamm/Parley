import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import policy from "./analytics-policy.json";
import { projectAnalyticsEvent } from "./analyticsContract";

describe("canonical analytics policy", () => {
 it("projects every canonical event and refuses extra fields", () => {
  expect(Object.keys(policy.events)).toHaveLength(11);
  expect(policy.pages).toHaveLength(9);
  for (const [name, fields] of Object.entries(policy.events)) {
   const data: Record<string, unknown> = { schema: policy.schema };
   for (const [key, values] of Object.entries(fields)) data[key] = values[0];
   expect(projectAnalyticsEvent(name, data)).toEqual({ name, data });
   expect(projectAnalyticsEvent(name, { ...data, private: "secret" })).toBeNull();
  }
 });
});

it("rejects canonical pin drift in production metadata before the build", () => {
 const dir = mkdtempSync(join(tmpdir(), "parley-policy-drift-"));
 try {
  for (const path of ["web/scripts", "web/src/lib", "internal/analyticsrelay"]) mkdirSync(join(dir,path), {recursive:true});
  writeFileSync(join(dir,"web/scripts/sync-analytics-policy.mjs"), readFileSync("scripts/sync-analytics-policy.mjs"));
  const html = readFileSync("index.html", "utf8");
  writeFileSync(join(dir,"web/index.html"), html);
  const changed = { ...policy, website: "11111111-1111-4111-8111-111111111111", hostname: "other.example.invalid", title: "Changed canonical title" };
  const bytes = JSON.stringify(changed);
  writeFileSync(join(dir,"web/src/lib/analytics-policy.json"),bytes);
  writeFileSync(join(dir,"internal/analyticsrelay/policy.generated.json"),bytes);
  const run = () => spawnSync(process.execPath,[join(dir,"web/scripts/sync-analytics-policy.mjs"),"--check"],{encoding:"utf8"});
  const rejected=run();expect(rejected.status).not.toBe(0);expect(rejected.stderr).toContain("analytics metadata drift");
  writeFileSync(join(dir,"web/index.html"), html.replace(policy.website,changed.website).replace(policy.hostname,changed.hostname));
  expect(run().status).toBe(0);
 } finally { rmSync(dir, {recursive:true,force:true}); }
});
