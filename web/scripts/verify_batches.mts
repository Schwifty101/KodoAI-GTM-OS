// Verifies the Batches page's queries and its one write against the real database under RLS. TEST rows only; kind enrich_test, never enrich.
// The seeded leads use statuses the autopilot ignores (drafted, sent, no_buyer); selected/approved counting runs on in-memory rows. Their batch_no (9998, 9999) still
// moves the autopilot's "current batch", so the script refuses to run while autopilot_on is true unless ALLOW_LIVE_AUTOPILOT=1.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_batches.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { enqueueJobOnce } from "../lib/actions";
import {
  BATCH_SIZE, batchBase, countByStatus, countCleaned, creditState, doneJobs, fillLabel, isSheetBatch, loadBatchJobs, loadBatchNos, loadOutreachBatches,
  loadRetryCandidates, outreachRows, retryArgv, retryOpen, stepOpen,
} from "../lib/batches";
import { sameArgv, stepState, type JobRow } from "../lib/runnow";
import type { Job } from "../lib/types";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };

const ap = await admin.from("settings").select("value").eq("key", "autopilot_on");
if (ap.error) throw new Error(ap.error.message);
if (ap.data[0]?.value === true && process.env.ALLOW_LIVE_AUTOPILOT !== "1") {
  console.error("autopilot_on is true: this script seeds TEST leads the live autopilot would react to (and moves its current batch). Pause autopilot first, or set ALLOW_LIVE_AUTOPILOT=1 to run anyway. Nothing was written.");
  process.exit(1);
}

const { data: batch } = await admin.from("batches").insert({ name: "TEST batches verify" }).select("id").single();
const { data: empty } = await admin.from("batches").insert({ name: "TEST batches empty" }).select("id").single();
const mk = (i: number, status: string, batch_no: number | null, extra: object = {}) => ({ place_id: `TEST_b${i}`, name: `Spa ${i}`, status, batch_id: batch!.id, batch_no, approved: false, ...extra });
const seed = await admin.from("leads").insert([
  mk(1, "drafted", 9998), mk(2, "drafted", 9998, { approved: true }), mk(3, "sent", 9998), mk(4, "drafted", 9999),
  mk(5, "no_buyer", null, { owner_name: "Jane Doe", owner_title: "Owner" }), mk(6, "no_buyer", null),
]);
if (seed.error) throw new Error(`seed leads: ${seed.error.message}`);
const l1 = (await admin.from("leads").select("id").eq("place_id", "TEST_b1").single()).data!.id;
await admin.from("cost_log").insert([
  { provider: "hunter", units: 2, usd: 0, lead_id: l1 }, { provider: "apify", units: 1, usd: 0.01, lead_id: l1 },
]);
const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

const nos = await loadBatchNos();
const r98 = nos.find((r) => r.batch_no === 9998), r99 = nos.find((r) => r.batch_no === 9999);
check("loadBatchNos: 9998 has 3 leads {drafted:2, sent:1}", r98?.leads === 3 && r98.byStatus.drafted === 2 &&r98.byStatus.sent === 1 && Object.keys(r98.byStatus).length === 2);
check("loadBatchNos: spend merged (hunter 2, apify 0.01)", r98?.hunter_credits === 2 && Math.abs(r98.apify_usd - 0.01) < 1e-9);
check("loadBatchNos: 9999 has 1 lead and zero spend (no view row)", r99?.leads === 1 && r99.hunter_credits === 0 && r99.gemini_usd === 0);
check("loadBatchNos: newest first", nos.map((r) => r.batch_no).every((n, i, a) => i === 0 || a[i - 1] > n) && nos[0].batch_no >= 9999);
check("fillLabel", !!r98 && fillLabel(r98) === `3 of ${BATCH_SIZE}`);
const total = (await admin.from("leads").select("id", { count: "exact", head: true }).not("batch_no", "is", null)).count;
check("sum(leads) equals count: exact", nos.reduce((a, r) => a + r.leads, 0) === total);

// Plan 8: outreach cards (batch_base counts as filled), pure helpers, intake step data.
check("fillLabel with a base", !!r98 && fillLabel(r98, 5) === `8 of ${BATCH_SIZE}`);
check("batchBase parses {\"3\": 32}, ignores junk", JSON.stringify(batchBase({ "3": 32, x: 1, "4": "no" })) === JSON.stringify({ 3: 32 }) && Object.keys(batchBase(null)).length === 0);
const out = await loadOutreachBatches({ 9998: 5, 9997: 7 });
const o98 = out.find((r) => r.batch_no === 9998), o99 = out.find((r) => r.batch_no === 9999), o97 = out.find((r) => r.batch_no === 9997);
check("loadOutreachBatches: 9998 = 3 numbered + 5 base, 2 drafted, 1 sent",
  o98?.leads === 8 && o98.base === 5 && o98.drafted === 2 && o98.sent === 1 && o98.selected === 0 && o98.approved === 0 && o98.replied === 0);
check("loadOutreachBatches: 9999 has 1 drafted, no base", o99?.leads === 1 && o99.base === 0 && o99.drafted === 1 && o99.selected === 0);
check("loadOutreachBatches: a base-only batch still gets a row", o97?.leads === 7 && o97.selected === 0);
// selected/approved counting on in-memory rows: a seeded selected+approved lead would be drafted (paid) by a live autopilot
const mem = outreachRows([
  { batch_no: 9998, status: "selected", approved: false }, { batch_no: 9998, status: "selected", approved: true }, { batch_no: 9998, status: "sent", approved: false },
  { batch_no: 9999, status: "selected", approved: false },
], { 9998: 5, 9997: 7 });
const m98 = mem.find((r) => r.batch_no === 9998), m99 = mem.find((r) => r.batch_no === 9999);
check("outreachRows: 9998 = 3 numbered + 5 base, 2 selected (1 approved), 1 sent", m98?.leads === 8 && m98.base === 5 && m98.selected === 2 && m98.approved === 1 && m98.sent === 1 && m98.drafted === 0 && m98.replied === 0);
check("outreachRows: 9999 has 1 selected (not approved), no base", m99?.leads === 1 && m99.base === 0 && m99.selected === 1 && m99.approved === 0);
check("outreachRows: a base-only batch still gets a row, newest first", mem.find((r) => r.batch_no === 9997)?.leads === 7 && mem.map((r) => r.batch_no).join() === "9999,9998,9997");
check("loadOutreachBatches: newest first", out.map((r) => r.batch_no).every((n, i, a) => i === 0 || a[i - 1] > n));
check("countByStatus and countCleaned on the TEST batch", (await countByStatus(batch!.id, "drafted")) === 3 &&(await countByStatus(batch!.id, "no_buyer")) === 2 && (await countCleaned(batch!.id)) === 0 && (await countCleaned(empty!.id)) === 0);
check("isSheetBatch", isSheetBatch("Sheet import 2026-11-20") && !isSheetBatch("Houston TX 2026-11-14"));
const jr = (kind: string, status: string, argv: string[]): JobRow => ({ id: `x${argv.length}${kind}${status}`, kind, status, payload: { argv }, result: null, error: null, created_at: new Date().toISOString(), finished_at: null });
check("doneJobs drops a sheet pass dry run, keeps its apply and plain passes",
  doneJobs([jr("verify-sheet", "done", ["--batch", "b"]), jr("verify-sheet", "done", ["--batch", "b", "--confirm"]), jr("clean", "done", ["--batch", "b"])]).length === 2);
check("a verify-sheet preview does not unlock enrich; its apply does",
  !stepState(["clean", "verify-sheet", "enrich"], "enrich", doneJobs([jr("verify-sheet", "done", ["--batch", "b"])]), "b").enabled
  && stepState(["clean", "verify-sheet", "enrich"], "enrich", doneJobs([jr("verify-sheet", "done", ["--batch", "b", "--confirm"])]), "b").enabled);
check("stepOpen: queued enrich of this run (any flags) is open, other run or done is not",
  stepOpen([jr("enrich", "queued", ["--batch", "b", "--retry-no-buyer"])], "enrich", "b") && !stepOpen([jr("enrich", "queued", ["--batch", "c"])], "enrich", "b") && !stepOpen([jr("enrich", "done", ["--batch", "b"])], "enrich", "b"));

const rc = await loadRetryCandidates();
const mine = rc.find((r) => r.batch_id === batch!.id);
check("loadRetryCandidates: named 1, unnamed 1", mine?.named === 1 && mine.unnamed === 1 && mine.name === "TEST batches verify");
check("loadRetryCandidates: batch without no_buyer absent", !rc.some((r) => r.batch_id === empty!.id));

check("retryArgv", JSON.stringify(retryArgv("abc")) === JSON.stringify(["--batch", "abc", "--retry-no-buyer", "--named-only"]));
const job = (kind: string, status: string, b: string) => ({ kind, status, payload: { argv: retryArgv(b) } }) as unknown as Job;
check("retryOpen true for queued, running, paused_budget", ["queued", "running", "paused_budget"].every((s) => retryOpen([job("enrich", s, "abc")], "abc")));
check("retryOpen false for other batch, done job, clean job", !retryOpen([job("enrich", "queued", "x")], "abc") && !retryOpen([job("enrich", "done", "abc")], "abc") && !retryOpen([job("clean", "queued", "abc")], "abc"));

const sp = (p: string, today: number, month: number) => ({ provider: p, units_today: today, units_month: month, usd_today: 0, usd_month: 0 });
const cs = (spend: ReturnType<typeof sp>[], h: number, p: number) => creditState(spend, { cap_hunter_credits_day: h, cap_prospeo_credits_day: p });
check("creditState: cap 0 blocked, today = cap blocked, below cap open, month passes through",
  cs([], 0, 5)[0].blocked && cs([sp("hunter", 5, 9)], 5, 5)[0].blocked && !cs([sp("hunter", 4, 9)], 5, 5)[0].blocked && cs([sp("hunter", 4, 9)], 5, 5)[0].month === 9 && !cs([], 5, 5)[1].blocked);

const argv = retryArgv(batch!.id);
const q = async () => (await admin.from("jobs").select("id").eq("kind", "enrich_test").contains("payload", { argv })).data!.length;
await enqueueJobOnce("enrich_test", argv);
check("enqueueJobOnce inserts one queued row", (await q()) === 1);
let refused = false;
try { await enqueueJobOnce("enrich_test", argv); } catch { refused = true; }
check("second identical enqueue is refused", refused && (await q()) === 1);

// loadBatchJobs: test twins of the step kinds are included, other kinds are not, at most 200.
await admin.from("jobs").insert({ kind: "draft_test", payload: { argv, test: true } }); // marked like enqueueJob does, so the live worker's claim skips it
const bj = await loadBatchJobs();
check("loadBatchJobs includes the enrich_test job with its argv", bj.some((j) => j.kind === "enrich_test" && sameArgv(j.payload?.argv ?? [], argv)));
check("loadBatchJobs excludes other kinds (draft_test) and returns at most 200, newest first",
  !bj.some((j) => j.kind === "draft_test") && bj.length <= 200 && bj.every((j, i) => i === 0 || bj[i - 1].created_at >= j.created_at));

await admin.from("jobs").delete().in("kind", ["enrich_test", "draft_test"]).contains("payload", { argv });
await admin.from("cost_log").delete().eq("lead_id", l1);
await admin.from("leads").delete().like("place_id", "TEST_b%");
await admin.from("batches").delete().in("id", [batch!.id, empty!.id]);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
