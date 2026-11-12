"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import type { Job, SpendRow } from "@/lib/types";
import { cancelJob, enqueueJob, retryJob, saveSetting } from "@/lib/actions";
import { splitArgs } from "@/lib/args";
import { SETTING_FIELDS, type SettingField } from "@/lib/settings";

// Defaults mirror gtm/settings_store.py so an unset key shows what the worker will use.
const DEFAULTS: Record<string, unknown> = {
  monthly_budget_pkr: 25000, pkr_per_usd: 276, weekly_target: 200, allow_paid_gemini: false, paid_gemini_monthly_cap_usd: 0,
  credit_end_date: "2027-02-09", credit_balance_usd: 298, credit_balance_as_of: "2026-11-12",
  gemini_input_usd_per_m: 1.5, gemini_output_usd_per_m: 9.0,
  cap_apify_usd_day: 2.0, cap_serper_queries_day: 700, cap_gemini_usd_day: 5.0,
  cap_hunter_credits_day: 100, cap_prospeo_credits_day: 20, cap_harvest_usd_day: 0.5,
};
const GROUPS = ["Budget", "Google credit", "API prices", "Daily caps"];
// Spend meter: provider, its daily cap key, and which spend column that cap counts.
const METER: [string, string, "usd" | "units"][] = [
  ["apify", "cap_apify_usd_day", "usd"], ["serper", "cap_serper_queries_day", "units"], ["gemini", "cap_gemini_usd_day", "usd"],
  ["hunter", "cap_hunter_credits_day", "units"], ["prospeo", "cap_prospeo_credits_day", "units"], ["harvest", "cap_harvest_usd_day", "usd"],
];
const JOB_KINDS = ["scrape", "clean", "enrich", "signals", "select", "draft", "followups", "replies"];

export default function Settings() {
  const ready = useRequireSession();
  const [vals, setVals] = useState<Record<string, unknown>>(DEFAULTS);
  const [spend, setSpend] = useState<SpendRow[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [kind, setKind] = useState("clean");
  const [argv, setArgv] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [s, sp, j] = await Promise.all([
        supabase.from("settings").select("key,value"),
        supabase.from("spend_summary").select("*"),
        supabase.from("jobs").select("*").order("created_at", { ascending: false }).limit(50),
      ]);
      for (const r of [s, sp, j]) if (r.error) throw new Error(r.error.message);
      setErr("");
      setVals({ ...DEFAULTS, ...Object.fromEntries((s.data ?? []).map((r) => [r.key, r.value])) });
      setSpend((sp.data ?? []) as SpendRow[]); setJobs((j.data ?? []) as Job[]);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const act = async (fn: () => Promise<void>) => { try { await fn(); await load(); } catch (e) { setErr((e as Error).message); } };
  const save = (f: SettingField, raw: string | boolean) =>
    act(() => saveSetting(f.key, f.type === "int" || f.type === "float" ? (raw === "" ? NaN : Number(raw)) : raw));
  const field = (f: SettingField) => (
    <label className="card" key={f.key}>
      <div className="muted">{f.label}</div>
      {f.type === "bool" ? (
        <input type="checkbox" checked={vals[f.key] === true} onChange={(e) => save(f, e.target.checked)} />
      ) : (
        // key remounts the uncontrolled input after a save so it shows the stored value
        <input key={String(vals[f.key])} type={f.type === "date" ? "date" : "number"} step={f.type === "float" ? "any" : 1}
          defaultValue={String(vals[f.key])} onBlur={(e) => e.target.value !== String(vals[f.key]) && save(f, e.target.value)} />
      )}
    </label>
  );
  const gemini = vals.allow_paid_gemini === true;

  return (
    <>
      <h1>Settings</h1>
      {err && <p className="err">{err}</p>}
      <p className="muted">Paid Gemini is {gemini ? <span className="pill bad">allowed</span> : <span className="pill ok">off</span>}: with it off, the LLM passes (signals, select, draft, replies) use Groq, and only the owner-research step of enrich, which needs Gemini, stops and pauses the job.</p>

      {GROUPS.map((g) => (
        <div key={g}>
          <h2>{g}</h2>
          <div className="grid">{SETTING_FIELDS.filter((f) => f.group === g).map(field)}</div>
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
        <button className="primary" onClick={() => act(async () => { await enqueueJob(kind, splitArgs(argv)); setArgv(""); })}>Enqueue</button>
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
