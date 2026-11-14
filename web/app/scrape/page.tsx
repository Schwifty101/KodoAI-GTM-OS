"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { useSettings } from "@/lib/useSettings";
import { SettingInput } from "@/components/SettingInput";
import { SETTING_FIELDS } from "@/lib/settings";
import { enqueueJobOnce, retryTile } from "@/lib/actions";
import { loadCoverage, runTilesArgv, summarizeMetros, walkJobOpen } from "@/lib/scrape";
import type { Coverage, Job, SpendRow } from "@/lib/types";

const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0);

export default function Scrape() {
  const ready = useRequireSession();
  const { vals, reload, save, err: setErr0 } = useSettings(ready);
  const [cov, setCov] = useState<Coverage[]>([]);
  const [spend, setSpend] = useState<SpendRow | undefined>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [n, setN] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [c, sp, j] = await Promise.all([
        loadCoverage(),
        supabase.from("spend_summary").select("*").eq("provider", "apify"),
        supabase.from("jobs").select("*").eq("kind", "walk").order("created_at", { ascending: false }).limit(50),
      ]);
      for (const r of [sp, j]) if (r.error) throw new Error(r.error.message);
      setErr(""); setCov(c); setSpend((sp.data as SpendRow[])[0]); setJobs((j.data ?? []) as Job[]);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const act = async (fn: () => Promise<void>) => { try { await fn(); await load(); await reload(); } catch (e) { setErr((e as Error).message); } };
  const metros = summarizeMetros(cov);
  const sum = (f: (c: Coverage) => number) => cov.reduce((s, c) => s + f(c), 0);
  const count = (s: string) => cov.filter((c) => c.status === s).length;
  const done = count("done");
  const today = Number(spend?.usd_today ?? 0), month = Number(spend?.usd_month ?? 0), cap = Number(vals.cap_apify_usd_day);
  const blocked = cap === 0, atCap = !blocked && today >= cap;
  const tiles = n === "" ? Number(vals.walk_tiles_per_run) : Number(n);
  const tilesOk = Number.isInteger(tiles) && tiles >= 1 && tiles <= 20;
  const isOpen = walkJobOpen(jobs);
  const failed = cov.filter((c) => c.status === "failed");
  const shown = metros.filter((m) => `${m.metro} ${m.state}`.toLowerCase().includes(q.toLowerCase()));
  const sched = vals.walk_schedule_enabled === true;

  return (
    <>
      <h1>Scrape &amp; Coverage</h1>
      {(err || setErr0) && <p className="err">{err || setErr0}</p>}
      <p className="muted">The daily schedule is OFF by owner decision. Only the owner turns it on (below), and only when the owner adds Apify credit once the free credit runs out or the OS is ready for campaigns. Nothing here scrapes by itself: a button queues a job and the worker on the VM runs it. <span className={`pill ${sched ? "bad" : "ok"}`}>{sched ? "schedule on" : "schedule off"}</span></p>

      <h2>Coverage</h2>
      <div className="card">
        <div>{done} of {cov.length} tiles done ({pct(done, cov.length)}%)</div>
        <div style={{ height: 8, background: "var(--line)", borderRadius: 4, margin: "6px 0" }}>
          <div style={{ height: 8, width: `${pct(done, cov.length)}%`, background: "var(--accent)", borderRadius: 4 }} />
        </div>
        <div className="muted">
          pending {count("pending")}, running {count("running")}, done {done}, failed {count("failed")} · places found {sum((c) => c.places_found ?? 0)} · new leads {sum((c) => c.new_leads ?? 0)} · saturated {cov.filter((c) => c.saturated).length} · metros finished {metros.filter((m) => m.done === m.total).length} of {metros.length}
        </div>
        {!cov.length && <div className="muted">No coverage yet. Run `seed-coverage` first.</div>}
      </div>

      <h2>Apify spend</h2>
      <div className="card">
        today ${today.toFixed(2)} of ${cap.toFixed(2)} day cap {blocked ? <span className="pill bad">blocked</span> : atCap && <span className="pill bad">at cap</span>} · month ${month.toFixed(2)}
        <div className="muted">Typical tile $0.10 to $0.20, worst case $0.40 (docs/spikes/tile_tuning.md).</div>
      </div>

      <h2>Run now</h2>
      <div className="bar">
        <input type="number" min={1} max={20} step={1} value={n === "" ? String(vals.walk_tiles_per_run) : n} onChange={(e) => setN(e.target.value)} />
        <button className="primary" disabled={!tilesOk || isOpen || blocked || atCap}
          onClick={() => act(() => enqueueJobOnce("walk", runTilesArgv(tiles)))}>Run {tilesOk ? tiles : "N"} {tiles === 1 ? "tile" : "tiles"} now</button>
      </div>
      <p className="muted">Spends Apify credit (about $0.10 to $0.40 a tile at the tuned depth) and is capped by the daily Apify cap.</p>
      {!tilesOk && <p className="err">Tiles must be a whole number from 1 to 20.</p>}
      {isOpen && <p className="muted">A walk job is already queued or running.</p>}
      {(blocked || atCap) && <p className="err">Apify is {blocked ? "blocked (cap is 0)" : "at its day cap"}: the worker would pause the job. Raise the cap in Settings first.</p>}
      <table>
        <thead><tr><th>Created</th><th>Job</th><th>Status</th><th>Error</th></tr></thead>
        <tbody>
          {jobs.slice(0, 5).map((j) => (
            <tr key={j.id}><td className="muted">{j.created_at.slice(0, 16).replace("T", " ")}</td><td>{j.kind} {(j.payload.argv ?? []).join(" ")}</td>
              <td><span className={`pill ${j.status === "failed" ? "bad" : ""}`}>{j.status}</span></td><td className="err">{j.error}</td></tr>
          ))}
          {!jobs.length && <tr><td colSpan={4} className="muted">No walk jobs yet.</td></tr>}
        </tbody>
      </table>

      <h2>Walk settings</h2>
      <div className="grid">{SETTING_FIELDS.filter((f) => f.group === "Scrape walk").map((f) => <SettingInput key={f.key} f={f} vals={vals} save={save} />)}</div>

      {failed.length > 0 && (
        <>
          <h2>Failed tiles</h2>
          <p className="muted">Retry sets the tile back to pending; the next walk picks it up.</p>
          <table>
            <thead><tr><th>Metro</th><th>State</th><th>Tile</th><th>Error</th><th></th></tr></thead>
            <tbody>{failed.map((c) => (
              <tr key={c.id}><td>{c.metro}</td><td>{c.state}</td><td>{c.tile}</td><td className="err">{c.error}</td>
                <td><button onClick={() => act(() => retryTile(c.id))}>Retry</button></td></tr>
            ))}</tbody>
          </table>
        </>
      )}

      <h2>Metros</h2>
      <div className="bar"><input placeholder="Filter by metro or state" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <table>
        <thead><tr><th>#</th><th>Metro</th><th>State</th><th>Done</th><th>Running</th><th>Failed</th><th>Places</th><th>New leads</th><th>Saturated</th><th>Last scraped</th></tr></thead>
        <tbody>
          {shown.map((m) => {
            const k = `${m.metro_rank}|${m.metro}`;
            return (
              <Fragment key={k}>
                <tr className="row" onClick={() => setOpen(open === k ? null : k)}>
                  <td>{m.metro_rank}</td><td>{m.metro}</td><td>{m.state}</td><td>{m.done}/{m.total}</td><td>{m.running}</td><td>{m.failed}</td>
                  <td>{m.places}</td><td>{m.newLeads}</td><td>{m.saturated}</td><td className="muted">{m.lastScraped?.slice(0, 10) ?? ""}</td>
                </tr>
                {open === k && (
                  <tr><td colSpan={10}>
                    <table>
                      <thead><tr><th>Tile</th><th>Status</th><th>Places</th><th>New leads</th><th>Saturated</th><th>Queries run</th><th>Scraped</th><th>Error</th></tr></thead>
                      <tbody>{cov.filter((c) => c.metro_rank === m.metro_rank && c.metro === m.metro).map((c) => (
                        <tr key={c.id}><td>{c.tile}</td><td><span className={`pill ${c.status === "failed" ? "bad" : ""}`}>{c.status}</span></td>
                          <td>{c.places_found ?? ""}</td><td>{c.new_leads ?? ""}</td><td>{c.saturated ? "yes" : ""}</td><td>{c.queries_run ?? ""}</td>
                          <td className="muted">{c.scraped_at?.slice(0, 16).replace("T", " ") ?? ""}</td><td className="err">{c.error}</td></tr>
                      ))}</tbody>
                    </table>
                  </td></tr>
                )}
              </Fragment>
            );
          })}
          {!shown.length && <tr><td colSpan={10} className="muted">No metros to show.</td></tr>}
        </tbody>
      </table>
    </>
  );
}
