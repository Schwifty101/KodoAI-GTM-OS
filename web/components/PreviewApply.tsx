"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { enqueueApply, enqueuePreview } from "@/lib/actions";
import { findPreview, sameArgv, type JobRow } from "@/lib/runnow";

const TERMINAL = ["done", "failed", "cancelled"];

/** Every job of this kind whose argv matches exactly (jsonb containment is only a prefilter), newest first. */
async function fetchRows(kind: string, argv: string[]): Promise<JobRow[]> {
  const { data, error } = await supabase.from("jobs").select("id,kind,status,payload,result,error,created_at,finished_at")
    .eq("kind", kind).contains("payload", { argv }).order("created_at", { ascending: false }).limit(50);
  if (error) throw new Error(error.message);
  return ((data ?? []) as JobRow[]).filter((j) => sameArgv(j.payload?.argv ?? [], argv));
}

/** Preview = the pass without --confirm; Apply = the same argv with --confirm, enabled only after a done preview of this exact argv (the server action re-checks). */
export function PreviewApply({ kind, argv, label, cost, disabledReason, jobs }: {
  kind: string; argv: string[]; label: string; cost?: string; disabledReason?: string; jobs?: JobRow[];
}) {
  const argvKey = JSON.stringify(argv); // callers pass inline arrays; key effects on the value, not the identity
  const [live, setLive] = useState<JobRow[]>([]); // rows fetched here; they win over the page's `jobs` for the same id
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");

  const refresh = useCallback(async () => setLive(await fetchRows(kind, JSON.parse(argvKey))), [kind, argvKey]);

  const rows = [...new Map([...(jobs ?? []), ...live].map((j) => [j.id, j])).values()];
  const mine = rows.filter((j) => j.kind === kind && sameArgv(j.payload?.argv ?? [], argv)); // excludes any --confirm job
  const shown = mine.reduce<JobRow | undefined>((m, j) => (!m || Date.parse(j.created_at) > Date.parse(m.created_at) ? j : m), undefined);
  const polling = !!shown && !TERMINAL.includes(shown.status);
  const preview = findPreview(rows, kind, argv);
  const canApply = !!preview && preview.id === shown?.id && !disabledReason; // a newer preview that is queued, failed or cancelled blocks Apply even if an older one was done
  const out = (shown?.result as { output?: string } | null)?.output;

  useEffect(() => { if (!jobs) refresh().catch((e) => setErr((e as Error).message)); }, [jobs, refresh]); // standalone use: learn of an earlier preview after a reload
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => refresh().catch((e) => setErr((e as Error).message)), 3000);
    return () => clearInterval(t);
  }, [polling, refresh]);

  const run = async (fn: () => Promise<void>, done: string) => {
    setBusy(true); setErr(""); setMsg("");
    try { await fn(); setMsg(done); await refresh(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const apply = () => {
    if (!window.confirm(`Apply: ${label}${cost ? ` (${cost})` : ""}?`)) return;
    run(() => enqueueApply(kind, argv), "Apply queued.");
  };

  return (
    <div className="card">
      <div>
        <button disabled={busy} onClick={() => run(() => enqueuePreview(kind, argv), "")}>Preview {label}</button>{" "}
        <button className="primary" disabled={busy || !canApply} onClick={apply}>Apply {label}{cost ? ` (${cost})` : ""}</button>{" "}
        {disabledReason ? <span className="muted">{disabledReason}</span> : !canApply && <span className="muted">Run Preview first.</span>}
      </div>
      {err && <p className="err">{err}</p>}
      {msg && !err && <p className="msg">{msg}</p>}
      {shown && <p className="muted">Preview {shown.status}{polling && "..."}</p>}
      {shown?.status === "done" && out && <pre className="draft">{out}</pre>}
      {(shown?.status === "failed" || shown?.status === "cancelled") && <p className="err">{shown.error ?? `Preview ${shown.status}.`}</p>}
    </div>
  );
}
