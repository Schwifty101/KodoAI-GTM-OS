"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { PreviewApply } from "@/components/PreviewApply";
import { autopilotSpent, enqueueJobOnce, pauseAutopilot, startAutopilot } from "@/lib/actions";
import { baseKind, stepState, type JobRow } from "@/lib/runnow";
import type { BatchMetrics, SpendRow } from "@/lib/types";
import {
  BATCH_SIZE, INTAKE_ORDER, SHEET_ORDER, STEP_INPUT, batchBase, batchCards, countByStatus, creditState, doneJobs, isEmptyRun, isSheetBatch, limitInputs, loadBatchJobs,
  loadBatchSpend, loadOutreachBatches, loadRetryCandidates, retryLater, retryWhy, stepOpen, type BatchCard, type RetryRow,
} from "@/lib/batches";

const money = (n: number) => `$${n.toFixed(n < 0.1 ? 4 : 2)}`;
const pad = (n: number) => String(n).padStart(2, "0");
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Confirm texts per step: each names the run and the lead count; none states a price that is not confirmed (docs/spikes/owner_routes.md). */
const STEP_TEXT: Record<string, (label: string, n: number, caps: string) => string> = {
  clean: (l, n) => `Clean ${l}: ${n} scraped leads. Continue?`,
  enrich: (l, n, caps) => `Enrich ${l}: ${n} cleaned leads. Hunter and Prospeo charge 1 credit per email found (no price per lead is confirmed, see docs/spikes/owner_routes.md); the research finder also spends Serper searches and Gemini tokens. Credits used today: ${caps}. The daily caps stop the run. Type ${n} to confirm.`,
  signals: (l, n) => `Signals for ${l}: ${n} enriched leads. This spends Gemini and page-fetch budget within the daily caps. Continue?`,
  select: (l, n) => `Select for ${l}: ${n} signalled leads. This calls Gemini for each chosen lead and numbers the chosen leads into the open batch of ${BATCH_SIZE}. Continue?`,
};

/** The pipeline row of one intake run. A step is greyed until the previous one has a done job for this run (reason on hover); every click re-counts the leads it will touch. */
function IntakeSteps({ run, jobs, caps, onErr, onQueued }: { run: BatchMetrics; jobs: JobRow[]; caps: string; onErr: (m: string) => void; onQueued: () => void }) {
  const [busy, setBusy] = useState(false);
  const sheet = isSheetBatch(run.name);
  const order = sheet ? SHEET_ORDER : INTAKE_ORDER;
  const label = `${run.name} (${run.created_at.slice(0, 10)})`;
  // The walk cleans its own leads inside the walk job, so a scrape run has no `clean` job: leads past clean (cleaned or enriched > 0) count as clean done.
  const cleanSeen: JobRow[] = run.cleaned > 0 || run.enriched > 0
    ? [{ id: `clean-seen-${run.batch_id}`, kind: "clean", status: "done", payload: { argv: ["--batch", run.batch_id] }, result: null, error: null, created_at: run.created_at, finished_at: run.created_at }]
    : [];
  const done = [...doneJobs(jobs), ...cleanSeen];
  const click = async (step: string) => {
    setBusy(true); onErr("");
    try {
      const n = await countByStatus(run.batch_id, STEP_INPUT[step]);
      if (n === 0) throw new Error(`${label} has no ${STEP_INPUT[step]} leads for ${step}`);
      if (step === "enrich") { // no dry run exists: the owner types the lead count
        const typed = window.prompt(STEP_TEXT[step](label, n, caps));
        if (typed === null) return;
        if (typed.trim() !== String(n)) throw new Error("the typed count did not match: nothing queued");
      } else if (!window.confirm(STEP_TEXT[step](label, n, caps))) return;
      await enqueueJobOnce(step, ["--batch", run.batch_id]);
      onQueued();
    } catch (e) { onErr((e as Error).message); } finally { setBusy(false); }
  };
  const last = (step: string) => jobs.find((j) => baseKind(j.kind) === step && (j.payload?.argv ?? []).includes(run.batch_id)); // jobs are newest first
  const button = (step: string) => {
    const st = stepState(order, step, done, run.batch_id, sheet);
    const open = stepOpen(jobs, step, run.batch_id), j = last(step);
    return (
      <span key={step}>
        <span title={st.enabled ? undefined : st.why}><button disabled={busy || open || !st.enabled} onClick={() => click(step)}>{step[0].toUpperCase() + step.slice(1)}</button></span>
        {j && <> <span className={`pill ${j.status === "done" ? "ok" : j.status === "failed" ? "bad" : ""}`} title={j.error ?? undefined}>{j.status}</span></>}
      </span>
    );
  };
  const vs = sheet ? stepState(order, "verify-sheet", done, run.batch_id, true) : undefined;
  return (
    <div className="bar">
      {button("clean")}
      {vs && <PreviewApply kind="verify-sheet" argv={["--batch", run.batch_id]} label="verify-sheet" cost="0.5 Hunter credit per email" disabledReason={vs.enabled ? undefined : vs.why} jobs={jobs} />}
      {button("enrich")}{button("signals")}{button("select")}
    </div>
  );
}

export default function Batches() {
  const ready = useRequireSession();
  const { vals, reload } = useSettings(ready);
  const defaultVals = useRef(vals); // useSettings starts on the built-in defaults and swaps in a new object once the stored settings arrive
  const [limitEdit, setLimitEdit] = useState<string | null>(null); // null = not touched: the input follows the stored autopilot_limit_usd
  const [noLimitEdit, setNoLimitEdit] = useState<boolean | null>(null);
  const [showEmpty, setShowEmpty] = useState(false);
  const [spent, setSpent] = useState<number | null>(null);
  const [cards, setCards] = useState<BatchCard[]>([]);
  const [runs, setRuns] = useState<BatchMetrics[]>([]);
  const [retry, setRetry] = useState<RetryRow[]>([]);
  const [spend, setSpend] = useState<SpendRow[]>([]);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  const baseJson = JSON.stringify(vals.batch_base ?? {}); // key effects on the value: useSettings hands out a new object on every reload
  const load = useCallback(async () => {
    try {
      const [bs, o, rt, m, sp, j] = await Promise.all([
        loadBatchSpend(), loadOutreachBatches(batchBase(JSON.parse(baseJson))), loadRetryCandidates(),
        supabase.from("batch_metrics").select("*").order("created_at", { ascending: false }),
        supabase.from("spend_summary").select("*"),
        loadBatchJobs(),
      ]);
      for (const r of [m, sp]) if (r.error) throw new Error(r.error.message);
      setErr(""); setCards(batchCards(o, bs)); setRetry(rt);
      setRuns((m.data ?? []) as unknown as BatchMetrics[]); setSpend((sp.data ?? []) as SpendRow[]); setJobs(j);
    } catch (e) { setErr((e as Error).message); }
    setLoaded(true);
  }, [baseJson]);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  const stepsBusy = jobs.some((j) => j.status === "queued" || j.status === "running");
  const refreshJobs = useCallback(() => loadBatchJobs().then(setJobs, (e) => setErr((e as Error).message)), []);
  useEffect(() => { // a queued or running step: keep the row (and the gate of the next step) current until it ends
    if (!ready || !stepsBusy) return;
    const t = setInterval(refreshJobs, 5000);
    return () => clearInterval(t);
  }, [ready, stepsBusy, refreshJobs]);
  const startedAt = String(vals.autopilot_started_at ?? "");
  useEffect(() => {
    if (!ready || !startedAt) return setSpent(null);
    const tick = () => autopilotSpent(startedAt).then(setSpent, () => setSpent(null));
    tick();
    if (vals.autopilot_on !== true) return;
    const t = setInterval(tick, 30_000);
    return () => clearInterval(t);
  }, [ready, startedAt, vals.autopilot_on]);
  if (!ready) return null;

  const apOn = vals.autopilot_on === true;
  const apLimit = Number(vals.autopilot_limit_usd ?? 0);
  const apRun = async (fn: () => Promise<void>) => {
    try { await fn(); await reload(); setErr(""); } catch (e) { setErr((e as Error).message); }
  };
  const settingsLoaded = vals !== defaultVals.current; // until then the limit shown is the built-in default, not the owner's
  const stored = limitInputs(apLimit);
  const limit = limitEdit ?? stored.limit, noLimit = noLimitEdit ?? stored.noLimit;
  const apStart = () => apRun(() => startAutopilot(noLimit ? 0 : Number(limit)));

  const credits = creditState(spend, vals);
  const allBlocked = credits.every((c) => c.blocked);
  const capsText = credits.map((c) => `${c.provider} ${c.today} of ${c.cap}`).join(", ");
  const named = new Map(retry.map((r) => [r.batch_id, r]));
  const runName = new Map(runs.map((r) => [r.batch_id, r.name])); // the owner reads run names, never ids
  const newest = cards[0]?.batch_no ?? 0; // the open batch is the highest number, base included (gtm/autopilot.py); cards are newest first
  const emptyRuns = runs.filter((r) => isEmptyRun(r, jobs)).length;
  const shownRuns = showEmpty ? runs : runs.filter((r) => !isEmptyRun(r, jobs));

  const go = async (batchId: string, n: number) => {
    if (!window.confirm(`This spends Hunter and Prospeo credits on ${n} leads. Continue?`)) return;
    try { await retryLater(batchId); await load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <>
      <h1>Batches</h1>
      <p className="muted">A batch is {BATCH_SIZE} verified, selected owners (numbered when a lead becomes selected, never renumbered). Leads that are scraped but not yet selected belong to a scrape run or the sheet import, listed under Scrape runs and retries.</p>
      {err && <p className="err">{err}</p>}

      <h2>Outreach batches</h2>
      {!loaded ? <p className="muted">Loading…</p> : cards.length === 0 ? <p className="muted">No batch numbers yet: leads get one when select picks them.</p> : (
        <>
          <div className="grid">{cards.map((b) => (
            <div className="card" key={b.batch_no}>
              <h3>Batch {pad(b.batch_no)}: {b.leads} of {BATCH_SIZE} {b.batch_no === newest && b.leads < BATCH_SIZE && <span className="pill">open</span>}</h3>
              <p>{b.selected} selected ({b.approved} approved), {b.drafted} drafted, {b.sent} sent, {b.replied} replied</p>
              <p className="muted">
                Spend recorded: Apify {money(b.apify_usd)}, Gemini {money(b.gemini_usd)}, Hunter {count(b.hunter_credits, "credit")},
                Prospeo {count(b.prospeo_credits, "credit")}, Serper {count(b.serper_queries, "query", "queries")}
              </p>
              {b.base > 0 && <p className="muted">{b.base} of these are already in the batch outside the OS (Notion).</p>}
            </div>
          ))}</div>
          <p className="muted">Spend is what was recorded against these leads (enrich, signals, drafts). Scrape-time Apify cost is per scrape run, under Scrape runs and retries.</p>
        </>
      )}

      <div className="card">
        <h2>Autopilot</h2>
        <p>
          {String(vals.autopilot_state ?? "off")} {apOn ? <span className="pill">on</span> : <span className="pill bad">off</span>}
        </p>
        <p>
          Spent {spent === null ? "-" : money(spent)} of {apLimit === 0 ? "no limit" : money(apLimit)}{startedAt && ` since ${startedAt.slice(0, 16).replace("T", " ")}`}
        </p>
        <p>
          <label>Limit (USD) <input type="number" min="0" step="0.5" value={limit} disabled={noLimit} onChange={(e) => setLimitEdit(e.target.value)} /></label>{" "}
          <label><input type="checkbox" checked={noLimit} onChange={(e) => setNoLimitEdit(e.target.checked)} /> No limit</label>{" "}
          <span title={settingsLoaded ? undefined : "Settings are still loading"}>
            <button disabled={!settingsLoaded || (!noLimit && (limit === "" || Number(limit) < 0))} onClick={apStart}>{startedAt ? "Start / Resume" : "Start"}</button>
          </span>{" "}
          <button disabled={!apOn} onClick={() => apRun(pauseAutopilot)}>Pause</button>
        </p>
        <p className="muted">The limit counts Apify and Gemini dollars only; Hunter, Serper and Prospeo log credits and are bounded by their daily caps. Resume starts the spend count again from now. Autopilot never approves leads or sends.</p>
      </div>

      <details>
        <summary><h2 style={{ display: "inline" }}>Scrape runs and retries</h2></summary>
        <h3>Intake: scrape and import runs ({shownRuns.length})</h3>
        <p className="muted">The pass buttons take one intake run at a time. A step is greyed until the step before it has a finished job for that run; hover for the reason.</p>
        {!loaded ? <p className="muted">Loading…</p> : shownRuns.length === 0 ? <p className="muted">No intake runs with leads yet.</p> : (
          <table>
            <thead><tr><th>Run</th><th>Created</th><th>Scraped</th><th>Cleaned</th><th>Enriched</th><th>Apify</th><th>Hunter credits</th><th>Owner known, email not verified</th></tr></thead>
            <tbody>{shownRuns.map((r) => {
              const c = named.get(r.batch_id);
              return (
                <Fragment key={r.batch_id}>
                  <tr>
                    <td>{r.name}</td><td>{r.created_at.slice(0, 10)}</td><td>{r.scraped}</td><td>{r.cleaned}</td><td>{r.enriched}</td>
                    <td>{money(Number(r.apify_usd))}</td><td>{r.hunter_credits}</td>
                    <td>{c?.named ?? 0} {c && c.unnamed > 0 && <span className="muted">({c.unnamed} no owner found, parked)</span>}</td>
                  </tr>
                  <tr><td colSpan={8}><IntakeSteps run={r} jobs={jobs} caps={capsText} onErr={setErr} onQueued={refreshJobs} /></td></tr>
                </Fragment>
              );
            })}</tbody>
          </table>
        )}
        {emptyRuns > 0 && <p><button onClick={() => setShowEmpty(!showEmpty)}>{showEmpty ? "hide" : "show"} {count(emptyRuns, "empty run")}</button> <span className="muted">no leads and no jobs</span></p>}

        <div className="card">
          <h3>Retry later</h3>
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
            const why = retryWhy(jobs, r.batch_id, r.named, allBlocked);
            return (
              <p key={r.batch_id}>
                {r.name}: <button disabled={!!why} onClick={() => go(r.batch_id, r.named)}>Retry later ({r.named} leads)</button>
                {why && <span className="muted"> {why}</span>}
              </p>
            );
          })}
          <h4>Last 5 enrich jobs</h4>
          {jobs.every((j) => j.kind !== "enrich") ? <p className="muted">None.</p> : (
            <table><thead><tr><th>Created</th><th>Args</th><th>Status</th><th>Error</th></tr></thead>
              <tbody>{jobs.filter((j) => j.kind === "enrich").slice(0, 5).map((j) => (
                <tr key={j.id}><td>{j.created_at.slice(0, 16).replace("T", " ")}</td><td><code>{(j.payload.argv ?? []).map((a) => runName.get(a) ?? a).join(" ")}</code></td><td>{j.status}</td><td>{j.error ?? ""}</td></tr>
              ))}</tbody></table>
          )}
          <p className="muted">A retry that stops on credits shows its result counts in the Jobs panel of Settings.</p>
        </div>
      </details>
    </>
  );
}
