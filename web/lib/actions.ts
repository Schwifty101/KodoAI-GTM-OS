import { supabase } from "./supabase";
import { SETTING_FIELDS, validSetting } from "./settings";
import { CONFIRM_KINDS, PREVIEW_MAX_AGE_MS, alreadyApplied, baseKind, findPreview, isConfirmFlag, jobPayload, type JobRow } from "./runnow";

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

/** Start or Resume Autopilot with a new spend limit (0 = no limit); the spend clock restarts now. A negative limit throws before anything is written. */
export async function startAutopilot(limitUsd: number) {
  const lim = SETTING_FIELDS.find((x) => x.key === "autopilot_limit_usd")!;
  if (!validSetting(lim, limitUsd)) throw new Error("the limit must be 0 (no limit) or more");
  await saveSetting("autopilot_started_at", new Date().toISOString()); // first: the controller must never pair a new limit with an old clock
  await saveSetting("autopilot_limit_usd", limitUsd);
  await saveSetting("autopilot_state", "running");
  await saveSetting("autopilot_on", true);
}

export async function pauseAutopilot() {
  await saveSetting("autopilot_state", "paused by owner"); // state first, on last-write-wins, same order as startAutopilot
  await saveSetting("autopilot_on", false);
}

/** USD recorded in cost_log since `since` (read-only), paged past PostgREST's 1000-row cap. */
export async function autopilotSpent(since: string): Promise<number> {
  let total = 0;
  for (let from = 0; ; from += 1000) {
    const { data, error } = await supabase.from("cost_log").select("usd").gte("created_at", since).order("id").range(from, from + 999);
    if (error) throw new Error(error.message);
    total += (data ?? []).reduce((a, r) => a + Number(r.usd), 0);
    if ((data ?? []).length < 1000) return total;
  }
}

/** Queue a worker job: `argv` is the CLI pass arguments, e.g. ["--batch", "B1"]. A `_test` kind is marked so the live worker skips it (jobPayload). */
export const enqueueJob = (kind: string, argv: string[]) => ok(supabase.from("jobs").insert({ kind, payload: jobPayload(kind, argv) }));

export const cancelJob = (id: string) => ok(supabase.from("jobs").update({ status: "cancelled" }).eq("id", id).eq("status", "queued"));

export const retryJob = (id: string) =>
  ok(supabase.from("jobs").update({ status: "queued", error: null, run_after: new Date().toISOString() }).eq("id", id).in("status", ["failed", "paused_budget"]));

const inFlight = new Set<string>(); // ponytail: closes the double click in one tab (two calls overlap before the first insert lands); a second tab or process still races, only a unique partial index on open jobs closes that (migration, owner gate)
/** Like enqueueJob, but refuses a second identical job (same kind and argv) while one is queued, running or paused for budget. */
export async function enqueueJobOnce(kind: string, argv: string[]) {
  const key = JSON.stringify([kind, argv]);
  if (inFlight.has(key)) throw new Error("an identical job is already open");
  inFlight.add(key);
  try {
    const { data, error } = await supabase.from("jobs").select("payload").eq("kind", kind).in("status", ["queued", "running", "paused_budget"]);
    if (error) throw new Error(error.message);
    if ((data ?? []).some((j) => JSON.stringify(j.payload?.argv ?? []) === JSON.stringify(argv))) throw new Error("an identical job is already open");
    await enqueueJob(kind, argv);
  } finally {
    inFlight.delete(key);
  }
}

/** Preview = the CLI dry run: the pass without --confirm (or any abbreviation of it). */
export async function enqueuePreview(kind: string, argv: string[]) {
  if (argv.some(isConfirmFlag)) throw new Error("a preview never carries --confirm");
  await enqueueJobOnce(kind, argv);
}

/** Apply = argv + --confirm, but only when the database holds a done preview of this exact kind and argv, created under 24 h ago, and no apply of it since. One preview unlocks one Apply. Re-checked here, so a hand-built call cannot skip it. */
export async function enqueueApply(kind: string, argv: string[]) {
  if (!CONFIRM_KINDS.includes(baseKind(kind))) throw new Error(`${kind} has no dry run to apply`);
  if (argv.some(isConfirmFlag)) throw new Error("pass the preview argv; --confirm is added here");
  const { data, error } = await supabase.from("jobs").select("id,kind,status,payload,result,error,created_at,finished_at")
    .eq("kind", kind).contains("payload", { argv }) // containment is only a prefilter (it also returns this argv's applies, any status); the helpers match the argv exactly
    .gte("created_at", new Date(Date.now() - PREVIEW_MAX_AGE_MS).toISOString()).order("created_at", { ascending: false }).limit(50);
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as JobRow[];
  const preview = findPreview(rows, kind, argv);
  if (!preview) throw new Error("no done preview for this argv");
  if (alreadyApplied(rows, kind, argv, preview)) throw new Error("preview already applied: run a new preview");
  await enqueueJobOnce(kind, [...argv, "--confirm"]);
}

/** The Jobs dropdown's enqueue: --confirm on a sheet pass is routed through the Apply guard, anything else is a plain once-only job. */
export const enqueueGuarded = (kind: string, argv: string[]): Promise<void> =>
  CONFIRM_KINDS.includes(baseKind(kind)) && argv.some(isConfirmFlag)
    ? enqueueApply(kind, argv.filter((a) => !isConfirmFlag(a)))
    : enqueueJobOnce(kind, argv);

/** Only a failed tile goes back to pending; running and done tiles are never touched. */
export const retryTile = (id: string) =>
  ok(supabase.from("coverage").update({ status: "pending", error: null }).eq("id", id).eq("status", "failed"));

/** Touch writes filter on the current status, so a claimed (scheduled/sending/sent) touch is never changed. `one` throws when nothing matched. */
async function one(p: PromiseLike<{ data: { id: string }[] | null; error: { message: string } | null }>) {
  const { data, error } = await p;
  if (error) throw new Error(error.message);
  if (!data?.length) throw new Error("that touch is no longer in a state that allows this");
}

/** An edit clears approval and any planned slot; check-drafts re-checks it. Guarded by status, so a touch the tick claims meanwhile matches nothing. */
export const saveDraftEdit = (touchId: string, subject: string, body: string) =>
  one(supabase.from("touches").update({ subject, body, status: "edited", approved_at: null, send_at: null }).eq("id", touchId).in("status", ["drafted", "held", "edited", "approved", "scheduled"]).select("id"));

export const approveTouches = (ids: string[]) =>
  ok(supabase.from("touches").update({ status: "approved", approved_at: new Date().toISOString() }).in("id", ids).eq("status", "drafted"));

export const unapproveTouches = (ids: string[]) =>
  ok(supabase.from("touches").update({ status: "drafted", approved_at: null }).in("id", ids).eq("status", "approved"));

export const skipTouch = (id: string) =>
  one(supabase.from("touches").update({ status: "cancelled" }).eq("id", id).in("status", ["drafted", "held", "edited", "approved", "scheduled"]).select("id"));

/** For a touch stranded in `sending` after a crash: the owner checked Gmail and decides. */
export async function markSent(id: string) {
  const { data, error } = await supabase.from("touches").update({ status: "sent" }).eq("id", id).eq("status", "sending").select("id,lead_id,touch_no,sent_at");
  if (error) throw new Error(error.message);
  const t = data?.[0];
  if (!t) throw new Error("that touch is no longer in a state that allows this");
  if (!t.sent_at) await ok(supabase.from("touches").update({ sent_at: new Date().toISOString() }).eq("id", id));
  if (t.touch_no === 1) await ok(supabase.from("leads").update({ status: "sent" }).eq("id", t.lead_id).eq("status", "drafted"));
}

export const markFailed = (id: string) =>
  one(supabase.from("touches").update({ status: "approved", send_at: null }).eq("id", id).eq("status", "sending").select("id"));

export const startSending = () => saveSetting("sending_on", true);
export const pauseSending = () => saveSetting("sending_on", false);

export async function redraftBatch(batchId: string, instruction: string) {
  const text = instruction.trim();
  if (!text) throw new Error("type an instruction first");
  await enqueueJobOnce("redraft", ["--batch", batchId, `--instruction=${text}`]);
}

export const checkDrafts = () => enqueueJobOnce("check-drafts", []);

/** Draft the approved selected leads of one outreach batch (leads.batch_no); a paid LLM pass. */
export const draftBatch = (batchNo: number) => enqueueJobOnce("draft", ["--batch-no", String(batchNo)]);

/** Draft the Touch 2 and Touch 3 follow-ups that are due; a paid LLM pass. */
export const draftFollowups = () => enqueueJobOnce("followups", []);
