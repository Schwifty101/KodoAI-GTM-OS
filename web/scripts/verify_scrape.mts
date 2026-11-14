// Scrape page checks against the real database under the operator session. Only `walk_test` jobs and metro 'TEST' coverage rows are created.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_scrape.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { enqueueJobOnce } from "../lib/actions";
import { finishedMetros, loadCoverage, runTilesArgv, summarizeMetros, walkJobOpen } from "../lib/scrape";
import type { Coverage, Job } from "../lib/types";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };
const throws = (f: () => unknown) => { try { f(); return false; } catch { return true; } };

const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" });

const cnt = async (status?: string) => {
  let qq = admin.from("coverage").select("id", { count: "exact", head: true });
  if (status) qq = qq.eq("status", status);
  return (await qq).count!;
};
const all = await loadCoverage();
check("loadCoverage returns every row (more than 1000)", all.length === (await cnt()) && all.length > 1000);

const mk = (o: Partial<Coverage>): Coverage => ({ id: "x", seq: 0, metro_rank: 1, metro: "A", state: "AA", tile: "t", status: "pending", places_found: null, new_leads: null, saturated: false, queries_run: null, scrape_batch_id: null, error: null, started_at: null, scraped_at: null, ...o });
const s = summarizeMetros([
  mk({ metro_rank: 2, metro: "B", status: "done", places_found: 5, new_leads: 3, saturated: true, scraped_at: "2026-01-02" }),
  mk({ metro_rank: 1, status: "done", places_found: 10, scraped_at: "2026-01-05" }),
  mk({ metro_rank: 1, status: "done", places_found: null, scraped_at: "2026-01-03" }),
  mk({ metro_rank: 1, status: "failed" }),
]);
check("summarizeMetros counts, sums, max date, order", s[0].metro === "A" && s[0].total === 3 && s[0].done === 2 && s[0].failed === 1 && s[0].places === 10 && s[0].lastScraped === "2026-01-05" && s[1].saturated === 1 && s[1].done === s[1].total && s[1].newLeads === 3);
// a metro spanning two states: finished only when every state row is done; row keys (rank|metro|state) are unique
const ms = summarizeMetros([mk({ metro: "M", state: "S1", status: "done" }), mk({ metro: "M", state: "S2", status: "pending" }), mk({ metro_rank: 2, metro: "N", state: "S1", status: "done" })]);
check("finishedMetros counts a two-state metro only when all its states are done", finishedMetros(ms) === 1 && ms.length === 3);
const realKeys = summarizeMetros(all).map((m) => `${m.metro_rank}|${m.metro}|${m.state}`);
check("metro row keys (rank|metro|state) are unique across the real table", new Set(realKeys).size === realKeys.length);
const real = summarizeMetros(all);
check("metro totals equal the database", real.reduce((a, m) => a + m.total, 0) === all.length);
for (const st of ["pending", "running", "done", "failed"] as const)
  check(`metro ${st} sum equals count exact`, real.reduce((a, m) => a + m[st], 0) === (await cnt(st)));

check("runTilesArgv ok", JSON.stringify(runTilesArgv(3)) === JSON.stringify(["--tiles", "3"]));
check("runTilesArgv rejects 0, 21, 1.5, NaN", [0, 21, 1.5, NaN].every((n) => throws(() => runTilesArgv(n))));

const j = (kind: string, status: string) => ({ kind, status }) as Job;
check("walkJobOpen true for queued, running, paused_budget walk", ["queued", "running", "paused_budget"].every((st) => walkJobOpen([j("walk", st)])));
check("walkJobOpen false for done, failed, cancelled and other kinds", ["done", "failed", "cancelled"].every((st) => !walkJobOpen([j("walk", st)])) && !walkJobOpen([j("clean", "queued")]));

const sp = await supabase.from("spend_summary").select("*").eq("provider", "apify");
check("spend_summary apify readable with numeric today and month", !sp.error && (!sp.data?.length || (!isNaN(Number(sp.data[0].usd_today)) && !isNaN(Number(sp.data[0].usd_month)))));

// Run-button path, with a non-runnable kind so the live worker never takes it.
const argv = ["--tiles", "1", "TEST_scrape"];
const open = async () => (await admin.from("jobs").select("id,status").eq("kind", "walk_test").contains("payload", { argv })).data!;
await enqueueJobOnce("walk_test", argv);
const o = await open();
check("enqueueJobOnce inserts one queued job under RLS", o.length === 1 && o[0].status === "queued");
let dup = false; try { await enqueueJobOnce("walk_test", argv); } catch { dup = true; }
check("second identical click is refused", dup && (await open()).length === 1);
await admin.from("jobs").delete().eq("kind", "walk_test").contains("payload", { argv });

console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
