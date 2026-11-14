// Dev verification: seeds test rows, mints a one-off operator session, and runs the app's real write actions under RLS.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts   (reads the secret key from ../.env; never bundled into the app)
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { approveLeads, approveTouches, markSent, unapproveTouches, cancelJob, clearPause, markFailed, redraftBatch, saveDraftEdit, skipTouch, enqueueJob, enqueueJobOnce, markBooked, rejectLeads, retryJob, retryTile, saveSetting, setOutcome, unapproveLeads } from "../lib/actions";
import { SETTING_FIELDS, validSetting } from "../lib/settings";
import { splitArgs } from "../lib/args";
import { execFileSync } from "node:child_process";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };

const sa = (i: string, want: string[]) => JSON.stringify(splitArgs(i)) === JSON.stringify(want);
check("splitArgs plain", sa("--batch abc", ["--batch", "abc"]));
check("splitArgs double quotes", sa('--query "med spa" --max-places 20', ["--query", "med spa", "--max-places", "20"]));
check("splitArgs single quotes", sa("--query 'med spa' x", ["--query", "med spa", "x"]));
check("splitArgs unclosed quote takes the rest", sa('--query "med spa x', ["--query", "med spa x"]));
check("splitArgs extra spaces", sa("  a   b  ", ["a", "b"]));
check("splitArgs empty", sa("", []) && sa("   ", []));

const { data: batch } = await admin.from("batches").insert({ name: "TEST web verify" }).select("id").single();
const mk = (i: number, status: string) => ({ place_id: `TEST_v${i}`, name: `Spa ${i}`, status, batch_id: batch!.id, domain: `v${i}.com` });
await admin.from("leads").insert([mk(1, "selected"), mk(2, "selected"), mk(3, "selected"), mk(4, "sent")]);
const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

const row = async (n: number) => (await admin.from("leads").select("status,approved,reject_reason").eq("place_id", `TEST_v${n}`).single()).data!;
const id = async (n: number) => (await admin.from("leads").select("id").eq("place_id", `TEST_v${n}`).single()).data!.id as string;
const [a, b, c, d] = [await id(1), await id(2), await id(3), await id(4)];

await approveLeads([a, b, d]);
check("approve marks selected leads approved", (await row(1)).approved && (await row(2)).approved);
check("approve leaves a lead that is not `selected` alone", !(await row(4)).approved && (await row(4)).status === "sent");
await unapproveLeads([b]);
check("unapprove clears approval", !(await row(2)).approved);
await rejectLeads([c, d]);
const rc = await row(3);
check("reject sets status rejected, reason operator, not approved", rc.status === "rejected" && rc.reject_reason === "operator" && !rc.approved);
check("reject leaves a lead that is not `selected` alone", (await row(4)).status === "sent");

// Task 19: the dashboard view under the operator session
await admin.from("leads").update({ owner_email: "d@v1.com", email_verified: true }).eq("place_id", "TEST_v1");
const dm = await supabase.from("batch_metrics").select("scraped,enriched").eq("batch_id", batch!.id).single();
check("dashboard view is readable by the operator and counts the batch", dm.data?.scraped === 4 && dm.data?.enriched === 1);

// Task 18: outreach actions
const { data: mb } = await admin.from("mailboxes").insert({ address: "pytest-verify@example.com", paused: true, paused_reason: "test" }).select("id").single();
await clearPause(mb!.id);
const m = (await admin.from("mailboxes").select("paused,paused_reason").eq("id", mb!.id).single()).data!;
check("clearPause unpauses and clears the reason", !m.paused && m.paused_reason === null);
check("clearPause sets ramp_from to today", (await admin.from("mailboxes").select("ramp_from").eq("id", mb!.id).single()).data!.ramp_from === new Date().toISOString().slice(0, 10));
await admin.from("leads").update({ status: "replied" }).eq("place_id", "TEST_v1");
await admin.from("touches").insert([{ lead_id: a, touch_no: 1, status: "sent" }, { lead_id: a, touch_no: 2, status: "sent" }]);
await setOutcome(a, "positive");
const outs = (await admin.from("touches").select("touch_no,outcome").eq("lead_id", a).order("touch_no")).data!;
check("setOutcome records on the latest sent touch only", outs[0].outcome === null && outs[1].outcome === "positive");
await markBooked(a);
check("markBooked sets booked from replied", (await row(1)).status === "booked");
await markBooked(b);
check("markBooked does nothing to a lead that has not replied", (await row(2)).status === "selected");
await admin.from("mailboxes").delete().eq("id", mb!.id);

// Task 6: settings and jobs actions
const pyDefaults = JSON.parse(execFileSync("uv", ["run", "python", "-c", "import json;from gtm.settings_store import DEFAULTS;print(json.dumps(DEFAULTS))"], { cwd: "..", encoding: "utf8" }));
check("SETTING_FIELDS keys and defaults equal the Python DEFAULTS",
  JSON.stringify(SETTING_FIELDS.map((f) => f.key).sort()) === JSON.stringify(Object.keys(pyDefaults).sort()) && SETTING_FIELDS.every((f) => f.def === pyDefaults[f.key]));
const fld = (k: string) => SETTING_FIELDS.find((f) => f.key === k)!;
check("validSetting enforces ranges",
  !validSetting(fld("walk_hour_utc"), 24) && !validSetting(fld("walk_hour_utc"), -1) && validSetting(fld("walk_hour_utc"), 0) && validSetting(fld("walk_hour_utc"), 23)
  && !validSetting(fld("walk_escalate_at"), 1.5) && validSetting(fld("walk_escalate_at"), 0.8)
  && !validSetting(fld("walk_queries"), "") && !validSetting(fld("walk_queries"), "  ") && validSetting(fld("walk_queries"), "med spa")
  && !validSetting(fld("walk_schedule_enabled"), "yes") && !validSetting(fld("walk_tiles_per_run"), 0));
const wt = async () => (await admin.from("settings").select("value").eq("key", "weekly_target")).data?.[0]?.value;
const wt0 = await wt();
await saveSetting("weekly_target", 150);
check("saveSetting persists", (await wt()) === 150);
const nSettings = async () => (await admin.from("settings").select("key", { count: "exact", head: true })).count;
const n0 = await nSettings();
const throws = async (f: () => Promise<void>) => { try { await f(); return false; } catch { return true; } };
check("saveSetting rejects an unknown key", await throws(() => saveSetting("nope", 1)) && (await nSettings()) === n0);
check("saveSetting rejects a wrong-typed value", await throws(() => saveSetting("weekly_target", "x")) && (await wt()) === 150);
if (wt0 === undefined) await admin.from("settings").delete().eq("key", "weekly_target"); else await admin.from("settings").update({ value: wt0 }).eq("key", "weekly_target");

const jstat = async (i: string) => (await admin.from("jobs").select("status").eq("id", i).single()).data!.status;
await enqueueJob("clean", ["--batch", "TEST"]);
const q = (await admin.from("jobs").select("id,status").eq("kind", "clean").contains("payload", { argv: ["--batch", "TEST"] })).data!;
check("enqueueJob inserts one queued job", q.length === 1 && q[0].status === "queued");
await cancelJob(q[0].id);
check("cancelJob cancels a queued job", (await jstat(q[0].id)) === "cancelled");
const seed = async (status: string) => (await admin.from("jobs").insert({ kind: "clean", payload: { test: true }, status }).select("id").single()).data!.id as string;
const [jr, jf, jd] = [await seed("running"), await seed("failed"), await seed("done")];
await cancelJob(jr);
check("cancelJob leaves a running job alone", (await jstat(jr)) === "running");
await retryJob(jf); await retryJob(jd);
check("retryJob requeues a failed job", (await jstat(jf)) === "queued");
check("retryJob ignores a done job", (await jstat(jd)) === "done");
await admin.from("jobs").delete().or("payload->>test.eq.true,payload->argv.cs.[\"TEST\"]");

// Plan 3b Task 1. Test jobs use kind `walk_test` (not job-runnable) so the live worker never takes them.
const onceArgv = ["--tiles", "1", "TEST_once"];
const openOnce = async () => (await admin.from("jobs").select("id,status").eq("kind", "walk_test").contains("payload", { argv: onceArgv })).data!;
await enqueueJobOnce("walk_test", onceArgv);
check("enqueueJobOnce refuses a second identical open job", (await throws(() => enqueueJobOnce("walk_test", onceArgv))) && (await openOnce()).length === 1);
await admin.from("jobs").update({ status: "done" }).eq("id", (await openOnce())[0].id);
await enqueueJobOnce("walk_test", onceArgv);
check("enqueueJobOnce allows a new job once the old one is done", (await openOnce()).length === 2);
await admin.from("jobs").delete().eq("kind", "walk_test").contains("payload", { argv: onceArgv });

const sts = ["failed", "running", "done", "pending"];
await admin.from("coverage").insert(sts.map((st, i) => ({ seq: 900000 + i, metro_rank: 0, metro: "TEST", state: "ZZ", tile: `TEST_rt_${st}`, status: st, error: st === "failed" ? "boom" : null })));
const cov = (await admin.from("coverage").select("id,status").eq("metro", "TEST")).data!;
for (const r of cov) await retryTile(r.id);
const after = (await admin.from("coverage").select("tile,status,error").eq("metro", "TEST")).data!;
const st = (n: string) => after.find((r) => r.tile === `TEST_rt_${n}`)!;
check("retryTile only flips failed", st("failed").status === "pending" && st("failed").error === null && st("running").status === "running" && st("done").status === "done" && st("pending").status === "pending");
await admin.from("coverage").delete().eq("metro", "TEST");


// Plan 4 Task 9: draft and send actions on REHEARSAL_C_ rows (a claimed touch must never change)
{
  const { data: rb } = await admin.from("batches").insert({ name: "REHEARSAL_C_ verify" }).select("id").single();
  const sts = ["drafted", "held", "approved", "scheduled", "sending", "sent"];
  await admin.from("leads").insert(sts.map((s, i) => ({ place_id: `REHEARSAL_C_t${i}`, name: `RC ${s}`, status: "drafted", batch_id: rb!.id, domain: `rc${i}.com` })));
  const ids = (await admin.from("leads").select("id,place_id").like("place_id", "REHEARSAL_C_t%")).data!;
  const lid = (i: number) => ids.find((r) => r.place_id === `REHEARSAL_C_t${i}`)!.id as string;
  await admin.from("touches").insert(sts.map((s, i) => ({ lead_id: lid(i), touch_no: 1, status: s, subject: "old", body: "old body", approved_at: s === "approved" ? new Date().toISOString() : null })));
  const tr = async (i: number) => (await admin.from("touches").select("id,status,subject,body,approved_at,send_at").eq("lead_id", lid(i)).single()).data!;
  const T = Object.fromEntries(await Promise.all(sts.map(async (s, i) => [s, (await tr(i)).id as string])));

  await saveDraftEdit(T.drafted, "new / subj", "new body");
  const e = await tr(0);
  check("edit sets edited and saves the text", e.status === "edited" && e.subject === "new / subj" && e.body === "new body");
  await saveDraftEdit(T.approved, "x / y", "edited approved");
  const ea = await tr(2);
  check("edit clears approval", ea.status === "edited" && ea.approved_at === null);
  await admin.from("touches").update({ send_at: new Date().toISOString() }).eq("id", T.scheduled);
  await saveDraftEdit(T.scheduled, "s / s", "edited scheduled");
  const es = await tr(3);
  check("edit unschedules a scheduled touch", es.status === "edited" && es.send_at === null && es.approved_at === null && es.body === "edited scheduled");
  await admin.from("touches").update({ status: "scheduled", body: "old body" }).eq("id", T.scheduled);
  for (const s of ["sending", "sent"]) {
    const i = sts.indexOf(s);
    check(`edit refuses a ${s} touch`, (await throws(() => saveDraftEdit(T[s], "hack", "hack"))) && (await tr(i)).body === "old body" && (await tr(i)).status === s);
  }
  await admin.from("touches").update({ status: "drafted" }).eq("id", T.approved);
  await approveTouches(Object.values(T));
  const after2 = await Promise.all(sts.map((_, i) => tr(i)));
  check("approve only moves drafted", after2.map((r) => r.status).join() === "edited,held,approved,scheduled,sending,sent" && after2[2].approved_at !== null);
  await admin.from("touches").update({ status: "drafted" }).eq("id", T.drafted);
  await skipTouch(T.sent).catch(() => {}); await skipTouch(T.drafted);
  check("skip cancels a drafted touch and refuses a sent one", (await tr(0)).status === "cancelled" && (await tr(5)).status === "sent");
  await markFailed(T.scheduled).catch(() => {});
  check("markFailed refuses a touch that is not sending", (await tr(3)).status === "scheduled");
  await markSent(T.scheduled).catch(() => {});
  check("markSent refuses a touch that is not sending", (await tr(3)).status === "scheduled");
  await markFailed(T.sending);
  check("markFailed returns a sending touch to approved", (await tr(4)).status === "approved");
  await markSent(T.sending).catch(() => {});
  check("markSent refuses an approved touch", (await tr(4)).status === "approved");
  await unapproveTouches([T.sending]);
  check("unapprove returns approved to drafted", (await tr(4)).status === "drafted" && (await tr(4)).approved_at === null);
  await admin.from("leads").insert({ place_id: "REHEARSAL_C_stuck", name: "RC stuck", status: "drafted", batch_id: rb!.id, domain: "rcstuck.com" });
  const stuckLead = (await admin.from("leads").select("id").eq("place_id", "REHEARSAL_C_stuck").single()).data!.id as string;
  await admin.from("touches").insert({ lead_id: stuckLead, touch_no: 1, status: "sending", subject: "s", body: "b" });
  const stuckTouch = (await admin.from("touches").select("id").eq("lead_id", stuckLead).single()).data!.id as string;
  await markSent(stuckTouch);
  const st1 = (await admin.from("touches").select("status,sent_at").eq("id", stuckTouch).single()).data!;
  check("markSent sends a stranded touch: sent_at set, Touch 1 lead becomes sent", st1.status === "sent" && st1.sent_at !== null && (await admin.from("leads").select("status").eq("id", stuckLead).single()).data!.status === "sent");
  const dashArgv = ["--batch", rb!.id, "--instruction=-warmer opener"];
  await redraftBatch(rb!.id, "-warmer opener");
  const dj = (await admin.from("jobs").select("id,payload").eq("kind", "redraft").contains("payload", { argv: dashArgv })).data!;
  check("redraft passes an instruction starting with - as one --instruction= argument", dj.length === 1);
  const j0 = (await admin.from("jobs").select("id", { count: "exact", head: true }).eq("kind", "redraft")).count;
  check("redraft refuses an empty instruction", (await throws(() => redraftBatch(rb!.id, "   "))) && (await admin.from("jobs").select("id", { count: "exact", head: true }).eq("kind", "redraft")).count === j0);
  await admin.from("jobs").delete().eq("kind", "redraft").contains("payload", { argv: ["--batch", rb!.id] });
  await admin.from("leads").delete().like("place_id", "REHEARSAL_C_%");
  await admin.from("batches").delete().eq("id", rb!.id);
}

await admin.from("leads").delete().like("place_id", "TEST_v%");
await admin.from("batches").delete().eq("id", batch!.id);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
