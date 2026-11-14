// Verifies the Batches page's queries and its one write against the real database under RLS. TEST rows only; kind enrich_test, never enrich.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_batches.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { enqueueJobOnce } from "../lib/actions";
import { BATCH_SIZE, creditState, fillLabel, loadBatchNos, loadRetryCandidates, retryArgv, retryOpen } from "../lib/batches";
import type { Job } from "../lib/types";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };

const { data: batch } = await admin.from("batches").insert({ name: "TEST batches verify" }).select("id").single();
const { data: empty } = await admin.from("batches").insert({ name: "TEST batches empty" }).select("id").single();
const mk = (i: number, status: string, batch_no: number | null, extra: object = {}) => ({ place_id: `TEST_b${i}`, name: `Spa ${i}`, status, batch_id: batch!.id, batch_no, ...extra });
await admin.from("leads").insert([
  mk(1, "selected", 9998), mk(2, "selected", 9998), mk(3, "sent", 9998), mk(4, "selected", 9999),
  mk(5, "no_buyer", null, { owner_name: "Jane Doe", owner_title: "Owner" }), mk(6, "no_buyer", null),
]);
const l1 = (await admin.from("leads").select("id").eq("place_id", "TEST_b1").single()).data!.id;
await admin.from("cost_log").insert([
  { provider: "hunter", units: 2, usd: 0, lead_id: l1 }, { provider: "apify", units: 1, usd: 0.01, lead_id: l1 },
]);
const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

const nos = await loadBatchNos();
const r98 = nos.find((r) => r.batch_no === 9998), r99 = nos.find((r) => r.batch_no === 9999);
check("loadBatchNos: 9998 has 3 leads {selected:2, sent:1}", r98?.leads === 3 && r98.byStatus.selected === 2 && r98.byStatus.sent === 1 && Object.keys(r98.byStatus).length === 2);
check("loadBatchNos: spend merged (hunter 2, apify 0.01)", r98?.hunter_credits === 2 && Math.abs(r98.apify_usd - 0.01) < 1e-9);
check("loadBatchNos: 9999 has 1 lead and zero spend (no view row)", r99?.leads === 1 && r99.hunter_credits === 0 && r99.gemini_usd === 0);
check("loadBatchNos: newest first", nos.map((r) => r.batch_no).every((n, i, a) => i === 0 || a[i - 1] > n) && nos[0].batch_no >= 9999);
check("fillLabel", !!r98 && fillLabel(r98) === `3 of ${BATCH_SIZE}`);
const total = (await admin.from("leads").select("id", { count: "exact", head: true }).not("batch_no", "is", null)).count;
check("sum(leads) equals count: exact", nos.reduce((a, r) => a + r.leads, 0) === total);

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

await admin.from("jobs").delete().eq("kind", "enrich_test").contains("payload", { argv });
await admin.from("cost_log").delete().eq("lead_id", l1);
await admin.from("leads").delete().like("place_id", "TEST_b%");
await admin.from("batches").delete().in("id", [batch!.id, empty!.id]);
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
