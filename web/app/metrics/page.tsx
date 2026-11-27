"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import { fetchAll } from "@/lib/fetchAll";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { batchBase, fillLabel, loadBatchNos, type BatchNoRow } from "@/lib/batches";
import { COLS, DASH_LEAD_SELECT, batchLabel, costRows, dashboardRows, pct, type DashLead, type Funnel } from "@/lib/dashboard";
import type { BatchMetrics } from "@/lib/types";
import {
  addSpend, allocateSpend, batchRows, byAngle, hint0017, historyRows, isTestLead, perUnit, previousRange, pricedUsd, spendFrom, undatedCounts, whereLeadsDie,
  type CostDay, type Grain, type HistoryRow, type LeadRow, type Prices, type Spend, type TouchRow,
} from "@/lib/metrics";
import { loadMetricsData } from "@/lib/metricsData";
import { defaultFrom, kOf, money, spendText } from "@/lib/metricsFormat";

type Counts = Record<string, number>;

// The scrape-run table (one row per run, from the batch_metrics view). Kept as detail at the bottom.
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
const num = (n: number | null) => (n == null ? "n/a" : Number(n).toFixed(2));
const today = () => new Date().toISOString().slice(0, 10);
const isDate = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v);
const H_COLS = ["scraped", "owners", "touch1", "followups", "bounces", "replies", "booked"] as const;
const H_LABELS = ["Scraped", "Verified owners", "Touch 1 sent", "Follow-ups sent", "Bounces", "Replies", "Booked"];
const total = (rows: HistoryRow[]): HistoryRow => rows.reduce((a, r) => {
  for (const k of H_COLS) a[k] += r[k];
  a.spend = addSpend(a.spend, r.spend);
  return a;
}, { start: "", scraped: 0, owners: 0, touch1: 0, followups: 0, bounces: 0, replies: 0, booked: 0, spend: {} } as HistoryRow);
type Data = { leads: LeadRow[]; touches: TouchRow[]; costs: CostDay[] };

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

export default function Metrics() {
  const ready = useRequireSession();
  const { vals } = useSettings(ready);
  const [leads, setLeads] = useState<DashLead[]>([]);
  const [nos, setNos] = useState<BatchNoRow[]>([]);
  const [rows, setRows] = useState<BatchMetrics[]>([]);
  const [data, setData] = useState<Data>({ leads: [], touches: [], costs: [] });
  const [err, setErr] = useState("");
  const [mErr, setMErr] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [mLoaded, setMLoaded] = useState(false);
  const [grain, setGrain] = useState<Grain>("week");
  const [to, setTo] = useState(today);
  const [from, setFrom] = useState(() => defaultFrom("week", today()));
  const [angleBatch, setAngleBatch] = useState("");

  useEffect(() => {
    if (!ready) return;
    Promise.all([
      fetchAll<DashLead>((f, t) => supabase.from("leads").select(DASH_LEAD_SELECT).order("id").range(f, t)),
      loadBatchNos(),
      supabase.from("batch_metrics").select("*").order("created_at", { ascending: false }),
    ]).then(([l, n, m]) => {
      if (m.error) throw new Error(m.error.message);
      setLeads(l); setNos(n); setRows((m.data ?? []) as unknown as BatchMetrics[]);
    }).catch((e) => setErr(hint0017((e as Error).message))).finally(() => setLoaded(true));
  }, [ready]);

  // Separate from the funnel load so the funnel still shows while migration 0017 is not applied.
  useEffect(() => {
    if (!ready) return;
    loadMetricsData().then(setData).catch((e) => setMErr(hint0017((e as Error).message))).finally(() => setMLoaded(true));
  }, [ready]);

  const d = useMemo(() => dashboardRows(leads.filter((l) => !isTestLead(l.place_id ?? ""))), [leads]);
  const cost = useMemo(() => costRows(d.batches, nos), [d, nos]);
  const alloc = useMemo(() => allocateSpend(data.costs, data.leads), [data]);
  const rangeOk = isDate(from) && isDate(to) && from <= to;
  const hist = useMemo(() => {
    if (!rangeOk) return null;
    const prev = previousRange(from, to);
    return { prev, rows: historyRows({ ...data, grain, from, to }), prevRows: historyRows({ ...data, grain, from: prev.from, to: prev.to }) };
  }, [data, grain, from, to, rangeOk]);
  if (!ready) return null;

  const base = batchBase(vals.batch_base);
  const prices: Prices = {
    hunter: Number(vals.price_hunter_usd_per_credit) || 0,
    prospeo: Number(vals.price_prospeo_usd_per_credit) || 0,
    serper: Number(vals.price_serper_usd_per_credit) || 0,
  };
  const sp = (s: Spend | null) => spendText(s, prices);
  const bRows = batchRows(data.leads, data.touches, alloc, base);
  const batchNos = [...new Set(data.leads.flatMap((l) => (l.batch_no == null ? [] : [l.batch_no])))].sort((a, b) => b - a);
  const angles = byAngle(data.leads, data.touches, angleBatch === "" ? undefined : Number(angleBatch));
  const dies = whereLeadsDie(data.leads);
  const undated = undatedCounts(data.touches, data.leads);
  const inRange = rangeOk ? spendFrom(data.costs.filter((c) => c.day.slice(0, 10) >= from && c.day.slice(0, 10) <= to)) : {};
  const providers = Object.entries(inRange).sort((a, b) => (a[0] < b[0] ? -1 : 1));
  const buckets: [string, Spend][] = [
    ["Allocated to numbered batches", [...alloc.byBatchNo.values()].reduce(addSpend, {} as Spend)],
    ["Allocated to verified owners not yet in a batch", alloc.notNumbered],
    ["Not allocated: run has no verified owner yet", alloc.noOwners],
    ["No batch or lead", alloc.unattributed],
  ];
  const bucketSum = buckets.reduce((a, [, s]) => addSpend(a, s), {} as Spend);
  const pickGrain = (g: Grain) => { setGrain(g); if (isDate(to)) setFrom(defaultFrom(g, to)); };
  const hCells = (r: HistoryRow) => (
    <>
      {H_COLS.map((k) => <td key={k}>{r[k]}</td>)}
      <td>{sp(r.spend)}</td>
      <td>{sp(perUnit(r.spend, r.owners))}</td>
    </>
  );

  const runs = rows.filter((r) => r.scraped > 0);
  const counts = (r: BatchMetrics) => r as unknown as Counts;
  const all: Counts = Object.fromEntries(STAGES.map((s) => [s.key, runs.reduce((a, r) => a + Number(counts(r)[s.key] ?? 0), 0)]));
  const otherText = Object.entries(d.other).sort((a, b) => b[1] - a[1]).map(([s, n]) => `${n} ${s}`).join(", ");

  return (
    <>
      <h1>Metrics</h1>
      <p className="muted">
        Batches use the Touch 1 cohort (leads whose Touch 1 was sent); history uses event dates. This page is UTC.
      </p>
      {mErr && <p className="err">{mErr}</p>}

      <h2>Batches of 100</h2>
      <table>
        <thead>
          <tr>
            <th>Batch</th><th>Fill</th><th>Sent</th>
            <th title="bounced of sent">Bounced</th>
            <th title="of delivered (sent minus bounced)">Replied</th>
            <th title="of delivered">Positive</th>
            <th title="of delivered">Booked</th>
            <th title="each scrape run's spend split equally over its verified owners">Allocated spend</th>
            <th>Cost per verified owner</th>
            <th>Cost per reply</th>
          </tr>
        </thead>
        <tbody>
          {bRows.map((b) => (
            <tr key={b.batch_no}>
              <td>{batchLabel(b.batch_no)}</td>
              <td>{fillLabel({ leads: b.fill })}{b.base > 0 && <span className="muted"> (includes {b.base} outside the OS: no cost, no outcomes)</span>}</td>
              <td>sent {b.sent}, delivered {b.delivered}</td>
              <td>{kOf(b.bounced, b.sent)}</td>
              <td>{kOf(b.replied, b.delivered)}</td>
              <td>{kOf(b.positive, b.delivered)}</td>
              <td>{kOf(b.booked, b.delivered)}</td>
              <td>{sp(b.spend)}</td>
              <td>{sp(perUnit(b.spend, b.owners))}</td>
              <td>{sp(perUnit(b.spend, b.replied))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {mLoaded && !mErr && bRows.length === 0 && <p className="muted">No batch numbers yet: leads get one when select picks them.</p>}
      <p className="muted">
        Allocated spend is a living number: it moves while enrichment and drafting continue. Unpriced credits are shown as credits, not dollars (set prices on the Settings page).
      </p>

      <h3>Pipeline by batch</h3>
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

      <h2>Money</h2>
      <h3>By provider, {rangeOk ? `${from} to ${to}` : "no valid range"} (the History range)</h3>
      <table>
        <thead>
          <tr><th>Provider</th><th>Recorded dollars</th><th>Credits or units</th><th>Priced dollars</th></tr>
        </thead>
        <tbody>
          {providers.map(([prov, v]) => (
            <tr key={prov}>
              <td>{prov}</td><td>{money(v.usd)}</td><td>{Math.round(v.units * 100) / 100}</td><td>{money(pricedUsd({ [prov]: v }, prices))}</td>
            </tr>
          ))}
          {providers.length > 0 && (
            <tr><td><strong>All providers</strong></td><td>{money(providers.reduce((a, [, v]) => a + v.usd, 0))}</td><td></td><td>{money(pricedUsd(inRange, prices))}</td></tr>
          )}
        </tbody>
      </table>
      {mLoaded && !mErr && rangeOk && providers.length === 0 && <p className="muted">No spend recorded in this range.</p>}
      <h3>Where all spend went</h3>
      <table>
        <thead><tr><th>Bucket</th><th>Spend</th></tr></thead>
        <tbody>
          {buckets.map(([label, s]) => <tr key={label}><td>{label}</td><td>{sp(s)}</td></tr>)}
          <tr><td><strong>Sum of the four buckets</strong></td><td>{sp(bucketSum)}</td></tr>
          <tr><td><strong>Total spend</strong></td><td>{sp(spendFrom(data.costs))}</td></tr>
        </tbody>
      </table>
      <p className="muted">The sum of the four buckets equals total spend. Groq is tokens and never becomes money.</p>

      <h2>History</h2>
      <p>
        <label>Grain{" "}
          <select value={grain} onChange={(e) => pickGrain(e.target.value as Grain)}>
            <option value="day">day</option><option value="week">week (Monday start)</option><option value="month">month</option><option value="quarter">quarter</option>
          </select>
        </label>{" "}
        <label>From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>{" "}
        <label>To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </p>
      {!rangeOk && <p className="err">Pick a from date on or before the to date.</p>}
      {hist && (
        <>
          <table>
            <thead>
              <tr>
                <th>Period start</th>
                {H_LABELS.map((l) => <th key={l}>{l}</th>)}
                <th>Spend</th>
                <th title="period spend divided by that period's verified owners; enrichment can finish later">Cost per verified owner (approximate)</th>
              </tr>
            </thead>
            <tbody>
              {hist.rows.map((r) => <tr key={r.start}><td>{r.start}</td>{hCells(r)}</tr>)}
              <tr><td><strong>This range</strong></td>{hCells(total(hist.rows))}</tr>
              <tr className="muted"><td>Previous range, {hist.prev.from} to {hist.prev.to}</td>{hCells(total(hist.prevRows))}</tr>
            </tbody>
          </table>
          <p className="muted">
            Counts and money only; rates live in Batches of 100. Scraped and verified owners by lead creation date, sends by sent time, bounces and replies by outcome time, booked by booking time.
          </p>
        </>
      )}
      {(undated.bounces + undated.replies > 0 || undated.booked > 0) && (
        <p className="muted">{undated.bounces + undated.replies} outcomes and {undated.booked} bookings have no date: recorded before migration 0017.</p>
      )}

      <h2>Angles</h2>
      <p>
        <label>Batch{" "}
          <select value={angleBatch} onChange={(e) => setAngleBatch(e.target.value)}>
            <option value="">All numbered leads</option>
            {batchNos.map((n) => <option key={n} value={n}>{batchLabel(n)}</option>)}
          </select>
        </label>
      </p>
      <table>
        <thead>
          <tr><th>Vector</th><th>Lane</th><th>Leads</th><th>Sent</th><th>Bounced</th><th>Replied</th><th>Positive</th><th>Booked</th></tr>
        </thead>
        <tbody>
          {angles.map((a) => (
            <tr key={`${a.vector}|${a.lane}`}>
              <td>{a.vector}</td><td>{a.lane}</td><td>{a.leads}</td><td>{kOf(a.sent, a.leads)}</td>
              <td>{kOf(a.bounced, a.sent)}</td><td>{kOf(a.replied, a.delivered)}</td><td>{kOf(a.positive, a.delivered)}</td><td>{kOf(a.booked, a.delivered)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {mLoaded && !mErr && angles.length === 0 && <p className="muted">No numbered leads yet.</p>}

      <h2>Where leads die</h2>
      <table>
        <thead><tr><th>Reason</th><th>Leads</th></tr></thead>
        <tbody>{dies.map((r) => <tr key={r.reason}><td>{r.reason}</td><td>{r.n}</td></tr>)}</tbody>
      </table>
      {mLoaded && !mErr && dies.length === 0 && <p className="muted">No rejected or no_buyer leads.</p>}

      <details>
        <summary><h2 style={{ display: "inline" }}>Scrape runs and previous cost table (detail)</h2></summary>
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

        <h3>Spend recorded against leads only (previous cost table)</h3>
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
          Scrape-time Apify is logged per scrape run, and spend on leads that never reached a batch has no batch: neither is here (scrape runs are above).
        </p>
      </details>
    </>
  );
}
