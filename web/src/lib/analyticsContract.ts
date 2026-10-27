/** Pure contract only: importing this module never loads or sends analytics. */
export const ANALYTICS_SCHEMA = 1 as const;

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
function readEventData(data: unknown): Record<string, unknown> | null {
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

function isAnalyticsKind(value: unknown): value is AnalyticsKind {
  return value === "poker" || value === "standup" || value === "other";
}

/** Reject unapproved inputs, then build a new payload from fixed primitives. */
export function projectAnalyticsEvent(name: unknown, data?: unknown): ApprovedAnalyticsEvent | null {
  const values = readEventData(data);
  if (!values) return null;
  switch (name) {
    case "workspace_created":
    case "workspace_joined":
    case "invitation_accepted":
    case "guest_link_redeemed":
    case "poker_vote_saved":
    case "poker_reveal_requested":
    case "standup_participated":
      if (!hasOnlyProperties(values, [])) return null;
      return { name, data: { schema: ANALYTICS_SCHEMA } };
    case "session_created":
    case "room_opened":
    case "session_closed":
      if (!hasOnlyProperties(values, ["kind"]) || !isAnalyticsKind(values.kind)) return null;
      return { name, data: { schema: ANALYTICS_SCHEMA, kind: values.kind } };
    case "creation_failed": {
      if (!hasOnlyProperties(values, ["flow", "category"])) return null;
      const { flow, category } = values;
      if (flow !== "workspace_create" && flow !== "session_create") return null;
      if (category !== "rejected" && category !== "outcome_unknown") return null;
      return { name, data: { schema: ANALYTICS_SCHEMA, flow, category } };
    }
    default:
      return null;
  }
}

const excludedPrefixes = new Set([
  "api", "auth", "login", "logout", "signin", "sign-in", "callback", "internal", "sso",
  "embed", "plugin-ui", "catalog",
]);

function decodeSegment(segment: string): string {
  try { return decodeURIComponent(segment); } catch { return segment; }
}

/** Match router templates; no part of an address is ever returned as data. */
export function analyticsPageCategory(pathname: string): AnalyticsPageCategory | null {
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
