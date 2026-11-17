"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { approveTouches, checkDrafts, clearPause, markFailed, markSent, pauseSending, saveDraftEdit, skipTouch, startSending, unapproveTouches } from "@/lib/actions";
import { fetchAll } from "@/lib/fetchAll";
import type { Mailbox, Touch } from "@/lib/types";

type T = Touch & { leads: { name: string; owner_name: string | null; place_id: string; mailbox_id: string | null; status: string } };
const COLS = "id,lead_id,touch_no,status,subject,body,scheduled_for,sent_at,send_at,outcome,problems,leads!inner(name,owner_name,place_id,mailbox_id,status)";
const day = (iso: string | null) => (iso ?? "").slice(0, 10);
const ago = (iso: string | null) => (iso ? Math.floor((Date.now() - Date.parse(iso)) / 864e5) : 0);

export default function Send() {
  const ready = useRequireSession();
  const [tab, setTab] = useState<"today" | "follow">("today");
  const [mb, setMb] = useState<Mailbox | null>(null);
  const [on, setOn] = useState(false);
  const [open, setOpen] = useState<T[]>([]);
  const [sent, setSent] = useState<T[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [subj, setSubj] = useState("");
  const [body, setBody] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const page = (statuses: string[]) => fetchAll<T>((a, b) => supabase.from("touches").select(COLS).in("status", statuses).order("id").range(a, b) as unknown as PromiseLike<{ data: T[] | null; error: { message: string } | null }>);
      const [m, s, o, st] = await Promise.all([
        supabase.from("mailboxes").select("*").order("enabled_on", { ascending: false, nullsFirst: false }).limit(1),
        supabase.from("settings").select("value").eq("key", "sending_on"),
        page(["drafted", "held", "edited", "approved", "scheduled", "sending"]),
        page(["sent"]),
      ]);
      if (m.error || s.error) throw new Error((m.error ?? s.error)!.message);
      setErr(""); setMb((m.data?.[0] as Mailbox) ?? null); setOn(s.data?.[0]?.value === true); setOpen(o); setSent(st);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  const checking = open.some((t) => t.status === "edited");
  useEffect(() => { if (checking) { const i = setInterval(load, 4000); return () => clearInterval(i); } }, [checking, load]);
  if (!ready) return null;

  async function act(fn: () => Promise<unknown>, ok = "") {
    setMsg(""); setErr("");
    try { await fn(); setMsg(ok); await load(); } catch (e) { setErr((e as Error).message); }
  }

  const today = new Date().toISOString().slice(0, 10);
  const mine = (t: T) => !mb || t.leads.mailbox_id === mb.id;
  // One source of truth: the Python send tick stamps the allowance (gtm/send.py today_allowance).
  const allowance = mb?.allowance_date === today && mb.allowance_today != null ? mb.allowance_today : null;
  const sentToday = sent.filter((t) => mine(t) && day(t.sent_at) === today).length;
  const wk = sent.filter((t) => mine(t) && ago(t.sent_at) < 7);
  const bounced = wk.filter((t) => t.leads.status === "bounced").length;
  const q = (s: string) => open.filter((t) => t.status === s);
  const next = q("scheduled").map((t) => t.send_at).filter(Boolean).sort()[0];
  const follow = open.filter((t) => t.touch_no > 1 && ["drafted", "held", "edited", "approved", "scheduled"].includes(t.status));
  const ready1 = follow.filter((t) => t.status === "drafted").map((t) => t.id);
  const t1 = (leadId: string) => sent.find((t) => t.lead_id === leadId && t.touch_no === 1);

  const startEdit = (t: T) => { setEditing(t.id); setSubj(t.subject ?? ""); setBody(t.body ?? ""); };
  const save = (id: string) => act(async () => { await saveDraftEdit(id, subj, body); setEditing(null); await checkDrafts().catch(() => {}); }, "Saved, checking...");

  return (
    <>
      <h1>Send</h1>
      {msg && <p className="msg">{msg}</p>}{err && <p className="err">{err}</p>}
      <div className="bar">
        <button className={tab === "today" ? "primary" : ""} onClick={() => setTab("today")}>Today</button>
        <button className={tab === "follow" ? "primary" : ""} onClick={() => setTab("follow")}>Follow-ups <span className="pill">{follow.length}</span></button>
      </div>

      {tab === "today" && (
        <>
          {!mb && <p className="muted">No mailbox yet: <code>gtm mailbox add --address you@kodoai.xyz</code></p>}
          {mb && (
            <div className="card">
              <div className="bar">
                <strong>{mb.address}</strong>
                <span className={`pill ${mb.paused ? "bad" : "ok"}`}>{mb.paused ? "mailbox paused" : "mailbox active"}</span>
                <span className={`pill ${on ? "ok" : ""}`}>sending {on ? "ON" : "OFF"}</span>
                {on ? <button onClick={() => act(pauseSending, "Sending paused")}>Pause</button>
                    : <button className="primary" disabled={mb.paused} onClick={() => act(startSending, "Sending started")}>Start sending</button>}
              </div>
              {mb.paused && <p className="err">{mb.paused_reason} <button onClick={() => act(() => clearPause(mb.id), "Pause cleared")}>I&apos;ve looked, clear the pause</button></p>}
              <div>Allowance today {allowance === null ? <span className="muted">not computed yet today</span> : <strong>{allowance}</strong>} · sent today <strong>{sentToday}</strong> · sent last 7 days <strong>{wk.length}</strong> · bounced <strong>{bounced}</strong> ({wk.length ? Math.round((100 * bounced) / wk.length) : 0}%)</div>
            </div>
          )}
          <div className="grid">
            <div className="card"><strong>{q("scheduled").length}</strong> scheduled<div className="muted">next: {next ? new Date(next).toLocaleString() : "none"}</div></div>
            <div className="card"><strong>{q("approved").length}</strong> approved, not yet scheduled<div className="muted">deferred outside the window or over the allowance</div></div>
            <div className="card"><strong>{q("held").length}</strong> held</div>
          </div>
          <h2>Stuck in sending ({q("sending").length})</h2>
          <p className="muted">A touch claimed but not confirmed (a crash). Check Gmail Sent, then pick.</p>
          {q("sending").map((t) => (
            <div className="card" key={t.id}><div className="bar" style={{ marginBottom: 0 }}>
              <strong>{t.leads.name}</strong><span className="pill">Touch {t.touch_no}</span>
              <button onClick={() => act(() => markSent(t.id), "Marked sent")}>Mark sent</button>
              <button className="danger" onClick={() => act(() => markFailed(t.id), "Returned to approved")}>Mark failed</button>
            </div></div>
          ))}
          {!q("sending").length && <p className="muted">Nothing stuck.</p>}
        </>
      )}

      {tab === "follow" && (
        <>
          <div className="bar">
            <button className="primary" disabled={!ready1.length} onClick={() => act(() => approveTouches(ready1), `Approved ${ready1.length}`)}>Approve all ({ready1.length})</button>
            <span className="muted">Replies last checked: {mb?.replies_checked_at ? new Date(mb.replies_checked_at).toLocaleString() : "never"}{follow.some((t) => t.status === "edited") && " · checking drafts..."}</span>
          </div>
          {follow.map((t) => {
            const first = t1(t.lead_id);
            const overdue = !!t.scheduled_for && t.scheduled_for < today;
            return (
              <div className="card" key={t.id}>
                <div className="bar" style={{ marginBottom: 4 }}>
                  <strong>{t.leads.name}</strong><span className="muted">{t.leads.owner_name}</span><span className="pill">Touch {t.touch_no}</span>
                  <span className="muted">{first ? `${ago(first.sent_at)} days since Touch 1` : "Touch 1 not found"}{first?.outcome ? ` · outcome ${first.outcome}` : ""}</span>
                  {overdue && <span className="pill bad">overdue</span>}
                  {["approved", "scheduled"].includes(t.status) && <span className="pill ok">{t.status}</span>}
                  {t.status === "edited" && <span className="pill">checking...</span>}
                  {t.status === "held" && <span className="pill bad">held: {t.problems.join(", ")}</span>}
                  {t.send_at && <span className="muted">planned {new Date(t.send_at).toLocaleString()}</span>}
                </div>
                {first && <details><summary className="muted">Original email: {first.subject}</summary><pre className="draft">{first.body}</pre></details>}
                {editing === t.id ? (
                  <div>
                    <input style={{ width: "100%", marginBottom: 6 }} value={subj} onChange={(e) => setSubj(e.target.value)} />
                    <textarea style={{ width: "100%" }} rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
                    <div className="bar"><button className="primary" onClick={() => save(t.id)}>Save</button><button onClick={() => setEditing(null)}>Cancel</button></div>
                  </div>
                ) : (
                  <>
                    <strong>{t.subject}</strong><pre className="draft">{t.body}</pre>
                    <div className="bar">
                      {t.status === "approved"
                        ? <button onClick={() => act(() => unapproveTouches([t.id]), "Unapproved")}>Unapprove</button>
                        : <button className="primary" disabled={t.status !== "drafted"} onClick={() => act(() => approveTouches([t.id]), "Approved")}>Approve</button>}
                      <button onClick={() => startEdit(t)}>Edit</button>
                      {t.status !== "scheduled" && <button className="danger" onClick={() => act(() => skipTouch(t.id), "Skipped")}>Skip</button>}
                    </div>
                  </>
                )}
              </div>
            );
          })}
          {!follow.length && <p className="muted">No follow-ups waiting. Touch 2 and 3 appear here when they are due.</p>}
        </>
      )}
    </>
  );
}
