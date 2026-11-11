import { trackAnalyticsEvent } from "../lib/analytics";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../lib/api";
import { spacePath } from "../lib/paths";
import { NameGate, useMe } from "../components/NameGate";
import { isFullAccount } from "../lib/links";
import { Logo, ThemeToggle } from "../components/Brand";
import { buttonPrimary } from "../components/Modal";
import type { WorkspaceInvitation } from "../components/WorkspaceInvitations";

const pendingKey = "scrum-pro:invitation";
// Fragment tokens are removed from the address bar before sign-in. A bounded
// session-only handoff survives OIDC's redirect without putting secrets in next.
function readToken() {
  const token = new URLSearchParams(location.hash.slice(1)).get("t");
  if (token) {
    try {
      sessionStorage.setItem(pendingKey, JSON.stringify({ token, at: Date.now() }));
    } catch {
      // Restricted storage still permits acceptance on this page.
    }
    history.replaceState(
      history.state,
      "",
      location.pathname + location.search,
    );
    return token;
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingKey) || "null");
    return saved &&
      typeof saved.token === "string" &&
      typeof saved.at === "number" &&
      Date.now() - saved.at < 15 * 60 * 1000
      ? saved.token
      : "";
  } catch {
    return "";
  }
}
export function InvitationPage() {
  const [token] = useState(readToken);
  const [needName, setNeedName] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const preview = useQuery({
    queryKey: ["workspace-invitation", token],
    queryFn: () =>
      api<WorkspaceInvitation>("POST", "/api/invitations/preview", { token }),
    enabled: !!token,
    retry: false,
  });
  async function accept() {
    if (!isFullAccount(me.data)) {
      setNeedName(true);
      return;
    }
    await redeem();
  }
  async function redeem() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const i = await api<WorkspaceInvitation>(
        "POST",
        "/api/invitations/accept",
        { token },
      );
      trackAnalyticsEvent("invitation_accepted");
      try { sessionStorage.removeItem(pendingKey); } catch { /* Storage may be disabled. */ }
      await qc.invalidateQueries({ queryKey: ["my-orgs"] });
      await qc.invalidateQueries({ queryKey: ["my-spaces"] });
      if (i.spaceSlug) {
        await qc.invalidateQueries({
          queryKey: ["space", i.orgSlug, i.spaceSlug],
        });
        navigate(spacePath(i.orgSlug, i.spaceSlug));
      } else navigate("/");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }
  return (
    <main className="mx-auto max-w-xl px-5 py-8">
      <div className="mb-10 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 text-2xl font-bold">
          <Logo size={26} />
          Scrum Pro
        </Link>
        <ThemeToggle />
      </div>
      <h1 className="font-display text-3xl font-bold">You’re invited</h1>
      {!token && (
        <p role="alert" className="mt-4 text-stop">
          Open the complete invitation link your host shared.
        </p>
      )}
      {preview.isPending && token && (
        <p role="status" className="mt-4">
          Checking your invitation…
        </p>
      )}
      {preview.isError && (
        <p role="alert" className="mt-4 text-stop">
          {errorText(preview.error)}
        </p>
      )}
      {preview.data && (
        <section className="mt-5 rounded-panel border border-line bg-surface p-6">
          <p className="text-xl font-bold">
            {preview.data.spaceName || "Scrum Pro hosting"}
          </p>
          <p className="mt-2 text-sm text-ink-soft">
            You’re invited as a <strong>{preview.data.role}</strong>.
          </p>
          <p className="mt-3 text-sm text-ink-soft">
            {preview.data.role === "host"
              ? preview.data.spaceSlug
                ? "You can manage this workspace, create workspaces and sessions in this organization, and invite others."
                : "You can create workspaces and sessions in this organization, and invite others."
              : "You can join this workspace and take part in its sessions. A host starts sessions and manages invitations."}
          </p>
          <button
            className={buttonPrimary + " mt-5"}
            disabled={busy || me.isPending}
            onClick={() => void accept()}
          >
            {busy ? "Accepting…" : "Accept invitation"}
          </button>
        </section>
      )}
      {error && (
        <p role="alert" className="mt-4 text-stop">
          {error}
        </p>
      )}
      {needName && (
        <NameGate
          because="To accept your invitation:"
          onCancel={() => setNeedName(false)}
          onDone={() => {
            setNeedName(false);
            void redeem();
          }}
        />
      )}
    </main>
  );
}
