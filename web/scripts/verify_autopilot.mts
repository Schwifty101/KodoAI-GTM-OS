// Verifies the Autopilot card's writes and spent query against the real database under RLS.
// Saves the real autopilot settings first and restores them in finally. Never touches batches or leads.
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_autopilot.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { startAutopilot, pauseAutopilot, autopilotSpent } from "../lib/actions";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const KEYS = ["autopilot_on", "autopilot_limit_usd", "autopilot_started_at", "autopilot_state"];
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };
const read = async () => Object.fromEntries(((await admin.from("settings").select("key,value").in("key", KEYS)).data ?? []).map((r) => [r.key, r.value]));

const saved = (await admin.from("settings").select("*").in("key", KEYS)).data ?? [];
const original = Object.fromEntries(saved.map((r) => [r.key, r.value]));
let costId: string | undefined;
try {
  const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
  await supabase.auth.verifyOtp({ token_hash: g.data!.properties!.hashed_token, type: "magiclink" });

  const t0 = Date.now();
  await startAutopilot(2.5);
  let s = await read();
  check("start: on, limit 2.5, state running", s.autopilot_on === true && s.autopilot_limit_usd === 2.5 && s.autopilot_state === "running");
  const ts = Object.fromEntries(((await admin.from("settings").select("key,updated_at").in("key", KEYS)).data ?? []).map((r) => [r.key, r.updated_at]));
  check("start: started_at written before on", ts.autopilot_started_at < ts.autopilot_on);
  check("start: started_at is now", Math.abs(Date.parse(s.autopilot_started_at as string) - t0) < 60_000);

  const before = await read();
  let refused = false;
  try { await startAutopilot(-1); } catch { refused = true; }
  check("negative limit refused, nothing written", refused && JSON.stringify(before) === JSON.stringify(await read()));

  await startAutopilot(0);
  s = await read();
  check("0 stored as no limit", s.autopilot_limit_usd === 0 && s.autopilot_on === true);

  const since = new Date().toISOString();
  const c = await admin.from("cost_log").insert({ provider: "apify", units: 1, usd: 0.0123 }).select("id").single();
  costId = c.data?.id;
  const spent = await autopilotSpent(since);
  const truth = ((await admin.from("cost_log").select("usd").gte("created_at", since)).data ?? []).reduce((a, r) => a + Number(r.usd), 0);
  check("autopilotSpent sums cost_log.usd since start (>= 0.0123, matches admin sum)", spent >= 0.0123 && Math.abs(spent - truth) < 0.05);

  // Paging: 2,150 rows > the 1000-row cap, so 3 pages. Far-future since keeps real rows out.
  const rows = Array.from({ length: 2150 }, (_, i) => ({ provider: "TEST_ap", units: 1, usd: 0.001, created_at: new Date(Date.UTC(2099, 0, 1, 0, 0, 1 + i)).toISOString() }));
  for (let i = 0; i < rows.length; i += 500) {
    const r = await admin.from("cost_log").insert(rows.slice(i, i + 500));
    if (r.error) throw new Error(r.error.message);
  }
  const big = await autopilotSpent("2099-01-01T00:00:00Z");
  console.log("paged sum", big);
  check("autopilotSpent pages past 1000 rows (2150 x 0.001 = 2.15)", Math.abs(big - 2.15) < 1e-6);

  await pauseAutopilot();
  s = await read();
  check("pause: off, state paused by owner", s.autopilot_on === false && s.autopilot_state === "paused by owner");
} finally {
  await admin.from("cost_log").delete().eq("provider", "TEST_ap");
  if (costId) await admin.from("cost_log").delete().eq("id", costId);
  await admin.from("settings").delete().in("key", KEYS);
  if (saved.length) await admin.from("settings").insert(saved);
}
check("settings restored", JSON.stringify(await read()) === JSON.stringify(original));
console.log(fails.length ? `${fails.length} FAILED` : "all ok");
process.exit(fails.length ? 1 : 0);
