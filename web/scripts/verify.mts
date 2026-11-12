// Dev verification: seeds test rows, mints a one-off operator session, and runs the app's real write actions under RLS.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify.mts   (reads the secret key from ../.env; never bundled into the app)
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { approveLeads, cancelJob, clearPause, enqueueJob, markBooked, rejectLeads, retryJob, saveSetting, setOutcome, unapproveLeads } from "../lib/actions";
import { SETTING_FIELDS } from "../lib/settings";
import { splitArgs } from "../lib/args";
import { readFileSync } from "node:fs";

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
const pyKeys = [...readFileSync("../gtm/settings_store.py", "utf8").split("DEFAULTS")[1].split("\nTTL")[0].matchAll(/"(\w+)":/g)].map((m) => m[1]).sort();
check("SETTING_FIELDS keys equal the Python DEFAULTS keys", JSON.stringify(SETTING_FIELDS.map((f) => f.key).sort()) === JSON.stringify(pyKeys) && pyKeys.length === 16);
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

await admin.from("leads").delete().like("place_id", "TEST_v%");
await admin.from("batches").delete().eq("id", batch!.id);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
