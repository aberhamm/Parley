import { beforeEach, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderApp } from "../test/render";
import { api } from "../lib/api";
import { expectNoViolations } from "../test/axe";
import { WorkspaceInvitations } from "./WorkspaceInvitations";
vi.mock("../lib/api",async()=>({...await vi.importActual("../lib/api"),api:vi.fn()}));
beforeEach(()=>{
 vi.mocked(api).mockReset();vi.mocked(api).mockImplementation(async(method)=>method==="POST"?{path:"/invite#t=secret"}:[]);
});
it("defaults to participant and only grants host when explicitly selected",async()=>{
 const user=userEvent.setup();const {container}=renderApp(<WorkspaceInvitations org="default" slug="team"/>);
 await user.click(screen.getByRole("button",{name:"Invite someone"}));
 expect((screen.getByLabelText("Invite as") as HTMLSelectElement).value).toBe("participant");
 await user.click(screen.getByRole("button",{name:"Create invitation"}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith("POST","/api/orgs/default/spaces/team/invitations",{role:"participant"}));
 expect((await screen.findByLabelText("Invitation link") as HTMLInputElement).readOnly).toBe(true);
 await user.selectOptions(screen.getByLabelText("Invite as"),"host");
 expect(screen.queryByLabelText("Invitation link")).toBeNull();
 await user.click(screen.getByRole("button",{name:"Create invitation"}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith("POST","/api/orgs/default/spaces/team/invitations",{role:"host"}));
 await expectNoViolations(container);
});
it("lists invitations without reconstructing tokens and revokes a pending invitation",async()=>{
 vi.mocked(api).mockResolvedValue([{id:"i1",role:"participant",expiresAt:"2099-01-01T00:00:00Z",acceptedAt:null,revokedAt:null}]);
 const user=userEvent.setup();renderApp(<WorkspaceInvitations org="default" slug="team"/>);
 await user.click(screen.getByRole("button",{name:"Invite someone"}));await user.click(await screen.findByRole("button",{name:"Revoke"}));
 await waitFor(()=>expect(api).toHaveBeenCalledWith("DELETE","/api/orgs/default/spaces/team/invitations/i1"));
 expect(screen.queryByLabelText("Invitation link")).toBeNull();
});
