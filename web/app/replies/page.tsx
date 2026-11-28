"use client";

import { useCallback, useEffect, useState } from "react";
import { useRequireSession } from "@/lib/useRequireSession";
import { markBooked, setOutcome } from "@/lib/actions";
import { hint0017 } from "@/lib/metrics";
import { gmailThreadUrl, replyBucket, type ReplyBucket } from "@/lib/replies";
import { loadReplies, type ReplyRow } from "@/lib/repliesData";

const SECTIONS: { key: ReplyBucket; title: string }[] = [
  { key: "look", title: "Needs a look" },
  { key: "positive", title: "Positive" },
  { key: "booked", title: "Booked" },
  { key: "declined", title: "Declined" },
  { key: "bounced", title: "Bounced" },
];
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "date not recorded");

export default function Replies() {
  const ready = useRequireSession();
  const [rows, setRows] = useState<ReplyRow[]>([]);
  const [address, setAddress] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await loadReplies();
      setErr(""); setRows(r.rows); setAddress(r.address); setCheckedAt(r.checkedAt);
    } catch (e) { setErr(hint0017((e as Error).message)); }
  }, []);
  useEffect(() => { if (ready) load(); }, [ready, load]);
  if (!ready) return null;

  const act = async (fn: () => Promise<void>) => { try { await fn(); await load(); } catch (e) { setErr(hint0017((e as Error).message)); } };

  return (
    <>
      <h1>Replies</h1>
      {err && <p className="err">{err}</p>}
      <p className="muted">Replies last read: {checkedAt ? new Date(checkedAt).toLocaleString() : "never"}.</p>

      {SECTIONS.map(({ key, title }) => {
        const list = rows.filter((r) => replyBucket(r.status, r.outcome) === key);
        const acts = key === "look" || key === "positive";
        return (
          <section key={key}>
            <h2>{title} ({list.length})</h2>
            {list.length ? (
              <table><thead><tr><th>Business</th><th>Owner email</th><th>Batch</th><th>Angle</th><th>Touch</th><th>Date</th><th>Gmail</th>{acts && <th>Actions</th>}</tr></thead><tbody>
                {list.map((r) => (
                  <tr key={r.lead_id}>
                    <td><strong>{r.name}</strong></td>
                    <td>{r.owner_email ?? "no email"}</td>
                    <td>{r.batch_no ?? "no batch"}</td>
                    <td>{r.vector ?? "(none)"} <span className="muted">{r.lane}</span></td>
                    <td>Touch {r.touch_no}</td>
                    <td>{when(r.outcome_at)}</td>
                    <td>{r.thread_id && address ? <a href={gmailThreadUrl(address, r.thread_id)} target="_blank" rel="noreferrer">Open in Gmail</a> : r.thread_id ?? "no thread id"}</td>
                    {acts && <td>
                      {key === "look" && <>
                        <button onClick={() => act(() => setOutcome(r.lead_id, "positive"))}>Positive</button>{" "}
                        <button onClick={() => act(() => setOutcome(r.lead_id, "negative"))}>Negative</button>{" "}
                        <button onClick={() => act(() => setOutcome(r.lead_id, "other"))}>Other</button>{" "}
                      </>}
                      <button className="primary" onClick={() => act(() => markBooked(r.lead_id))}>Mark booked</button>
                    </td>}
                  </tr>
                ))}
              </tbody></table>
            ) : <p className="muted">none</p>}
          </section>
        );
      })}
    </>
  );
}
