// Verifies Plan 6 (metrics) against the real database under RLS: migration 0017 (outcome_at, booked_at, cost_daily) and the loaders behind Home, Metrics, Replies and the per-lead panel.
// TEST rows only: place ids TEST_mv1..6 and the batch "TEST metrics verify"; batch_no stays null on every lead (a numbered TEST lead would move the live autopilot's current batch).
// Needs migration 0017 applied (it checks first and writes nothing if it is not). Refuses to run while autopilot_on is true unless ALLOW_LIVE_AUTOPILOT=1: the baselines below are
// exact counts, and a live autopilot that scrapes, drafts or spends between the baseline and the second read makes them flake.
// Everything seeded is deleted in `finally`, then re-selected to prove it. Never run it at the same time as pytest (the db tests wipe every TEST_ lead).
// Run: node --env-file=.env.local --env-file=../.env --import tsx scripts/verify_metrics.mts
import { createClient } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { markBooked, setOutcome } from "../lib/actions";
import { loadMetricsData } from "../lib/metricsData";
import { loadHome } from "../lib/homeData";
import { loadReplies } from "../lib/repliesData";
import { loadLeadActivity } from "../lib/leadActivity";
import { replyBucket } from "../lib/replies";

const admin = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.SUPABASE_SECRET_KEY!);
const fails: string[] = [];
const check = (name: string, cond: boolean) => { console.log(cond ? "ok  " : "FAIL", name); if (!cond) fails.push(name); };
const near = (a: unknown, b: number) => Math.abs(Number(a) - b) < 1e-9;
const fail = (what: string, e: { message: string } | null) => { if (e) throw new Error(`${what}: ${e.message}`); };

const ap = await admin.from("settings").select("value").eq("key", "autopilot_on");
if (ap.error) throw new Error(ap.error.message);
if (ap.data[0]?.value === true && process.env.ALLOW_LIVE_AUTOPILOT !== "1") {
  console.error("autopilot_on is true: this script seeds TEST rows next to a live autopilot and compares exact counts against a baseline. Pause autopilot first, or set ALLOW_LIVE_AUTOPILOT=1 to run anyway. Nothing was written.");
  process.exit(1);
}
for (const [table, col] of [["touches", "outcome_at"], ["leads", "booked_at"], ["cost_daily", "day"]]) {
  const p = await admin.from(table).select(col).limit(1);
  if (p.error) { console.error(`migration 0017 is not applied (${table}.${col}: ${p.error.message}). Nothing was written.`); process.exit(1); }
}

const BATCH = "TEST metrics verify";
const PLACE = [1, 2, 3, 4, 5, 6].map((i) => `TEST_mv${i}`);
const THREAD = "TEST_thread_mv";
const PAST = "2026-01-15", PAST_NEXT = "2026-01-16"; // a fixed past UTC day and the next one: 23:30Z and 00:30Z must land on two days

/** Deletes every TEST_mv lead (touches cascade), their cost rows and the test batch; returns the ids it found so the caller can re-select them. Safe to run on nothing. */
async function cleanup() {
  const lids = ((await admin.from("leads").select("id").like("place_id", "TEST_mv%")).data ?? []).map((r) => r.id as string);
  const bids = ((await admin.from("batches").select("id").eq("name", BATCH)).data ?? []).map((r) => r.id as string);
  if (lids.length) fail("cleanup cost_log by lead", (await admin.from("cost_log").delete().in("lead_id", lids)).error);
  if (bids.length) fail("cleanup cost_log by batch", (await admin.from("cost_log").delete().in("batch_id", bids)).error);
  fail("cleanup leads", (await admin.from("leads").delete().like("place_id", "TEST_mv%")).error);
  if (bids.length) fail("cleanup batch", (await admin.from("batches").delete().in("id", bids)).error);
  return { lids, bids };
}

await cleanup(); // a crashed earlier run must not skew the baseline or collide on the unique place ids

const g = await admin.auth.admin.generateLink({ type: "magiclink", email: "soban@kodoai.xyz" });
fail("generateLink", g.error);
fail("verifyOtp", (await supabase.auth.verifyOtp({ token_hash: g.data.properties!.hashed_token, type: "magiclink" })).error);

try {
  // Baselines, read before anything is seeded: includeTest returns the real rows too, so every count is compared against these.
  const now = new Date();
  const base = await loadMetricsData(true);
  const baseHome = await loadHome(now, true);

  // Seed (admin client, bypasses RLS). Every row of an insert carries the same keys, every column named: a missing key becomes null, not the column default.
  const nowIso = now.toISOString();
  const yNoon = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1, 12).toISOString(); // yesterday noon, local time
  const today = nowIso.slice(0, 10); // UTC day of the cost rows
  const b = await admin.from("batches").insert({ name: BATCH }).select("id").single();
  fail("seed batch", b.error);
  const bid: string = b.data!.id;
  type Lead = { vector?: string; signal_led?: boolean; owner_name?: string; owner_email?: string; email_verified?: boolean; created_at?: string };
  const mk = (i: number, status: string, o: Lead = {}) => ({
    place_id: `TEST_mv${i}`, name: `Metrics Spa ${i}`, status, batch_id: bid, batch_no: null, approved: false,
    vector: o.vector ?? null, signal_led: o.signal_led ?? false, owner_name: o.owner_name ?? null, owner_email: o.owner_email ?? null,
    email_verified: o.email_verified ?? null, created_at: o.created_at ?? nowIso,
  });
  const ls = await admin.from("leads").insert([
    // mv1: created yesterday noon, a verified owner, a vector and signal-led. mv5 is inserted as booked: the trigger stamps booked_at.
    mk(1, "sent", { created_at: yNoon, vector: "conversion_recovery", signal_led: true, owner_name: "Jane Verify", owner_email: "mv1@example.com", email_verified: true }),
    mk(2, "sent", { vector: "capacity" }), mk(3, "replied"), mk(4, "bounced"), mk(5, "booked"), mk(6, "drafted"),
  ]).select("id,place_id");
  fail("seed leads", ls.error);
  const id = Object.fromEntries(ls.data!.map((r) => [r.place_id as string, r.id as string]));
  const ids = new Set(Object.values(id));
  const tk = (n: number, status: string, sent_at: string | null, gmail_thread_id: string | null = null) =>
    ({ lead_id: id[`TEST_mv${n}`], touch_no: 1, status, sent_at, gmail_thread_id, outcome: null });
  fail("seed touches", (await admin.from("touches").insert([
    tk(1, "sent", yNoon), tk(2, "sent", nowIso), tk(3, "sent", nowIso, THREAD), tk(4, "sent", nowIso), tk(5, "sent", yNoon), tk(6, "drafted", null),
  ])).error);
  const cost = (provider: string, units: number, usd: number | null, batch_id: string | null, lead_id: string | null, created_at: string) =>
    ({ provider, units, usd, batch_id, lead_id, note: BATCH, created_at });
  fail("seed cost_log", (await admin.from("cost_log").insert([
    cost("apify", 1, 0.05, bid, null, nowIso),                       // by batch
    cost("hunter", 2, null, null, id.TEST_mv1, nowIso),              // lead only, credits with no dollars
    cost("apify", 1, 0.02, null, id.TEST_mv1, nowIso),               // lead only: must join the batch row's group
    cost("apify", 1, 0.10, bid, null, `${PAST}T23:30:00Z`),          // the UTC day split
    cost("apify", 1, 0.20, bid, null, `${PAST_NEXT}T00:30:00Z`),
  ])).error);

  // Reads straight after seeding and before any write, so the baselines still hold.
  const cd = await supabase.from("cost_daily").select("day,provider,run_id,units,usd").eq("run_id", bid).order("day").order("provider");
  fail("cost_daily", cd.error);
  const days = cd.data!;
  const dflt = await loadMetricsData();
  const all = await loadMetricsData(true);
  const home = await loadHome(now, true);

  check("cost_daily groups the seeded rows by UTC day, provider and run",
    days.map((r) => `${r.day} ${r.provider}`).join("|") === `${PAST} apify|${PAST_NEXT} apify|${today} apify|${today} hunter`
    && near(days[0].usd, 0.10) && near(days[0].units, 1) && near(days[1].usd, 0.20) && near(days[1].units, 1));
  const aToday = days.find((r) => r.day === today && r.provider === "apify"), hToday = days.find((r) => r.day === today && r.provider === "hunter");
  check("cost_daily attributes a lead-only row to the lead's run",
    !!hToday && near(hToday.units, 2) && near(hToday.usd, 0) // null usd reads as 0
    && !!aToday && near(aToday.units, 2) && near(aToday.usd, 0.07)); // 0.05 by batch + 0.02 by lead, one group

  check("loadMetricsData drops TEST rows by default",
    !dflt.leads.some((l) => PLACE.includes(l.place_id)) && !dflt.touches.some((t) => ids.has(t.lead_id)) && !dflt.costs.some((c) => c.run_id === bid));
  check("loadMetricsData(true) returns the seeded leads, sent touches and costs",
    all.leads.length === base.leads.length + 6 && PLACE.every((p) => all.leads.some((l) => l.place_id === p))
    && all.touches.length === base.touches.length + 5 && all.touches.filter((t) => ids.has(t.lead_id)).length === 5 // the drafted touch is not a sent touch
    && all.costs.filter((c) => c.run_id === bid).length === 4 && all.runs.some((r) => r.id === bid)
    && all.leads.some((l) => l.place_id === "TEST_mv1" && l.vector === "conversion_recovery" && l.signal_led && l.owner_email === "mv1@example.com" && l.email_verified === true)
    && all.leads.some((l) => l.place_id === "TEST_mv5" && l.status === "booked" && l.booked_at !== null)); // trigger on insert

  check("loadHome counts the seeded yesterday lead as scraped and as a verified owner",
    home.yesterday.scraped === baseHome.yesterday.scraped + 1 && home.yesterday.owners === baseHome.yesterday.owners + 1);
  check("loadHome counts the seeded yesterday sends as Touch 1", // extra: proves the sent_at range
    home.yesterday.touch1 === baseHome.yesterday.touch1 + 2 && home.yesterday.followups === baseHome.yesterday.followups);
  check("loadHome counts the seeded drafted touch", home.counts.draftsWaiting === baseHome.counts.draftsWaiting + 1);

  // Writes through the web path (operator session under RLS).
  await setOutcome(id.TEST_mv3, "positive");
  const t3 = (await admin.from("touches").select("outcome,outcome_at").eq("lead_id", id.TEST_mv3).eq("touch_no", 1).single()).data;
  check("setOutcome stamps outcome_at through the web write path", t3?.outcome === "positive" && t3.outcome_at !== null);

  // Replies, between the two writes: mv3 is replied with a positive outcome here; markBooked then moves it to booked.
  const rp = await loadReplies(true);
  const row = (p: string) => rp.rows.find((r) => r.lead_id === id[p]);
  const r3 = row("TEST_mv3"), r4 = row("TEST_mv4"), r5 = row("TEST_mv5");
  check("loadReplies buckets the seeded replied, bounced and booked leads and carries outcome_at and the thread id",
    !!r3 && replyBucket(r3.status, r3.outcome) === "positive" && r3.outcome_at !== null && r3.thread_id === THREAD && r3.touch_no === 1
    && !!r4 && replyBucket(r4.status, r4.outcome) === "bounced"
    && !!r5 && replyBucket(r5.status, r5.outcome) === "booked"
    && !row("TEST_mv1") && !row("TEST_mv2") && !row("TEST_mv6")); // sent and drafted leads with no outcome are not replies

  await markBooked(id.TEST_mv3);
  const l3 = (await admin.from("leads").select("status,booked_at").eq("id", id.TEST_mv3).single()).data;
  check("markBooked stamps booked_at", l3?.status === "booked" && l3.booked_at !== null);

  const a1 = await loadLeadActivity(id.TEST_mv1), a3 = await loadLeadActivity(id.TEST_mv3);
  check("loadLeadActivity returns the lead's spend by provider and its touches",
    Object.keys(a1.spend).sort().join() === "apify,hunter" // the batch-level 0.05 row is not this lead's
    && near(a1.spend.apify.units, 1) && near(a1.spend.apify.usd, 0.02) && near(a1.spend.hunter.units, 2) && near(a1.spend.hunter.usd, 0)
    && a1.touches.length === 1 && a1.touches[0].touch_no === 1 && a1.touches[0].status === "sent" && a1.touches[0].sent_at !== null && a1.touches[0].outcome === null
    && a3.touches.length === 1 && a3.touches[0].outcome === "positive" && a3.touches[0].outcome_at !== null && Object.keys(a3.spend).length === 0);
} finally {
  const { lids, bids } = await cleanup();
  const left = [
    admin.from("leads").select("id", { count: "exact", head: true }).like("place_id", "TEST_mv%"),
    admin.from("batches").select("id", { count: "exact", head: true }).eq("name", BATCH),
    ...(lids.length ? [
      admin.from("touches").select("id", { count: "exact", head: true }).in("lead_id", lids),
      admin.from("cost_log").select("id", { count: "exact", head: true }).in("lead_id", lids),
    ] : []),
    ...(bids.length ? [admin.from("cost_log").select("id", { count: "exact", head: true }).in("batch_id", bids)] : []),
  ];
  const counts = await Promise.all(left.map(async (q) => (await q).count));
  check("cleanup: every seeded lead, touch, cost row and the batch is gone (re-selected)", counts.every((c) => c === 0));
}

console.log(fails.length ? `verify_metrics: ${fails.length} FAILED` : "verify_metrics: all checks passed");
process.exit(fails.length ? 1 : 0);
