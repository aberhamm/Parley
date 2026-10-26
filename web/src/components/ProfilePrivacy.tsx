import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, errorText, getBearer, type Me } from "../lib/api";
import { isFullAccount } from "../lib/links";
import { clearPrivacyMemory } from "../lib/privacyMemory";
import { notificationAudio } from "../lib/notificationAudio";
import { buttonDanger, buttonQuiet, inputClass, labelClass } from "./Modal";

export function ProfilePrivacy({ me, onErased }: { me: Me; onErased: () => void }) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const id = useId();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const canErase = isFullAccount(me) && !getBearer();

  async function erase() {
    if (busy || typed !== "DELETE") return;
    setBusy(true);
    setError("");
    try {
      await api("POST", "/api/me/erase", { confirm: "DELETE" });
      notificationAudio.stop();
      clearPrivacyMemory();
      qc.clear();
      onErased();
      navigate("/", { replace: true });
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <section className="mt-5 border-t border-line pt-4">
      <button
        type="button"
        className={buttonQuiet + " text-[12px]"}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        Privacy and deletion
      </button>
      {open && (
        <div id={id} className="mt-3 space-y-3 text-[12px] leading-relaxed text-ink-soft">
          <p>
            Ending a session keeps its history. A workspace owner can delete a
            session or the workspace from the active database, or choose when
            ended sessions are deleted automatically in workspace Settings.
          </p>
          <p>
            Backups and security logs are separate copies. They may remain until
            their configured expiry. Downloaded exports, analytics and data sent
            to external services are outside these deletion controls. This does
            not promise immediate removal of every copy.
          </p>
          {canErase ? (
            <>
              <p>
                Profile erasure removes your display name, avatar, sign-in data,
                memberships, hosting access, votes, standup entries, commitments,
                kudos, calendar credentials and away days.
                Shared session and story content stays, with a deleted participant
                placeholder where a historical reference is needed. Transfer
                ownership or administration first if you are the last person
                responsible for a workspace or organization.
              </p>
              {confirming ? (
                <div className="rounded-card border border-stop p-3">
                  <p>This cannot be undone. You will be signed out on every device.</p>
                  <label htmlFor={id + "-confirm"} className={labelClass}>
                    Type DELETE to confirm profile erasure
                  </label>
                  <input
                    id={id + "-confirm"}
                    className={inputClass}
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    disabled={busy}
                  />
                  {error && <p role="alert" className="mt-3 text-stop">{error}</p>}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" className={buttonQuiet} disabled={busy} onClick={() => {
                      setConfirming(false); setTyped(""); setError("");
                    }}>Cancel</button>
                    <button type="button" className={buttonDanger} disabled={busy || typed !== "DELETE"} onClick={() => void erase()}>
                      {busy ? "Erasing…" : "Permanently erase my profile"}
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" className={buttonQuiet + " text-stop"} onClick={() => setConfirming(true)}>
                  Delete my profile and personal contributions
                </button>
              )}
            </>
          ) : (
            <p>Profile erasure is available from your full account in the main app.</p>
          )}
        </div>
      )}
    </section>
  );
}
