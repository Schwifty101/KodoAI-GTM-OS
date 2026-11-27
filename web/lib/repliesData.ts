import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { isTestLead } from "./metrics";

export type ReplyRow = {
  lead_id: string; name: string; owner_email: string | null; status: string; batch_no: number | null;
  vector: string | null; lane: string; touch_no: number; outcome: string | null; outcome_at: string | null; thread_id: string | null;
};

type TouchRaw = { id: string; touch_no: number; status: string; outcome: string | null; outcome_at: string | null; gmail_thread_id: string | null };
type LeadRaw = { id: string; name: string; owner_email: string | null; status: string; batch_no: number | null; vector: string | null; signal_led: boolean; place_id: string };

const LEAD = "id,name,owner_email,status,batch_no,vector,signal_led,place_id";
const TOUCH = "id,touch_no,status,outcome,outcome_at,gmail_thread_id";
const ANSWERED = ["replied", "booked", "unsubscribed", "bounced"];

/** One row per lead, built from the two reads (leads in an answered status with their touches; touches with an outcome with their lead). Pure. */
export function buildReplyRows(leads: (LeadRaw & { touches: TouchRaw[] })[], outcomeTouches: (TouchRaw & { leads: LeadRaw | null })[], includeTest: boolean): ReplyRow[] {
  const byLead = new Map<string, LeadRaw & { touches: TouchRaw[] }>();
  for (const l of leads) byLead.set(l.id, { ...l, touches: [...l.touches] });
  for (const { leads: l, ...t } of outcomeTouches) {
    if (!l) continue;
    const r = byLead.get(l.id) ?? { ...l, touches: [] };
    if (!r.touches.some((x) => x.id === t.id)) r.touches.push(t);
    byLead.set(l.id, r);
  }
  const rows: ReplyRow[] = [];
  for (const l of byLead.values()) {
    if (!includeTest && isTestLead(l.place_id)) continue;
    const byNo = [...l.touches].sort((a, b) => b.touch_no - a.touch_no);
    const sent = byNo.filter((t) => t.status === "sent");
    // The last sent touch that has an outcome, else the last sent touch (else the last touch of any status).
    const t = sent.find((x) => x.outcome !== null) ?? sent[0] ?? byNo[0];
    if (!t) continue;
    rows.push({
      lead_id: l.id, name: l.name, owner_email: l.owner_email, status: l.status, batch_no: l.batch_no, vector: l.vector,
      lane: l.signal_led ? "signal-led" : "relevance-led", touch_no: t.touch_no, outcome: t.outcome, outcome_at: t.outcome_at, thread_id: t.gmail_thread_id,
    });
  }
  const at = (r: ReplyRow) => (r.outcome_at ? Date.parse(r.outcome_at) : -Infinity);
  return rows.sort((a, b) => at(b) - at(a) || a.name.localeCompare(b.name));
}

/** Spec 7.6. touches.outcome_at needs migration 0017: callers show hint0017 on the error. */
export async function loadReplies(includeTest = false): Promise<{ rows: ReplyRow[]; address: string | null; checkedAt: string | null }> {
  const [leads, outcomeTouches, mb] = await Promise.all([
    fetchAll<LeadRaw & { touches: TouchRaw[] }>((f, t) =>
      supabase.from("leads").select(`${LEAD},touches(${TOUCH})`).in("status", ANSWERED).order("id").range(f, t)),
    // The client types a joined row as an array; the many-to-one join comes back as one object, so the page type is asserted.
    fetchAll<TouchRaw & { leads: LeadRaw | null }>((f, t) =>
      supabase.from("touches").select(`${TOUCH},leads(${LEAD})`).not("outcome", "is", null).order("id").range(f, t) as unknown as PromiseLike<{ data: (TouchRaw & { leads: LeadRaw | null })[] | null; error: { message: string } | null }>),
    supabase.from("mailboxes").select("address,replies_checked_at").order("address").limit(1),
  ]);
  if (mb.error) throw new Error(mb.error.message);
  return { rows: buildReplyRows(leads, outcomeTouches, includeTest), address: mb.data?.[0]?.address ?? null, checkedAt: mb.data?.[0]?.replies_checked_at ?? null };
}
