import { captureAnalytics } from "../test/analytics";
import { beforeEach, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "../test/render";
import { api } from "../lib/api";
import { InvitationPage } from "./InvitationPage";
vi.mock("../lib/api",async()=>({...await vi.importActual("../lib/api"),api:vi.fn()}));
beforeEach(()=>{
 sessionStorage.clear();history.replaceState(null,"","/invite#t="+"x".repeat(43));
 vi.mocked(api).mockReset();vi.mocked(api).mockImplementation(async(_method,path)=>{
  if(path==="/api/me")return {id:"user",name:"User",avatarHue:0};
  if(path==="/api/invitations/preview")return {id:"i1",role:"participant",spaceName:"Team",orgSlug:"default",spaceSlug:"team"};
  if(path==="/api/invitations/accept")throw new Error("Temporary network failure");
  throw new Error("unexpected path "+path);
 });
});
it("keeps the token out of the URL and permits retry after a transient acceptance failure",async()=>{
 const user=userEvent.setup();renderApp(<InvitationPage/>);
 const button=await screen.findByRole("button",{name:"Accept invitation"});
 expect(location.hash).toBe("");await user.click(button);
 await screen.findByRole("alert");
 await waitFor(()=>expect((button as HTMLButtonElement).disabled).toBe(false));
 await user.click(button);
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==="/api/invitations/accept")).toHaveLength(2);
});
it("does not accept or mint an identity without an invitation token",async()=>{
 history.replaceState(null,"","/invite");renderApp(<InvitationPage/>);
 await screen.findByText("Open the complete invitation link your host shared.");
 expect(screen.queryByRole("button",{name:"Accept invitation"})).toBeNull();
 expect(vi.mocked(api).mock.calls.some(c=>c[0]==="POST")).toBe(false);
});
it("accepts invitations even when browser session storage is unavailable", async () => {
 const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
 const remove = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
 vi.mocked(api).mockImplementation(async (_method, path) => {
  if (path === "/api/me") return {id:"user",name:"User",avatarHue:0};
  return {id:"i1",role:"host",orgSlug:"default"};
 });
 try {
  renderApp(<InvitationPage />);
  const button = await screen.findByRole("button", {name:"Accept invitation"});
  expect(location.hash).toBe("");
  await userEvent.click(button);
  await waitFor(() => expect(remove).toHaveBeenCalled());
  expect(screen.queryByRole("alert")).toBeNull();
 } finally { set.mockRestore(); remove.mockRestore(); }
});

it("observes only acknowledged invitation acceptance, with no preview or token fields", async () => {
 const captured = captureAnalytics("/invite#t=PRIVATE-TOKEN");
 const original = vi.mocked(api).getMockImplementation()!;
 let succeed = false;
 vi.mocked(api).mockImplementation(async (method, path, body) => {
  if (path === "/api/invitations/accept" && succeed) return {orgSlug:"private-org",spaceSlug:"private-workspace"};
  return original(method, path, body);
 });
 renderApp(<InvitationPage />, {route:"/invite"});
 const button = await screen.findByRole("button", {name:"Accept invitation"});
 expect(captured.events()).toEqual([]);
 await userEvent.click(button);
 await screen.findByRole("alert");
 expect(captured.events()).toEqual([]);
 succeed = true;
 await userEvent.click(button);
 await waitFor(() => expect(captured.events()).toEqual([{name:"invitation_accepted",data:{schema:1}}]));
 expect(JSON.stringify(captured.payloads)).not.toMatch(/PRIVATE|private-org|private-workspace/);
});

it.each(["disabled", "optout", "dnt", "missing", "throws", "rejects"])("preserves successful acceptance when analytics %s", async (mode) => {
 const captured=captureAnalytics("/invite#t=PRIVATE-TOKEN");
 if(mode === "disabled") document.querySelector<HTMLMetaElement>('meta[name="app-analytics"]')!.dataset.namedEvents="false";
 if(mode === "optout") localStorage.setItem("umami.disabled","1");
 if(mode === "dnt") window.doNotTrack="1";
 if(mode === "missing") delete window.umami;
 if(mode === "throws") window.umami={track(){throw new Error("synthetic tracker failure");}};
 if(mode === "rejects") window.umami={track(){return Promise.reject(new Error("synthetic tracker rejection"));}};
 vi.mocked(api).mockImplementation(async (_method,path) => {
  if(path === "/api/me") return {id:"user",name:"User",avatarHue:0};
  return {id:"i1",role:"host",orgSlug:"default"};
 });
 renderApp(<InvitationPage />, {route:"/invite"});
 await userEvent.click(await screen.findByRole("button",{name:"Accept invitation"}));
 await waitFor(() => expect(sessionStorage.getItem("scrum-pro:invitation")).toBeNull());
 expect(screen.queryByRole("alert")).toBeNull();
 expect(captured.events()).toEqual([]);
 delete window.doNotTrack;
 localStorage.removeItem("umami.disabled");
});

it("does not report preview or a sign-in prompt as invitation acceptance", async () => {
 const captured=captureAnalytics("/invite#t=PRIVATE-TOKEN");
 vi.mocked(api).mockImplementation(async (_method,path) => {
  if(path === "/api/me") return null;
  if(path === "/api/auth") return {mode:"oidc"};
  return {id:"i1",role:"participant",spaceName:"PRIVATE TEAM",orgSlug:"private-org",spaceSlug:"private-space"};
 });
 renderApp(<InvitationPage />, {route:"/invite"});
 await userEvent.click(await screen.findByRole("button",{name:"Accept invitation"}));
 await screen.findByRole("link",{name:/sign in/i});
 expect(captured.events()).toEqual([]);
 expect(vi.mocked(api).mock.calls.some(([,path]) => path === "/api/invitations/accept")).toBe(false);
});

it("does not report an invalid invitation preview", async () => {
 const captured=captureAnalytics("/invite#t=PRIVATE-INVALID");
 vi.mocked(api).mockImplementation(async (_method,path) => {
  if(path === "/api/me") return {id:"user",name:"User",avatarHue:0};
  throw new Error("Invitation unavailable");
 });
 renderApp(<InvitationPage />, {route:"/invite"});
 await screen.findByRole("alert");
 expect(screen.queryByRole("button",{name:"Accept invitation"})).toBeNull();
 expect(captured.events()).toEqual([]);
});
