"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRequireSession } from "@/lib/useRequireSession";
import { approveTouches, checkDrafts, draftBatch, redraftBatch, saveDraftEdit } from "@/lib/actions";
import { fetchAll } from "@/lib/fetchAll";
import type { Touch } from "@/lib/types";

const SAMPLE = 10;
const pad = (n: number) => String(n).padStart(2, "0");
// enqueueJobOnce refuses a second identical open job with "an identical job is already open".
const queued = (e: Error): never => { throw new Error(e.message.includes("already open") ? "already queued" : e.message); };
type Batch = { id: string; name: string; draft_instruction: string | null };
type DraftTouch = Touch & { leads: { name: string; owner_name: string | null; owner_email: string | null; vector: string | null; signal_led: boolean } };
type Skipped = { id: string; name: string; reject_reason: string };
const COLS = "id,lead_id,touch_no,status,subject,body,objective,problems,leads!inner(name,owner_name,owner_email,vector,signal_led,batch_id)";

const shuffle = <T,>(a: T[]) => { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };

export default function Drafts() {
  const ready = useRequireSession();
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchId, setBatchId] = useState("");
  const [touches, setTouches] = useState<DraftTouch[]>([]);
  const [skipped, setSkipped] = useState<Skipped[]>([]);
  const [sample, setSample] = useState<string[]>([]);
  const [pos, setPos] = useState(0);
  const [flagged, setFlagged] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [subj, setSubj] = useState("");
  const [body, setBody] = useState("");
  const [instr, setInstr] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [redrafting, setRedrafting] = useState(false);
  const [toDraft, setToDraft] = useState<[number, number][]>([]); // [outreach batch_no, approved leads still undrafted]

  const loadToDraft = useCallback(async () => {
    try {
      const rows = await fetchAll<{ batch_no: number }>((a, b) =>
        supabase.from("leads").select("batch_no").eq("status", "selected").eq("approved", true).not("batch_no", "is", null).order("id").range(a, b));
      const m = new Map<number, number>();
      rows.forEach((r) => m.set(r.batch_no, (m.get(r.batch_no) ?? 0) + 1));
      setToDraft([...m].sort((a, b) => a[0] - b[0]));
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (ready) loadToDraft(); }, [ready, loadToDraft]);

  useEffect(() => {
    if (!ready) return;
    supabase.from("batches").select("id,name,draft_instruction").order("created_at", { ascending: false }).then(({ data, error }) => {
      if (error) return setErr(error.message);
      setBatches(data ?? []);
      if (data?.[0]) setBatchId(data[0].id);
    });
  }, [ready]);

  const load = useCallback(async () => {
    if (!batchId) return;
    const [t, s, j] = await Promise.all([
      supabase.from("touches").select(COLS).eq("touch_no", 1).eq("leads.batch_id", batchId).neq("status", "cancelled").order("id"),
      supabase.from("leads").select("id,name,reject_reason").eq("batch_id", batchId).eq("status", "selected").not("reject_reason", "is", null),
      supabase.from("jobs").select("payload").eq("kind", "redraft").in("status", ["queued", "running"]),
    ]);
    if (t.error || s.error || j.error) return setErr((t.error ?? s.error ?? j.error)!.message);
    setRedrafting((j.data ?? []).some((r) => (r.payload?.argv ?? [])[1] === batchId));
    setErr(""); setTouches((t.data ?? []) as unknown as DraftTouch[]); setSkipped((s.data ?? []) as Skipped[]);
    return (t.data ?? []) as unknown as DraftTouch[];
  }, [batchId]);

  // New batch: reshuffle the sample once. Later reloads keep it, so an edited draft stays in the sample.
  useEffect(() => {
    setSample([]); setPos(0); setFlagged(new Set()); setEditing(null); setMsg("");
    load().then((rows) => setSample(shuffle((rows ?? []).filter((r) => r.status === "drafted").map((r) => r.id)).slice(0, SAMPLE)));
  }, [load]);

  const checking = touches.some((t) => t.status === "edited");
  useEffect(() => { if (checking || redrafting) { const i = setInterval(load, 4000); return () => clearInterval(i); } }, [checking, redrafting, load]);
  if (!ready) return null;

  const by = (s: string) => touches.filter((t) => t.status === s);
  const readyIds = by("drafted").filter((t) => !flagged.has(t.id)).map((t) => t.id);
  const cur = touches.find((t) => t.id === sample[pos]);
  const batch = batches.find((b) => b.id === batchId);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(""); setErr("");
    try { await fn(); setMsg(ok); await load(); } catch (e) { setErr((e as Error).message); }
  }
  const draftNow = (no: number, n: number) => {
    if (!window.confirm(`Draft Batch ${pad(no)}: ${n} approved lead${n === 1 ? "" : "s"}. Drafting makes LLM calls, and they are paid only if allow_paid_gemini is on (Settings). Queue the draft job?`)) return;
    return act(() => draftBatch(no).catch(queued), `Draft queued for Batch ${pad(no)}`).then(loadToDraft);
  };
  const startEdit = (t: DraftTouch) => { setEditing(t.id); setSubj(t.subject ?? ""); setBody(t.body ?? ""); };
  const save = (id: string) => act(async () => {
    await saveDraftEdit(id, subj, body);
    setEditing(null);
    await checkDrafts().catch(() => {}); // an identical check job already queued is fine
  }, "Saved, checking...");

  const editor = (t: DraftTouch) => (
    <div>
      <input style={{ width: "100%", marginBottom: 6 }} value={subj} onChange={(e) => setSubj(e.target.value)} />
      <textarea style={{ width: "100%" }} rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="bar"><button className="primary" onClick={() => save(t.id)}>Save</button><button onClick={() => setEditing(null)}>Cancel</button></div>
    </div>
  );

  return (
    <>
      <h1>Drafts</h1>
      <div className="bar">
        <select value={batchId} onChange={(e) => setBatchId(e.target.value)}>
          {batches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <span>{touches.length} drafts · <strong>{by("drafted").length} ready</strong> · {by("held").length} held · {by("approved").length} approved{checking && " · checking..."}</span>
      </div>
      {redrafting && <p className="msg">Regenerating this batch... approval is off until it finishes.</p>}
      {batch?.draft_instruction && <p className="muted">Last regenerate instruction: {batch.draft_instruction}</p>}
      {msg && <p className="msg">{msg}</p>}{err && <p className="err">{err}</p>}

      <div className="card">
        <strong>Draft an outreach batch</strong>
        {toDraft.map(([no, n]) => (
          <div className="bar" key={no} style={{ marginTop: 6 }}>
            <button onClick={() => draftNow(no, n)}>Draft Batch {pad(no)}</button>
            <span className="muted">{n} approved, not yet drafted</span>
          </div>
        ))}
        {!toDraft.length && <p className="muted">No approved leads waiting to be drafted. Approve selected leads first.</p>}
      </div>

      <div className="card">
        <div className="bar">
          <strong>Approve and regenerate</strong>
          <button className="primary" disabled={!readyIds.length || redrafting} onClick={() => act(() => approveTouches(readyIds), `Approved ${readyIds.length}`)}>Approve all ready ({readyIds.length})</button>
        </div>
        <textarea style={{ width: "100%" }} rows={2} placeholder="New instruction for the whole batch, e.g. warmer opener" value={instr} onChange={(e) => setInstr(e.target.value)} />
        <div className="bar" style={{ marginTop: 6 }}>
          <button disabled={!instr.trim()} onClick={() => act(async () => { await redraftBatch(batchId, instr); setInstr(""); }, "Regenerate queued: unsent drafts will be redrafted with this instruction")}>Regenerate batch with this instruction</button>
          <span className="muted">Approved drafts are left alone.</span>
        </div>
      </div>

      <h2>Sample {sample.length ? `(${Math.min(pos + 1, sample.length)} of ${sample.length})` : ""}</h2>
      {!sample.length && <p className="muted">No ready drafts in this batch.</p>}
      {cur && (
        <div className="card">
          <div className="muted">To: {cur.leads.owner_name ?? "?"} · {cur.leads.name} · {cur.leads.owner_email}</div>
          <div className="bar" style={{ margin: "4px 0" }}>
            <span className="pill">{cur.leads.vector ?? "no angle"}</span>
            <span className={`pill ${cur.leads.signal_led ? "ok" : ""}`}>{cur.leads.signal_led ? "signal-led" : "relevance-led"}</span>
            {cur.status === "edited" && <span className="pill">checking...</span>}
            {cur.status === "held" && <span className="pill bad">held: {cur.problems.join(", ")}</span>}
            {["approved", "scheduled", "sending", "sent"].includes(cur.status) && <span className="pill ok">{cur.status}</span>}
          </div>
          {editing === cur.id ? editor(cur) : (
            <>
              <strong>{cur.subject}</strong>
              <pre className="draft">{cur.body}</pre>
              <div className="bar">
                <button className="primary" disabled={pos >= sample.length - 1} onClick={() => setPos(pos + 1)}>Looks good</button>
                {["drafted", "held", "edited", "approved"].includes(cur.status) && <button onClick={() => startEdit(cur)}>Edit</button>}
                <button className={flagged.has(cur.id) ? "danger" : ""} onClick={() => setFlagged((f) => new Set(f).add(cur.id))}>Flag a problem</button>
                <button disabled={pos === 0} onClick={() => setPos(pos - 1)}>Back</button>
              </div>
              {flagged.has(cur.id) && <p className="err">Flagged and left out of Approve all. Edit it, or regenerate the batch with an instruction above.</p>}
              {pos >= sample.length - 1 && <p className="muted">End of the sample.</p>}
            </>
          )}
        </div>
      )}

      <h2>Held ({by("held").length + skipped.length})</h2>
      <p className="muted">Held drafts failed a check and cannot be approved until edited. Skipped leads were never drafted.</p>
      {by("held").map((t) => (
        <div className="card" key={t.id}>
          <div className="bar" style={{ marginBottom: 4 }}><strong>{t.leads.name}</strong><span className="pill bad">{t.problems.join(", ") || "held"}</span>
            {editing !== t.id && <button onClick={() => startEdit(t)}>Edit</button>}</div>
          {editing === t.id ? editor(t) : <><strong>{t.subject}</strong><pre className="draft">{t.body}</pre></>}
        </div>
      ))}
      {skipped.map((l) => <div className="card" key={l.id}><strong>{l.name}</strong> <span className="pill bad">{l.reject_reason}</span> <span className="muted">not drafted</span></div>)}
      {!by("held").length && !skipped.length && <p className="muted">Nothing held.</p>}
    </>
  );
}
