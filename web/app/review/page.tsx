"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { LEAD_COLUMNS, type Lead } from "@/lib/types";
import { approveLeads, rejectLeads, unapproveLeads } from "@/lib/actions";
import { Evidence } from "@/components/Evidence";

export default function Review() {
  const ready = useRequireSession();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    const { data, error } = await supabase.from("leads").select(LEAD_COLUMNS).eq("status", "selected").order("signal_led", { ascending: false }).order("created_at");
    if (error) setErr(error.message); else { setErr(""); setLeads((data ?? []) as unknown as Lead[]); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const waiting = leads.filter((l) => !l.approved);
  const approved = leads.filter((l) => l.approved);
  const ids = [...picked];
  const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  async function run(label: string, fn: (ids: string[]) => Promise<void>, target: string[]) {
    setMsg(""); setErr("");
    try { await fn(target); setMsg(`${label}: ${target.length}`); setPicked(new Set()); await load(); }
    catch (e) { setErr((e as Error).message); }
  }

  const row = (l: Lead) => (
    <div className="card" key={l.id}>
      <div className="bar" style={{ marginBottom: 6 }}>
        <input type="checkbox" checked={picked.has(l.id)} onChange={() => toggle(l.id)} />
        <strong>{l.name}</strong>
        <span className="muted">{[l.city, l.state].filter(Boolean).join(", ")}</span>
        <span className={`pill ${l.signal_led ? "ok" : ""}`}>{l.signal_led ? "signal-led" : "relevance-led"}</span>
        <span className="pill">{l.vector}</span>
        <button onClick={() => setOpen(open === l.id ? null : l.id)}>{open === l.id ? "Hide evidence" : "Evidence"}</button>
        {l.approved
          ? <button onClick={() => run("Unapproved", unapproveLeads, [l.id])}>Unapprove</button>
          : <><button className="primary" onClick={() => run("Approved", approveLeads, [l.id])}>Approve</button>
              <button className="danger" onClick={() => run("Rejected", rejectLeads, [l.id])}>Reject</button></>}
      </div>
      <div>{l.select_reason}</div>
      <div className="muted">{l.owner_name}, {l.owner_title} · {l.owner_email} <span>({l.email_source})</span></div>
      {open === l.id && <div className="detail"><Evidence lead={l} /></div>}
    </div>
  );

  return (
    <>
      <h1>Review <span className="muted">({waiting.length} waiting, {approved.length} approved)</span></h1>
      <p className="muted">Selected leads, with the reason and the evidence behind it. Approved leads are drafted by <code>gtm draft</code>.</p>
      <div className="bar">
        <button className="primary" disabled={!ids.length} onClick={() => run("Approved", approveLeads, ids)}>Approve selected ({ids.length})</button>
        <button className="danger" disabled={!ids.length} onClick={() => run("Rejected", rejectLeads, ids)}>Reject selected ({ids.length})</button>
        <button disabled={!waiting.length} onClick={() => run("Approved", approveLeads, waiting.map((l) => l.id))}>Approve all waiting ({waiting.length})</button>
      </div>
      {msg && <p className="msg">{msg}</p>}{err && <p className="err">{err}</p>}
      <h2>Waiting for review</h2>
      {waiting.length ? waiting.map(row) : <p className="muted">Nothing waiting.</p>}
      <h2>Approved, ready to draft</h2>
      {approved.length ? approved.map(row) : <p className="muted">None yet.</p>}
    </>
  );
}
