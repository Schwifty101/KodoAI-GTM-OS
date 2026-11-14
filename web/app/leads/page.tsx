"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { LEAD_COLUMNS, STATUSES, VECTORS, type Lead } from "@/lib/types";
import { Evidence } from "@/components/Evidence";

type Batch = { id: string; name: string };

export default function Leads() {
  const ready = useRequireSession();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [f, setF] = useState({ status: "", batch: "", city: "", state: "", vector: "", hasEmail: false, sort: "created_at" });
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    let q = supabase.from("leads").select(LEAD_COLUMNS).order(f.sort, { ascending: f.sort === "name", nullsFirst: false }).limit(300);
    if (f.status) q = q.eq("status", f.status);
    if (f.batch) q = q.eq("batch_id", f.batch);
    if (f.city) q = q.ilike("city", `%${f.city}%`);
    if (f.state) q = q.ilike("state", `%${f.state}%`);
    if (f.vector) q = q.eq("vector", f.vector);
    if (f.hasEmail) q = q.not("owner_email", "is", null);
    const { data, error } = await q;
    if (error) setErr(error.message); else { setErr(""); setLeads((data ?? []) as unknown as Lead[]); }
  }, [f]);

  useEffect(() => { if (ready) load(); }, [ready, load]);
  useEffect(() => {
    if (ready) supabase.from("batches").select("id,name").order("created_at", { ascending: false }).then(({ data }) => setBatches(data ?? []));
  }, [ready]);

  if (!ready) return null;
  const set = (k: keyof typeof f, v: string | boolean) => setF({ ...f, [k]: v });

  return (
    <>
      <h1>Leads <span className="muted">({leads.length}{leads.length === 300 ? "+" : ""})</span></h1>
      <div className="bar">
        <select value={f.status} onChange={(e) => set("status", e.target.value)}>
          <option value="">any status</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select value={f.batch} onChange={(e) => set("batch", e.target.value)}>
          <option value="">any batch</option>{batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <select value={f.vector} onChange={(e) => set("vector", e.target.value)}>
          <option value="">any vector</option>{VECTORS.map((v) => <option key={v}>{v}</option>)}
        </select>
        <input placeholder="city" value={f.city} onChange={(e) => set("city", e.target.value)} />
        <input placeholder="state" value={f.state} onChange={(e) => set("state", e.target.value)} />
        <label><input type="checkbox" checked={f.hasEmail} onChange={(e) => set("hasEmail", e.target.checked)} /> has email</label>
        <select value={f.sort} onChange={(e) => set("sort", e.target.value)}>
          <option value="created_at">newest first</option><option value="name">name A-Z</option><option value="review_count">most reviews</option>
        </select>
      </div>
      {err && <p className="err">{err}</p>}
      <table>
        <thead><tr><th>Business</th><th>Where</th><th>Status</th><th>Buyer</th><th>Vector</th><th>Lane</th><th>Batch</th></tr></thead>
        <tbody>
          {leads.map((l) => (
            <Fragment key={l.id}>
              <tr className="row" onClick={() => setOpen(open === l.id ? null : l.id)}>
                <td>{l.name}<div className="muted">{l.domain}</div></td>
                <td>{[l.city, l.state].filter(Boolean).join(", ")}</td>
                <td><span className={`pill ${l.status === "selected" || l.status === "sent" ? "ok" : l.status === "rejected" || l.status === "bounced" ? "bad" : ""}`}>{l.status}</span></td>
                <td>{l.owner_name ?? <span className="muted">none</span>}<div className="muted">{l.owner_title}</div></td>
                <td>{l.vector ?? ""}</td>
                <td>{l.vector ? (l.signal_led ? "signal-led" : "relevance-led") : ""}</td>
                <td className="muted">{l.batches?.name}</td>
              </tr>
              {open === l.id && (
                <tr><td colSpan={7}>
                  <div className="detail">
                    <p><strong>{l.name}</strong> {l.website && <a href={l.website} target="_blank" rel="noreferrer">{l.website}</a>} {l.rating != null && <span className="muted">· {l.rating} stars, {l.review_count} reviews</span>}</p>
                    {l.owner_email && <p>Buyer: {l.owner_name}, {l.owner_title} · <span className="muted">{l.owner_email} via {l.email_source}</span></p>}
                    {l.select_reason && <p><strong>Why selected:</strong> {l.select_reason}</p>}
                    {l.reject_reason && <p className="muted">Reason not selected: {l.reject_reason}</p>}
                    <Evidence lead={l} />
                  </div>
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {leads.length === 0 && !err && <p className="muted">No leads match.</p>}
    </>
  );
}
