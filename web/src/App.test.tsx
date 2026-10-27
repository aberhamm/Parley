import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import beacon from "./themes/beacon.theme.json";
import { parseThemePack } from "./lib/theme";
import App from "./App";
vi.mock("./pages/Landing",()=>({Landing:()=> <p>Landing</p>}));
vi.mock("./pages/LinkPage",()=>({LinkPage:()=> <p>Link failed to load</p>}));
vi.mock("./pages/PresentPage",()=>({PresentPage:()=> <p>Guest presentation</p>}));
vi.mock("./pages/InvitationPage",()=>new Promise(()=>{}));
afterEach(()=>cleanup());
it.each(["/","/link#SECRET","/session/guest/present","/invite"])("keeps preference outside route content and loading on %s",(path)=>{
  history.replaceState({},"",path); render(<App/>);
  expect(screen.getByText("Usage privacy")).toBeTruthy();
});
it.each(["/auth/callback","/embed/meet/mainstage","/o/private/admin/plugins"])("excludes %s without needing profile access",(path)=>{
  history.replaceState({},"",path); render(<App/>);
  expect(screen.queryByText("Usage privacy")).toBeNull();
});

/**
 * The pipeline end to end, at the level a user meets it: a pack sitting in
 * storage themes the running app with no screen and no reload, and clearing it
 * hands the page back to the built-in tokens. Asserted here rather than on the
 * hook, because a hook nothing mounts themes nothing.
 */
describe("theme packs reach the app", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("style");
    vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
  });

  it("applies an installed pack to the running app", async () => {
    localStorage.setItem("parley:theme-pack", JSON.stringify(beacon));
    render(<App />);
    const parsed = parseThemePack(beacon);
    if (!parsed.ok) throw new Error(parsed.errors.join("; "));
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue("--color-felt")).toBe(
        parsed.pack.modes.light!.felt,
      ),
    );
  });

  it("leaves the built-in tokens alone when nothing is installed", async () => {
    render(<App />);
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue("--color-felt")).toBe(""),
    );
  });
});
