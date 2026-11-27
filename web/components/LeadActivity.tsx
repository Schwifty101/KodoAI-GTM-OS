"use client";
import { useEffect, useState } from "react";
import { loadLeadActivity } from "@/lib/leadActivity";
import { hint0017 } from "@/lib/metrics";

type Activity = Awaited<ReturnType<typeof loadLeadActivity>>;

/** UTC YYYY-MM-DD HH:MM. */
const when = (iso: string) => new Date(iso).toISOString().slice(0, 16).replace("T", " ");

/** What this lead cost and what happened to its touches. Scrape-time Apify is logged per run, so it is not here. */
export function LeadActivity({ leadId }: { leadId: string }) {
  const [a, setA] = useState<Activity | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setA(null); setErr(null);
    loadLeadActivity(leadId).then((r) => { if (!cancelled) setA(r); }, (e) => { if (!cancelled) setErr(hint0017((e as Error).message)); });
    return () => { cancelled = true; };
  }, [leadId]);

  if (err) return <p className="err">{err}</p>;
  if (!a) return <p className="muted">Loading activity...</p>;
  const providers = Object.entries(a.spend);
  return (
    <div>
      <p><strong>Spend</strong> <span className="muted">(recorded against this lead; scrape-time Apify is per run)</span></p>
      {providers.length === 0 ? <p className="muted">No spend recorded against this lead.</p> : (
        <table>
          <thead><tr><th>Provider</th><th>Units</th><th>Dollars</th></tr></thead>
          <tbody>
            {providers.map(([p, v]) => <tr key={p}><td>{p}</td><td>{v.units}</td><td>{v.usd > 0 ? `$${v.usd.toFixed(v.usd < 0.1 ? 4 : 2)}` : "-"}</td></tr>)}
          </tbody>
        </table>
      )}
      <p><strong>Touches</strong></p>
      {a.touches.length === 0 ? <p className="muted">n/a</p> : a.touches.map((t, i) => (
        <div key={i}>
          Touch {t.touch_no}, {t.sent_at ? `sent ${when(t.sent_at)}` : "not sent"}{t.outcome ? `, outcome ${t.outcome} on ${t.outcome_at ? when(t.outcome_at) : "date not recorded"}` : ""}
        </div>
      ))}
    </div>
  );
}
