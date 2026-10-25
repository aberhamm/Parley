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
