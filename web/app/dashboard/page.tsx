"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import { fetchAll } from "@/lib/fetchAll";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { batchBase, fillLabel, loadBatchNos, type BatchNoRow } from "@/lib/batches";
import { COLS, DASH_LEAD_SELECT, batchLabel, costRows, dashboardRows, pct, type DashLead, type Funnel } from "@/lib/dashboard";
import type { BatchMetrics } from "@/lib/types";

type Counts = Record<string, number>;

// The scrape-run table (one row per run, from the batch_metrics view). Kept as detail under the batch table.
const STAGES: { key: string; label: string; hint: string }[] = [
  { key: "scraped", label: "Scraped", hint: "places from Google Maps" },
  { key: "cleaned", label: "Kept", hint: "passed the cleaning rules" },
  { key: "enriched", label: "Verified email", hint: "named decision-maker, verified address" },
  { key: "signalled", label: "Judged", hint: "evidence pass ran" },
  { key: "signal_led", label: "Dated signal", hint: "a current, sourced signal" },
  { key: "drafted", label: "Drafted", hint: "Touch 1 in Gmail Drafts" },
  { key: "sent", label: "Sent", hint: "Touch 1 sent" },
  { key: "bounced", label: "Bounced", hint: "" },
  { key: "replied", label: "Replied", hint: "any real reply, incl. opt-outs" },
  { key: "positive", label: "Positive", hint: "marked by you, or booked" },
  { key: "booked", label: "Booked", hint: "marked by you" },
];
const money = (n: number | null) => (n == null ? "n/a" : `$${Number(n).toFixed(Number(n) < 0.1 ? 4 : 2)}`);
const num = (n: number | null) => (n == null ? "n/a" : Number(n).toFixed(2));

function Cells({ row }: { row: Counts }) {
  return (
    <>
      {STAGES.map((s, i) => {
        const v = row[s.key];
        const prev = i === 0 ? 0 : row[STAGES[i - 1].key];
        return (
          <td key={s.key}>
            {v}
            {prev ? <span className="muted"> {Math.round((100 * v) / prev)}%</span> : null}
          </td>
        );
      })}
    </>
  );
}

function FunnelCells({ f }: { f: Funnel }) {
  return (
    <>
      {COLS.map((c) => {
        const p = c.of ? pct(f[c.key], f[c.of]) : null;
        return <td key={c.key}>{f[c.key]}{p && <span className="muted"> {p}</span>}</td>;
      })}
    </>
  );
}

export default function Dashboard() {
  const ready = useRequireSession();
  const { vals } = useSettings(ready);
  const [leads, setLeads] = useState<DashLead[]>([]);
  const [nos, setNos] = useState<BatchNoRow[]>([]);
  const [rows, setRows] = useState<BatchMetrics[]>([]);
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!ready) return;
    Promise.all([
      fetchAll<DashLead>((f, t) => supabase.from("leads").select(DASH_LEAD_SELECT).order("id").range(f, t)),
      loadBatchNos(),
      supabase.from("batch_metrics").select("*").order("created_at", { ascending: false }),
    ]).then(([l, n, m]) => {
      if (m.error) throw new Error(m.error.message);
      setLeads(l); setNos(n); setRows((m.data ?? []) as unknown as BatchMetrics[]);
    }).catch((e) => setErr((e as Error).message)).finally(() => setLoaded(true));
  }, [ready]);

  const d = useMemo(() => dashboardRows(leads), [leads]);
  const cost = useMemo(() => costRows(d.batches, nos), [d, nos]);
  if (!ready) return null;

  const base = batchBase(vals.batch_base);
  const runs = rows.filter((r) => r.scraped > 0);
  const counts = (r: BatchMetrics) => r as unknown as Counts;
  const all: Counts = Object.fromEntries(STAGES.map((s) => [s.key, runs.reduce((a, r) => a + Number(counts(r)[s.key] ?? 0), 0)]));
  const otherText = Object.entries(d.other).sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${s}`).join(", ");

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">
        One row per outreach batch of 100 (Batch 03 and later; earlier batches are not in the OS). The small percentage is the share of the column named in the header hint:
        sent is of drafted, bounced and replied are of sent, positive is of replied.
      </p>
      {err && <p className="err">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Batch</th>
            {COLS.map((c) => (
              <th key={c.key} title={[c.hint, c.of && `share of ${COLS.find((x) => x.key === c.of)!.label.toLowerCase()}`].filter(Boolean).join("; ") || undefined}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {d.batches.map((b) => (
            <tr key={b.batch_no}>
              <td>{batchLabel(b.batch_no)}</td>
              <FunnelCells f={b.f} />
            </tr>
          ))}
          <tr title="Leads with no batch number that are cleaned or further on, plus any sent or replied lead that was never numbered">
            <td>In the pipeline, not yet in a batch</td>
            <FunnelCells f={d.pipeline} />
          </tr>
          <tr>
            <td><strong>All</strong></td>
            <FunnelCells f={d.all} />
          </tr>
        </tbody>
      </table>
      {Object.entries(base).map(([n, b]) => {
        const r = d.batches.find((x) => x.batch_no === Number(n));
        return (
          <p className="muted" key={n}>
            {batchLabel(Number(n))} also holds {b} leads outside the OS (Notion). They are not in the counts above{r && `; counting them the batch is ${fillLabel({ leads: r.f.leads }, b)}`}.
          </p>
        );
      })}
      {otherText && <p className="muted">Not in the table, not in play: {otherText} (scraped, rejected by the cleaning rules, no verified owner, or suppressed).</p>}
      {loaded && !err && d.batches.length === 0 && <p className="muted">No batch numbers yet: leads get one when select picks them.</p>}

      <h2>Cost per batch</h2>
      <table>
        <thead>
          <tr>
            <th>Batch</th><th>Apify</th><th>Gemini</th><th>Hunter credits</th><th>Prospeo credits</th><th>Serper queries</th>
            <th title="Apify plus Gemini dollars, divided by enriched leads">Per enriched lead</th>
            <th title="Apify plus Gemini dollars, divided by replies">Per reply</th>
          </tr>
        </thead>
        <tbody>
          {[...cost.rows, ...(cost.rows.length > 1 ? [cost.all] : [])].map((r) => (
            <tr key={r.batch_no ?? "all"}>
              <td>{r.batch_no == null ? <strong>All batches</strong> : batchLabel(r.batch_no)}</td>
              <td>{money(r.apify_usd)}</td><td>{money(r.gemini_usd)}</td><td>{r.hunter_credits}</td><td>{r.prospeo_credits}</td><td>{r.serper_queries}</td>
              <td>{money(r.perEnriched)}</td><td>{money(r.perReply)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Spend recorded against the leads of each batch (enrich, signals, drafts). Dollars are Apify and Gemini; Hunter, Prospeo and Serper are logged in credits or queries and are not priced, so they are not in the per-lead and per-reply figures.
        Scrape-time Apify is logged per scrape run, and spend on leads that never reached a batch has no batch: neither is here (scrape runs are below).
      </p>

      <details>
        <summary><h2 style={{ display: "inline" }}>Scrape runs (detail)</h2></summary>
        <p className="muted">One row per scrape run with at least one place scraped. The small percentage is the share of the previous column. Hunter is shown in credits until a plan is priced.</p>
        <table>
          <thead>
            <tr>
              <th>Run</th>
              {STAGES.map((s) => (
                <th key={s.key} title={s.hint}>{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.batch_id}>
                <td>{r.name}</td>
                <Cells row={counts(r)} />
              </tr>
            ))}
            {runs.length > 1 && (
              <tr>
                <td><strong>All scrape runs</strong></td>
                <Cells row={all} />
              </tr>
            )}
          </tbody>
        </table>
        <h3>Scrape-run cost</h3>
        <table>
          <thead>
            <tr>
              <th>Run</th><th>Apify</th><th>Apify per lead</th><th>Apify per verified email</th>
              <th>Hunter credits</th><th>Hunter credits per verified email</th><th>Search queries</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.batch_id}>
                <td>{r.name}</td>
                <td>{money(r.apify_usd)}</td>
                <td>{money(r.apify_usd_per_lead)}</td>
                <td>{money(r.apify_usd_per_verified_email)}</td>
                <td>{r.hunter_credits}</td>
                <td>{num(r.hunter_credits_per_verified_email)}</td>
                <td>{r.serper_queries}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loaded && runs.length === 0 && !err && <p className="muted">No scrape runs yet: <code>uv run python -m gtm.cli scrape --city … --state …</code></p>}
      </details>
    </>
  );
}
