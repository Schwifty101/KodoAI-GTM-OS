import { supabase } from "./supabase";
import { SETTING_FIELDS, validSetting } from "./settings";

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

/** Upsert one owner setting; the key and the value's type are checked against SETTING_FIELDS first. */
export async function saveSetting(key: string, value: unknown) {
  const f = SETTING_FIELDS.find((x) => x.key === key);
  if (!f) throw new Error(`unknown setting ${key}`);
  if (!validSetting(f, value)) throw new Error(`${key} needs a ${f.type}`);
  await ok(supabase.from("settings").upsert({ key, value, updated_at: new Date().toISOString() }));
}

/** Queue a worker job: `argv` is the CLI pass arguments, e.g. ["--batch", "B1"]. */
export const enqueueJob = (kind: string, argv: string[]) => ok(supabase.from("jobs").insert({ kind, payload: { argv } }));

export const cancelJob = (id: string) => ok(supabase.from("jobs").update({ status: "cancelled" }).eq("id", id).eq("status", "queued"));

export const retryJob = (id: string) =>
  ok(supabase.from("jobs").update({ status: "queued", error: null, run_after: new Date().toISOString() }).eq("id", id).in("status", ["failed", "paused_budget"]));
