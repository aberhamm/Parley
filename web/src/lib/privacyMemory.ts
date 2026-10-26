import { setBearer } from "./api";

/** Erasure clears this app's local identity, invitation and meeting caches. */
export function clearPrivacyMemory(): void {
  setBearer("");
  for (const name of ["localStorage", "sessionStorage"] as const) {
    try {
      const storage = window[name];
      const keys = Array.from({ length: storage.length }, (_, i) => storage.key(i));
      for (const key of keys) {
        if (key && /^(parley[.:]|scrum-pro:)/.test(key)) storage.removeItem(key);
      }
    } catch {
      // Storage may be blocked. Server-side erasure still revokes the account.
    }
  }
}
