"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import type { BatchMetrics } from "@/lib/types";

type Counts = Record<string, number>;

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

export default function Dashboard() {
  const ready = useRequireSession();
  const [rows, setRows] = useState<BatchMetrics[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!ready) return;
    supabase
      .from("batch_metrics")
      .select("*")
      .order("created_at", { ascending: false })
      .then(({ data, error }) => {
        if (error) setErr(error.message);
        else setRows((data ?? []) as unknown as BatchMetrics[]);
      });
  }, [ready]);
  if (!ready) return null;

  const counts = (r: BatchMetrics) => r as unknown as Counts;
  const all: Counts = Object.fromEntries(STAGES.map((s) => [s.key, rows.reduce((a, r) => a + Number(counts(r)[s.key] ?? 0), 0)]));

  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">
        One row per scrape batch. The small percentage is the share of the previous column. Hunter is shown in credits until a plan is priced.
      </p>
      {err && <p className="err">{err}</p>}
      <table>
        <thead>
          <tr>
            <th>Batch</th>
            {STAGES.map((s) => (
              <th key={s.key} title={s.hint}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.batch_id}>
              <td>{r.name}</td>
              <Cells row={counts(r)} />
            </tr>
          ))}
          {rows.length > 1 && (
            <tr>
              <td><strong>All batches</strong></td>
              <Cells row={all} />
            </tr>
          )}
        </tbody>
      </table>
      <h2>Cost</h2>
      <table>
        <thead>
          <tr>
            <th>Batch</th><th>Apify</th><th>Apify per lead</th><th>Apify per verified email</th>
            <th>Hunter credits</th><th>Hunter credits per verified email</th><th>Search queries</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
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
      {rows.length === 0 && !err && (
        <p className="muted">No batches yet: <code>uv run python -m gtm.cli scrape --city … --state …</code></p>
      )}
    </>
  );
}
