import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../lib/api";
import { spaceApi } from "../lib/paths";
import { useCopy } from "../lib/ui";
import {
  Modal,
  buttonPrimary,
  buttonQuiet,
  inputClass,
  labelClass,
} from "./Modal";

export type WorkspaceInvitation = {
  id: string;
  orgSlug: string;
  spaceSlug?: string;
  spaceName?: string;
  role: "participant" | "host";
  createdAt: string;
  expiresAt: string;
  acceptedAt: string | null;
  revokedAt: string | null;
};
export function WorkspaceInvitations({
  org,
  slug,
}: {
  org: string;
  slug: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={buttonQuiet} onClick={() => setOpen(true)}>
        Invite someone
      </button>
      {open && (
        <InvitationModal org={org} slug={slug} onClose={() => setOpen(false)} />
      )}
    </>
  );
}
function InvitationModal({
  org,
  slug,
  onClose,
}: {
  org: string;
  slug: string;
  onClose: () => void;
}) {
  const [role, setRole] = useState<"participant" | "host">("participant");
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const copy = useCopy();
  const path = spaceApi(org, slug) + "/invitations";
  const query = useQuery({
    queryKey: ["workspace-invitations", org, slug],
    queryFn: () => api<WorkspaceInvitation[]>("GET", path),
    retry: false,
  });
  async function create() {
    setBusy(true);
    setError("");
    setLink("");
    try {
      const r = await api<{ path: string }>("POST", path, { role });
      setLink(new URL(r.path, location.origin).href);
      await qc.invalidateQueries({
        queryKey: ["workspace-invitations", org, slug],
      });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      await api("DELETE", path + "/" + encodeURIComponent(id));
      setLink("");
      await qc.invalidateQueries({
        queryKey: ["workspace-invitations", org, slug],
      });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Invite someone" onClose={onClose}>
      <p className="text-sm text-ink-soft">
        Choose what this person can do. Each link works once and expires in
        seven days.
      </p>
      <label className={labelClass} htmlFor="invitation-role">
        Invite as
      </label>
      <select
        id="invitation-role"
        className={inputClass}
        value={role}
        disabled={busy}
        onChange={(e) => {
          setRole(e.target.value as "participant" | "host");
          setLink("");
        }}
      >
        <option value="participant">Participant</option>
        <option value="host">Host</option>
      </select>
      <p className="mt-3 text-sm text-ink-soft">
        {role === "participant"
          ? "Join this workspace and take part in sessions. Cannot create workspaces, start sessions, or invite hosts."
          : "Manage this workspace, create workspaces and sessions in this organization, and invite other participants or hosts."}
      </p>
      <button
        className={buttonPrimary + " mt-4"}
        disabled={busy}
        onClick={() => void create()}
      >
        {busy ? "Working…" : "Create invitation"}
      </button>
      {link && (
        <div className="mt-4">
          <label className={labelClass} htmlFor="new-invitation-link">
            Invitation link
          </label>
          <input
            id="new-invitation-link"
            className={inputClass}
            value={link}
            readOnly
          />
          <button
            className={buttonQuiet + " mt-2"}
            onClick={() => void copy(link, "Invitation copied")}
          >
            Copy invitation
          </button>
          <p className="mt-2 text-sm text-ink-soft">
            Copy it now. The link cannot be retrieved after closing this dialog.
          </p>
        </div>
      )}
      {(error || query.isError) && (
        <p role="alert" className="mt-3 text-sm text-stop">
          {error || errorText(query.error)}
        </p>
      )}
      <h3 className="mt-6 font-bold">Recent invitations</h3>
      {query.isPending && <p role="status">Loading invitations…</p>}
      <ul className="mt-2 flex flex-col gap-3">
        {query.data?.map((i) => {
          const status = i.acceptedAt
            ? "Accepted"
            : i.revokedAt
              ? "Revoked"
              : Date.parse(i.expiresAt) <= Date.now()
                ? "Expired"
                : "Pending";
          return (
            <li
              key={i.id}
              className="flex items-center justify-between gap-3 border-t border-line pt-3 text-sm"
            >
              <span>
                <span className="font-bold">
                  {i.role === "host" ? "Host" : "Participant"}
                </span>{" "}
                · {status}
                <span className="block text-ink-soft">
                  Expires {new Date(i.expiresAt).toLocaleDateString("en-US")}
                </span>
              </span>
              {status === "Pending" && (
                <button
                  className={buttonQuiet}
                  disabled={busy}
                  onClick={() => void revoke(i.id)}
                >
                  Revoke
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}
