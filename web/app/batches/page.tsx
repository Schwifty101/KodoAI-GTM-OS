"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { STATUSES, type BatchMetrics, type Job, type SpendRow } from "@/lib/types";
import { BATCH_SIZE, creditState, fillLabel, loadBatchNos, loadRetryCandidates, retryLater, retryOpen, type BatchNoRow, type RetryRow } from "@/lib/batches";

const money = (n: number) => `$${n.toFixed(n < 0.1 ? 4 : 2)}`;

export default function Batches() {
  const ready = useRequireSession();
  const { vals } = useSettings(ready);
  const [nos, setNos] = useState<BatchNoRow[]>([]);
  const [runs, setRuns] = useState<BatchMetrics[]>([]);
  const [retry, setRetry] = useState<RetryRow[]>([]);
  const [spend, setSpend] = useState<SpendRow[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const [n, rt, m, sp, j] = await Promise.all([
        loadBatchNos(), loadRetryCandidates(),
        supabase.from("batch_metrics").select("*").order("created_at", { ascending: false }),
        supabase.from("spend_summary").select("*"),
        supabase.from("jobs").select("*").eq("kind", "enrich").order("created_at", { ascending: false }).limit(50),
      ]);
      for (const r of [m, sp, j]) if (r.error) throw new Error(r.error.message);
      setErr(""); setNos(n); setRetry(rt);
      setRuns((m.data ?? []) as unknown as BatchMetrics[]); setSpend((sp.data ?? []) as SpendRow[]); setJobs((j.data ?? []) as Job[]);
    } catch (e) { setErr((e as Error).message); }
    setLoaded(true);
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const credits = creditState(spend, vals);
  const allBlocked = credits.every((c) => c.blocked);
  const named = new Map(retry.map((r) => [r.batch_id, r]));
  const cols = STATUSES.filter((s) => nos.some((r) => r.byStatus[s]));
  const newest = nos[0]?.batch_no;

  const go = async (batchId: string, n: number) => {
    if (!window.confirm(`This spends Hunter and Prospeo credits on ${n} leads. Continue?`)) return;
    try { await retryLater(batchId); await load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <>
      <h1>Batches</h1>
      <p className="muted">A batch is {BATCH_SIZE} verified, selected owners (numbered when a lead becomes selected, never renumbered). Leads that are scraped but not yet selected belong to a scrape run, listed below.</p>
      {err && <p className="err">{err}</p>}

      <h2>Batches of {BATCH_SIZE}</h2>
      {!loaded ? <p className="muted">Loading…</p> : nos.length === 0 ? <p className="muted">No batch numbers yet: leads get one when select picks them.</p> : (
        <table>
          <thead><tr><th>Batch</th><th>Filled</th>{cols.map((s) => <th key={s}>{s}</th>)}<th>Apify</th><th>Hunter credits</th><th>Prospeo credits</th><th>Serper</th><th>Gemini</th></tr></thead>
          <tbody>{nos.map((r) => (
            <tr key={r.batch_no}>
              <td>{r.batch_no}</td>
              <td>{fillLabel(r)} {r.batch_no === newest && r.leads < BATCH_SIZE && <span className="pill">open</span>}</td>
              {cols.map((s) => <td key={s}>{r.byStatus[s] ?? 0}</td>)}
              <td>{money(r.apify_usd)}</td><td>{r.hunter_credits}</td><td>{r.prospeo_credits}</td><td>{r.serper_queries}</td><td>{money(r.gemini_usd)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <p className="muted">Spend here is what was recorded against these leads (enrich, signals, drafts). Scrape-time Apify cost is per scrape run, below.</p>

      <h2>Scrape runs</h2>
      {!loaded ? <p className="muted">Loading…</p> : runs.length === 0 ? <p className="muted">No scrape runs yet.</p> : (
        <table>
          <thead><tr><th>Run</th><th>Created</th><th>Scraped</th><th>Cleaned</th><th>Enriched</th><th>Apify</th><th>Hunter credits</th><th>Owner known, email not verified</th></tr></thead>
          <tbody>{runs.map((r) => {
            const c = named.get(r.batch_id);
            return (
              <tr key={r.batch_id}>
                <td>{r.name}</td><td>{r.created_at.slice(0, 10)}</td><td>{r.scraped}</td><td>{r.cleaned}</td><td>{r.enriched}</td>
                <td>{money(Number(r.apify_usd))}</td><td>{r.hunter_credits}</td>
                <td>{c?.named ?? 0} {c && c.unnamed > 0 && <span className="muted">({c.unnamed} no owner found, parked)</span>}</td>
              </tr>
            );
          })}</tbody>
        </table>
      )}

      <div className="card">
        <h2>Retry later</h2>
        <p>
          {credits.map((c) => (
            <span key={c.provider}>{c.provider} {c.today} of {c.cap} today, {c.month} this month {c.blocked && <span className="pill bad">blocked</span>}{" "}</span>
          ))}
        </p>
        <p className="muted">
          Retry later re-runs the finders for leads whose owner name is known but whose email could not be verified. It spends Hunter and Prospeo credits
          (each finder call costs 1 credit only when it finds an email; Prospeo no-match is free; no per-lookup price beyond that is confirmed, see docs/spikes/owner_routes.md)
          and stops by itself when a provider runs out or hits its daily cap. A saved email is never erased. The run also picks up any leads of that scrape run that are cleaned but not yet enriched. Nothing runs until you click.
        </p>
        {loaded && retry.filter((r) => r.named > 0).length === 0 && <p className="muted">Nothing to retry: no scrape run has a known owner without a verified email.</p>}
        {retry.map((r) => {
          const open = retryOpen(jobs, r.batch_id);
          const why = r.named === 0 ? "no named owners" : open ? "already queued or running" : allBlocked ? "Hunter and Prospeo are both blocked" : "";
          return (
            <p key={r.batch_id}>
              {r.name}: <button disabled={!!why} onClick={() => go(r.batch_id, r.named)}>Retry later ({r.named} leads)</button>
              {why && <span className="muted"> {why}</span>}
            </p>
          );
        })}
        <h3>Last 5 enrich jobs</h3>
        {jobs.length === 0 ? <p className="muted">None.</p> : (
          <table><thead><tr><th>Created</th><th>Args</th><th>Status</th><th>Error</th></tr></thead>
            <tbody>{jobs.slice(0, 5).map((j) => (
              <tr key={j.id}><td>{j.created_at.slice(0, 16).replace("T", " ")}</td><td><code>{(j.payload.argv ?? []).join(" ")}</code></td><td>{j.status}</td><td>{j.error ?? ""}</td></tr>
            ))}</tbody></table>
        )}
        <p className="muted">A retry that stops on credits shows its result counts in the Jobs panel of Settings.</p>
      </div>
    </>
  );
}
