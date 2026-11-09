import { supabase } from "./supabase";

// Every operator write goes through here so scripts/verify.ts can exercise the exact same calls under RLS.
async function ok<T extends { error: { message: string } | null }>(p: PromiseLike<T>): Promise<void> {
  const { error } = await p;
  if (error) throw new Error(error.message);
}

/** Approve = ready for the draft pass. Only leads still `selected` are touched. */
export const approveLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ approved: true }).in("id", ids).eq("status", "selected"));

export const unapproveLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ approved: false }).in("id", ids).eq("status", "selected"));

/** Reject = out of the pipeline, with the operator recorded as the reason. */
export const rejectLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ status: "rejected", reject_reason: "operator", approved: false }).in("id", ids).eq("status", "selected"));

/** The operator clears a bounce-spike pause once they have looked at why. */
export const clearPause = (mailboxId: string) =>
  ok(supabase.from("mailboxes").update({ paused: false, paused_reason: null }).eq("id", mailboxId));

/** Soban's own call on a reply (positive / negative / other); recorded on the latest sent touch. */
export async function setOutcome(leadId: string, outcome: "positive" | "negative" | "other") {
  const { data, error } = await supabase.from("touches").select("id").eq("lead_id", leadId).eq("status", "sent").order("touch_no", { ascending: false }).limit(1);
  if (error) throw new Error(error.message);
  if (data?.[0]) await ok(supabase.from("touches").update({ outcome }).eq("id", data[0].id));
}

/** Booked is only ever set by hand, and only from `replied`. */
export const markBooked = (leadId: string) =>
  ok(supabase.from("leads").update({ status: "booked" }).eq("id", leadId).eq("status", "replied"));
