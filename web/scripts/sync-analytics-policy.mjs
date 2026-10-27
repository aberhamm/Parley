import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
const source = new URL("../src/lib/analytics-policy.json", import.meta.url);
const target = new URL("../../internal/analyticsrelay/policy.generated.json", import.meta.url);
const bytes = readFileSync(source);
const policy = JSON.parse(bytes);
if (policy.schema !== 1 || Object.keys(policy.events).length !== 11 || policy.pages.length !== 9
    || !/^[a-f0-9]{64}$/.test(policy.tracker_sha256)) throw new Error("invalid analytics policy schema");
// Metadata only activates the deployment; it must not silently select another
// runtime policy. Browser payload pins themselves come directly from this JSON.
const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const meta = html.match(/<meta\b[^>]*\bname=["']app-analytics["'][^>]*>/)?.[0];
const attributes = Object.fromEntries([...(meta ?? "").matchAll(/([\w-]+)=["']([^"']*)["']/g)].map((match) => [match[1], match[2]]));
if (attributes["data-website-id"] !== policy.website || attributes["data-domains"] !== policy.hostname) {
  throw new Error("analytics metadata drift: index.html must activate the canonical website and host");
}
if (process.argv.includes("--check")) {
  if (!readFileSync(target).equals(bytes)) throw new Error("analytics policy drift: regenerate with node scripts/sync-analytics-policy.mjs");
} else writeFileSync(fileURLToPath(target), bytes);
