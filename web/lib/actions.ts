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

/** The operator clears a bounce-spike pause once they have looked at why; the ramp restarts from today. */
export const clearPause = (mailboxId: string) =>
  ok(supabase.from("mailboxes").update({ paused: false, paused_reason: null, ramp_from: new Date().toISOString().slice(0, 10) }).eq("id", mailboxId));

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

/** Like enqueueJob, but refuses a second identical job (same kind and argv) while one is queued, running or paused for budget. */
export async function enqueueJobOnce(kind: string, argv: string[]) {
  const { data, error } = await supabase.from("jobs").select("payload").eq("kind", kind).in("status", ["queued", "running", "paused_budget"]);
  if (error) throw new Error(error.message);
  if ((data ?? []).some((j) => JSON.stringify(j.payload?.argv ?? []) === JSON.stringify(argv))) throw new Error("an identical job is already open");
  await enqueueJob(kind, argv);
}

/** Only a failed tile goes back to pending; running and done tiles are never touched. */
export const retryTile = (id: string) =>
  ok(supabase.from("coverage").update({ status: "pending", error: null }).eq("id", id).eq("status", "failed"));

/** Touch writes filter on the current status, so a claimed (scheduled/sending/sent) touch is never changed. `one` throws when nothing matched. */
async function one(p: PromiseLike<{ data: { id: string }[] | null; error: { message: string } | null }>) {
  const { data, error } = await p;
  if (error) throw new Error(error.message);
  if (!data?.length) throw new Error("that touch is no longer in a state that allows this");
}

/** An edit clears approval; check-drafts re-checks it. */
export const saveDraftEdit = (touchId: string, subject: string, body: string) =>
  one(supabase.from("touches").update({ subject, body, status: "edited", approved_at: null }).eq("id", touchId).in("status", ["drafted", "held", "edited", "approved"]).select("id"));

export const approveTouches = (ids: string[]) =>
  ok(supabase.from("touches").update({ status: "approved", approved_at: new Date().toISOString() }).in("id", ids).eq("status", "drafted"));

export const unapproveTouches = (ids: string[]) =>
  ok(supabase.from("touches").update({ status: "drafted", approved_at: null }).in("id", ids).eq("status", "approved"));

export const skipTouch = (id: string) =>
  one(supabase.from("touches").update({ status: "cancelled" }).eq("id", id).in("status", ["drafted", "held", "edited", "approved"]).select("id"));

/** For a touch stranded in `sending` after a crash: the owner checked Gmail and decides. */
export const markSent = (id: string) =>
  one(supabase.from("touches").update({ status: "sent", sent_at: new Date().toISOString() }).eq("id", id).eq("status", "sending").select("id"));

export const markFailed = (id: string) =>
  one(supabase.from("touches").update({ status: "approved", send_at: null }).eq("id", id).eq("status", "sending").select("id"));

export const startSending = () => saveSetting("sending_on", true);
export const pauseSending = () => saveSetting("sending_on", false);

export async function redraftBatch(batchId: string, instruction: string) {
  const text = instruction.trim();
  if (!text) throw new Error("type an instruction first");
  await enqueueJobOnce("redraft", ["--batch", batchId, "--instruction", text]);
}

export const checkDrafts = () => enqueueJobOnce("check-drafts", []);
