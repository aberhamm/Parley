/** Pure contract only: importing this module never loads or sends analytics. */
import policy from "./analytics-policy.json";
export const ANALYTICS_SCHEMA = policy.schema as 1;

export type AnalyticsKind = "poker" | "standup" | "other";
type SimpleEventName =
  | "workspace_created" | "workspace_joined" | "invitation_accepted" | "guest_link_redeemed"
  | "poker_vote_saved" | "poker_reveal_requested" | "standup_participated";
type KindEventName = "session_created" | "room_opened" | "session_closed";
type CreationFlow = "workspace_create" | "session_create";
type CreationFailure = "rejected" | "outcome_unknown";

export type ApprovedAnalyticsEvent =
  | { name: SimpleEventName; data: { schema: typeof ANALYTICS_SCHEMA } }
  | { name: KindEventName; data: { schema: typeof ANALYTICS_SCHEMA; kind: AnalyticsKind } }
  | { name: "creation_failed"; data: { schema: typeof ANALYTICS_SCHEMA; flow: CreationFlow; category: CreationFailure } };
export type AnalyticsEventName = ApprovedAnalyticsEvent["name"];

export type AnalyticsPageCategory =
  | "/" | "/directory" | "/workspace" | "/workspace-settings" | "/session"
  | "/present" | "/invite" | "/link" | "/other";

// Read data properties without invoking accessors, and reject class instances,
// inherited fields and symbols. A malformed caller must not break a user action.
export function readAnalyticsData(data: unknown): Record<string, unknown> | null {
  if (data === undefined) return {};
  if (data === null || typeof data !== "object") return null;
  try {
    if (Array.isArray(data)) return null;
    const prototype = Object.getPrototypeOf(data);
    if (prototype !== Object.prototype && prototype !== null) return null;
    const descriptors = Object.getOwnPropertyDescriptors(data);
    const values: Record<string, unknown> = Object.create(null);
    for (const key of Reflect.ownKeys(descriptors)) {
      if (typeof key !== "string") return null;
      const descriptor = descriptors[key];
      if (!Object.hasOwn(descriptor, "value")) return null;
      values[key] = descriptor.value;
    }
    return values;
  } catch {
    return null;
  }
}

function hasOnlyProperties(data: Record<string, unknown>, allowed: readonly string[]): boolean {
  return (!Object.hasOwn(data, "schema") || data.schema === ANALYTICS_SCHEMA)
    && Object.keys(data).every((key) => key === "schema" || allowed.includes(key));
}

/** Reject unapproved inputs, then build a new payload from canonical finite data. */
export function projectAnalyticsEvent(name: unknown, data?: unknown): ApprovedAnalyticsEvent | null {
  const values = readAnalyticsData(data);
  if (!values || typeof name !== "string" || !Object.hasOwn(policy.events, name)) return null;
  const fields = policy.events[name as keyof typeof policy.events] as Record<string, string[]>;
  if (!hasOnlyProperties(values, Object.keys(fields))) return null;
  const projected: Record<string, unknown> = { schema: ANALYTICS_SCHEMA };
  for (const [key, allowed] of Object.entries(fields)) {
    if (typeof values[key] !== "string" || !allowed.includes(values[key])) return null;
    projected[key] = values[key];
  }
  return { name, data: projected } as ApprovedAnalyticsEvent;
}

const excludedPrefixes = new Set([
  "api", "auth", "login", "logout", "signin", "sign-in", "callback", "internal", "sso",
  "embed", "plugin-ui", "catalog",
]);

function decodeSegment(segment: string): string {
  try { return decodeURIComponent(segment); } catch { return segment; }
}

/** Match router templates; no part of an address is ever returned as data. */
function classifyAnalyticsPage(pathname: string): AnalyticsPageCategory | null {
  if (typeof pathname !== "string" || !pathname.startsWith("/")) return "/other";
  const path = pathname.split(/[?#]/, 1)[0];
  const parts = path.slice(1).split("/").map(decodeSegment);
  if (parts.at(-1) === "") parts.pop();

  // Exclude sensitive prefixes even on malformed or language-prefixed paths.
  // Language-prefixed application paths are otherwise unknown to App.tsx.
  const nonempty = parts.flatMap((part) => part.split(/[\\/]/)).filter(Boolean)
    .map((part) => part.toLowerCase());
  const excludedPath = ["en", "de", "fr"].includes(nonempty[0]) ? nonempty.slice(1) : nonempty;
  if (excludedPrefixes.has(excludedPath[0])) return null;
  if (excludedPath[0] === "o" && excludedPath[2] === "admin") return null;

  if (parts.some((part) => !part || part.includes("/") || part.includes("\\"))) return "/other";
  const first = parts[0]?.toLowerCase();
  if (!parts.length) return "/";
  if (parts.length === 1 && first === "invite") return "/invite";
  if (parts.length === 1 && first === "link") return "/link";
  if (first === "o") {
    if (parts.length === 2) return "/directory";
    if (parts[2]?.toLowerCase() === "s") {
      if (parts.length === 4) return "/workspace";
      if (parts.length === 5 && parts[4]?.toLowerCase() === "settings") return "/workspace-settings";
    }
  }
  if (first === "session") {
    if (parts.length === 2) return "/session";
    if (parts.length === 3 && parts[2]?.toLowerCase() === "present") return "/present";
  }
  return "/other";
}

export function analyticsPageCategory(pathname: string): AnalyticsPageCategory | null {
  const category = classifyAnalyticsPage(pathname);
  return category !== null && policy.pages.includes(category) ? category : null;
}
