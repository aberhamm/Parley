import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, errorText } from "../lib/api";
import { spaceApi } from "../lib/paths";
import { useToast } from "../lib/ui";
import { buttonQuiet, inputClass, labelClass } from "./Modal";

type PrivacyPolicy = { retentionDays: number };
const allowedDays = [0, 1, 7, 30, 90];

export function PrivacyRetentionPanel({ org, slug }: { org: string; slug: string }) {
  const id = useId();
  const qc = useQueryClient();
  const say = useToast();
  const [draft, setDraft] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const key = ["space-privacy", org, slug];
  const path = spaceApi(org, slug) + "/privacy";
  const policy = useQuery({ queryKey: key, queryFn: () => api<PrivacyPolicy>("GET", path), retry: false });
  const ready = allowedDays.includes(policy.data?.retentionDays ?? -1);
  const selected = draft ?? policy.data?.retentionDays ?? 0;

  async function save() {
    if (!ready || saving) return;
    setSaving(true);
    setError("");
    try {
      const saved = await api<PrivacyPolicy>("PUT", path, { retentionDays: selected });
      qc.setQueryData(key, saved);
      setDraft(null);
      say("Retention saved");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-6 rounded-card border border-line bg-surface px-5 py-4">
      <h2 className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">Privacy and retention</h2>
      <p className="mt-2 text-[13px] text-ink-soft text-pretty">
        Keep meeting history only as long as your team needs it. Automatic
        deletion starts from the time a session ends. Active sessions are never
        deleted automatically.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1">
          <label htmlFor={id} className={labelClass + " mt-0"}>Delete ended sessions after</label>
          <select id={id} className={inputClass} value={selected} disabled={!ready || saving} onChange={(event) => setDraft(Number(event.target.value))}>
            <option value={0}>Never automatically delete</option>
            {allowedDays.filter(days => days > 0).map(days => <option key={days} value={days}>{days} {days === 1 ? "day" : "days"}</option>)}
          </select>
        </div>
        <button type="button" className={buttonQuiet} disabled={!ready || saving || selected === policy.data?.retentionDays} onClick={() => void save()}>
          {saving ? "Saving…" : "Save retention"}
        </button>
      </div>
      {policy.isPending && <p role="status" className="mt-2 text-[12px] text-ink-faint">Loading retention…</p>}
      {policy.isError && <p role="alert" className="mt-2 text-[12px] text-stop">{errorText(policy.error)}</p>}
      {error && <p role="alert" className="mt-2 text-[12px] text-stop">{error}</p>}
      {selected > 0 && (
        <p className="mt-3 text-[12px] font-semibold text-stop">
          Saving this policy also applies to existing ended sessions. Sessions
          already older than this period become eligible for deletion. There is no undo.
        </p>
      )}
      <p className="mt-3 text-[12px] text-ink-faint text-pretty">
        Session deletion removes its stories, votes and standup entries from the
        active database. Workspace-level commitments and kudos remain until the
        workspace is deleted. Backups, security logs and external copies have
        separate retention periods.
      </p>
    </section>
  );
}
