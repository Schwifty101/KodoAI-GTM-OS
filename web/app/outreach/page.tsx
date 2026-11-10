"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import type { Mailbox, Touch } from "@/lib/types";
import { clearPause, markBooked, setOutcome } from "@/lib/actions";
import { fetchAll } from "@/lib/fetchAll";

const TOUCH_COLS = "id,lead_id,touch_no,status,subject,body,scheduled_for,sent_at,outcome,leads(name,owner_email,status,mailbox_id)";
const today = () => new Date().toISOString().slice(0, 10);

export default function Outreach() {
  const ready = useRequireSession();
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [touches, setTouches] = useState<Touch[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [m, t] = await Promise.all([
        supabase.from("mailboxes").select("*").order("address"),
        fetchAll<Touch>((a, b) => supabase.from("touches").select(TOUCH_COLS).order("scheduled_for", { ascending: true }).order("id").range(a, b) as unknown as PromiseLike<{ data: Touch[] | null; error: { message: string } | null }>),
      ]);
      if (m.error) throw new Error(m.error.message);
      setErr(""); setMailboxes(m.data ?? []); setTouches(t);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const act = async (fn: () => Promise<void>) => { try { await fn(); await load(); } catch (e) { setErr((e as Error).message); } };
  const mbAddr = (id: string | null) => mailboxes.find((m) => m.id === id)?.address ?? "no mailbox";
  const drafts = touches.filter((t) => t.status === "drafted");
  const sentToday = (m: Mailbox) => touches.filter((t) => t.status === "sent" && (t.sent_at ?? "").slice(0, 10) === today() && t.leads?.mailbox_id === m.id).length;
  const byLead = new Map<string, Touch[]>();
  touches.forEach((t) => byLead.set(t.lead_id, [...(byLead.get(t.lead_id) ?? []), t]));
  const answered = [...byLead.entries()].filter(([, ts]) => ["replied", "bounced", "unsubscribed", "booked"].includes(ts[0].leads?.status ?? ""));
  const tracker = [...byLead.entries()].filter(([, ts]) => ts[0].leads?.status === "sent");

  return (
    <>
      <h1>Outreach</h1>
      {err && <p className="err">{err}</p>}
      <p className="muted">Sending is a separate, explicit step: <code>uv run python -m gtm.cli send --confirm</code>. Drafts live in Gmail; edit them there, the Gmail draft is what goes out.</p>

      <h2>Mailboxes</h2>
      <div className="grid">
        {mailboxes.map((m) => (
          <div className="card" key={m.id}>
            <strong>{m.address}</strong> {m.paused ? <span className="pill bad">paused</span> : <span className="pill ok">active</span>}
            <div className="muted">enabled {m.enabled_on ?? "never"} · cap {m.daily_cap}/day · sent today {sentToday(m)}</div>
            {m.paused && <p className="err">{m.paused_reason}</p>}
            {m.paused && <button onClick={() => act(() => clearPause(m.id))}>I've looked, clear the pause</button>}
          </div>
        ))}
        {!mailboxes.length && <p className="muted">No mailbox yet: <code>gtm mailbox add --address you@kodoai.xyz</code></p>}
      </div>

      <h2>Drafts waiting ({drafts.length})</h2>
      {drafts.map((t) => (
        <div className="card" key={t.id}>
          <div className="bar" style={{ marginBottom: 4 }}>
            <strong>{t.leads?.name}</strong><span className="pill">Touch {t.touch_no}</span>
            <span className="muted">to {t.leads?.owner_email} from {mbAddr(t.leads?.mailbox_id ?? null)}</span>
            {(t.scheduled_for ?? "9") <= today() && t.touch_no > 1 && <span className="pill bad">due</span>}
          </div>
          <div><strong>{t.subject}</strong></div>
          <pre className="draft">{t.body}</pre>
        </div>
      ))}
      {!drafts.length && <p className="muted">No drafts. Approve leads on Review, then run <code>gtm draft --batch …</code>.</p>}

      <h2>Sequences in progress ({tracker.length})</h2>
      <table><thead><tr><th>Lead</th><th>Touch 1</th><th>Touch 2 (Day 3)</th><th>Touch 3 (Day 7)</th></tr></thead><tbody>
        {tracker.map(([id, ts]) => {
          const cell = (n: number) => { const t = ts.find((x) => x.touch_no === n); return t ? `${t.status}${t.sent_at ? " " + t.sent_at.slice(0, 10) : ""}` : "not drafted"; };
          return <tr key={id}><td>{ts[0].leads?.name}</td><td>{cell(1)}</td><td>{cell(2)}</td><td>{cell(3)}</td></tr>;
        })}
      </tbody></table>

      <h2>Replies and outcomes ({answered.length})</h2>
      {answered.map(([id, ts]) => {
        const last = [...ts].filter((t) => t.status === "sent").sort((a, b) => b.touch_no - a.touch_no)[0];
        return (
          <div className="card" key={id}>
            <div className="bar" style={{ marginBottom: 0 }}>
              <strong>{ts[0].leads?.name}</strong><span className="pill">{ts[0].leads?.status}</span>
              <span className="muted">classified: {last?.outcome ?? "none"}</span>
              {ts[0].leads?.status === "replied" && <>
                <button onClick={() => act(() => setOutcome(id, "positive"))}>Positive</button>
                <button onClick={() => act(() => setOutcome(id, "negative"))}>Negative</button>
                <button className="primary" onClick={() => act(() => markBooked(id))}>Mark booked</button>
              </>}
            </div>
          </div>
        );
      })}
      {!answered.length && <p className="muted">No replies yet.</p>}
    </>
  );
}
