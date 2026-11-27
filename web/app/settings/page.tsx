"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import type { Job, SpendRow } from "@/lib/types";
import Link from "next/link";
import { cancelJob, enqueueGuarded, retryJob } from "@/lib/actions";
import { useSettings } from "@/lib/useSettings";
import { SettingInput } from "@/components/SettingInput";
import { PreviewApply } from "@/components/PreviewApply";
import { lastRun } from "@/lib/runnow";
import { splitArgs } from "@/lib/args";
import { SETTING_FIELDS, GROUPS } from "@/lib/settings";

// Spend meter: provider, its daily cap key, and which spend column that cap counts.
const METER: [string, string, "usd" | "units"][] = [
  ["apify", "cap_apify_usd_day", "usd"], ["serper", "cap_serper_queries_day", "units"], ["gemini", "cap_gemini_usd_day", "usd"],
  ["hunter", "cap_hunter_credits_day", "units"], ["prospeo", "cap_prospeo_credits_day", "units"], ["harvest", "cap_harvest_usd_day", "usd"],
];
const JOB_KINDS = ["scrape", "clean", "enrich", "signals", "select", "draft", "followups", "replies", "import-sheet", "verify-sheet", "sheet-queue", "sheet-paint", "recontact"];
// The sheet passes with a real dry run. Their argv pins the sheet (--sheet-id), so a preview on one sheet never unlocks Apply on another.
const SHEET_PASSES = ["import-sheet", "sheet-queue", "sheet-paint"];

export default function Settings() {
  const ready = useRequireSession();
  const { vals, reload, save, err: setErr0 } = useSettings(ready);
  const [spend, setSpend] = useState<SpendRow[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [kind, setKind] = useState("clean");
  const [argv, setArgv] = useState("");
  const [err, setErr] = useState("");
  const [recLimit, setRecLimit] = useState("5");

  const load = useCallback(async () => {
    try {
      const [sp, j] = await Promise.all([
        supabase.from("spend_summary").select("*"),
        supabase.from("jobs").select("*").order("created_at", { ascending: false }).limit(50),
      ]);
      for (const r of [sp, j]) if (r.error) throw new Error(r.error.message);
      setErr("");
      setSpend((sp.data ?? []) as SpendRow[]); setJobs((j.data ?? []) as Job[]);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const act = async (fn: () => Promise<void>) => { try { await fn(); await load(); await reload(); } catch (e) { setErr((e as Error).message); } };
  const gemini = vals.allow_paid_gemini === true;
  const sheetId = String(vals.sheet_id ?? "").trim();
  const recN = /^[1-9]\d*$/.test(recLimit.trim()) ? recLimit.trim() : "";

  return (
    <>
      <h1>Settings</h1>
      {(err || setErr0) && <p className="err">{err || setErr0}</p>}
      <p className="muted">Values shown are what the worker uses right now; a key you have never saved shows its built-in default. Changes apply within a minute.</p>
      <p className="muted">Paid Gemini is {gemini ? <span className="pill bad">allowed</span> : <span className="pill ok">off</span>}: with it off, the model passes (signals, select, draft, replies) use Groq once the Google credit ends; owner research in enrich needs Gemini and stops and pauses its job. Replies are classified with Gemini Flash-Lite, priced by the two Lite settings.</p>
      <p className="muted">The scrape walk settings (schedule, tiles, search terms) live on the <Link href="/scrape">Scrape &amp; Coverage</Link> page.</p>

      {GROUPS.map(([g, hint]) => (
        <div key={g}>
          <h2>{g}</h2>
          {hint && <p className="muted">{hint}</p>}
          <div className="grid">{SETTING_FIELDS.filter((f) => f.group === g).map((f) => <SettingInput key={f.key} f={f} vals={vals} save={save} />)}</div>
          {g === "Sheet" && (
            <>
              <p className="muted">Preview runs the dry run on the worker. Apply writes, and needs a done preview of the same run from the last 24 hours. verify-sheet (paid) runs per batch on the Batches page.</p>
              {SHEET_PASSES.map((k) => {
                const last = lastRun(jobs, k);
                const line = (last?.result as { output?: string } | null)?.output?.split("\n").find((l) => l.trim());
                return (
                  <div key={k}>
                    <PreviewApply kind={k} argv={sheetId ? ["--sheet-id", sheetId] : []} label={k}
                      disabledReason={!sheetId ? "set sheet_id first" : k === "sheet-paint" && vals.sheet_writeback_on !== true ? "turn on sheet_writeback_on" : undefined} />
                    <p className="muted">Last run: {last ? `${last.status}, ${last.created_at.slice(0, 16).replace("T", " ")}${line ? `, ${line}` : ""}` : "none in the last 50 jobs"}</p>
                  </div>
                );
              })}
            </>
          )}
          {g === "Recontact" && (
            <>
              <p className="muted">Preview is a free dry run (counts, skips, Hunter cost, allowance left). Apply verifies that many emails with Hunter and creates the leads; it needs recontact_on, a Hunter allowance and a done preview of the same lead count from the last 24 hours.</p>
              <label>Leads to recontact <input type="number" min={1} value={recLimit} onChange={(e) => setRecLimit(e.target.value)} /></label>
              <PreviewApply kind="recontact" argv={recN ? ["--limit", recN] : []} label="recontact" cost="0.5 Hunter credit per email"
                disabledReason={vals.recontact_on !== true ? "turn on recontact_on" : !recN ? "enter a lead count" : undefined} />
            </>
          )}
        </div>
      ))}

      <h2>Spend</h2>
      <table>
        <thead><tr><th>Provider</th><th>Today</th><th>Day cap</th><th>Month to date</th></tr></thead>
        <tbody>
          {METER.map(([p, capKey, col]) => {
            const r = spend.find((x) => x.provider === p);
            const today = Number(r?.[col === "usd" ? "usd_today" : "units_today"] ?? 0);
            const month = Number(r?.[col === "usd" ? "usd_month" : "units_month"] ?? 0);
            const cap = Number(vals[capKey]);
            const fmt = (n: number) => (col === "usd" ? `$${n.toFixed(2)}` : String(n));
            return (
              <tr key={p}>
                <td>{p}</td>
                <td>{fmt(today)} {cap === 0 ? <span className="pill bad">blocked</span> : today >= cap && <span className="pill bad">at cap</span>}</td>
                <td>{fmt(cap)}</td><td>{fmt(month)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>Jobs</h2>
      <div className="bar">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>{JOB_KINDS.map((k) => <option key={k}>{k}</option>)}</select>
        <input placeholder="arguments, e.g. --batch B1" value={argv} onChange={(e) => setArgv(e.target.value)} />
        <button className="primary" onClick={() => act(async () => { await enqueueGuarded(kind, splitArgs(argv)); setArgv(""); })}>Enqueue</button>
      </div>
      <table>
        <thead><tr><th>Created</th><th>Job</th><th>Status</th><th>Error</th><th></th></tr></thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id}>
              <td className="muted">{j.created_at.slice(0, 16).replace("T", " ")}</td>
              <td>{j.kind} {(j.payload.argv ?? []).join(" ")}</td>
              <td><span className={`pill ${j.status === "failed" ? "bad" : ""}`}>{j.status}</span></td>
              <td className="err">{j.error}</td>
              <td>
                {j.status === "queued" && <button onClick={() => act(() => cancelJob(j.id))}>Cancel</button>}
                {(j.status === "failed" || j.status === "paused_budget") && <button onClick={() => act(() => retryJob(j.id))}>Retry</button>}
              </td>
            </tr>
          ))}
          {!jobs.length && <tr><td colSpan={5} className="muted">No jobs yet.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
