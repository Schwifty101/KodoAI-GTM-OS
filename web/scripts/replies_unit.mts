// Pure-logic check for buildReplyRows in web/lib/repliesData.ts. No database, no network (the supabase client is built with a dummy URL and never called).
// Run: cd web && npx tsx scripts/replies_unit.mts
process.env.NEXT_PUBLIC_SUPABASE_URL = "http://localhost";
process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "unit";
const { buildReplyRows } = await import("../lib/repliesData");

let failed = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`ok ${name}`);
  else { failed++; console.log(`FAIL ${name}`); }
}

const lead = (id: string, o: Record<string, unknown> = {}) =>
  ({ id, name: id, owner_email: `${id}@x.com`, status: "replied", batch_no: 4, vector: "capacity", signal_led: false, place_id: `P_${id}`, ...o });
const touch = (id: string, touch_no: number, o: Record<string, unknown> = {}) =>
  ({ id, touch_no, status: "sent", outcome: null, outcome_at: null, gmail_thread_id: `th${id}`, ...o });

const leads = [
  lead("a", { signal_led: true, touches: [touch("a1", 1), touch("a2", 2, { outcome: "positive", outcome_at: "2026-11-20T10:00:00Z" }), touch("a3", 3, { status: "drafted" })] }),
  lead("b", { status: "booked", vector: null, touches: [touch("b1", 1, { outcome: "positive" }), touch("b2", 2)] }),
  lead("TEST", { place_id: "TEST_1", touches: [touch("t1", 1)] }),
  lead("REH", { place_id: "REHEARSAL_1", touches: [touch("r1", 1)] }),
  lead("none", { touches: [] }),
];
const outcomeTouches = [
  { ...touch("a2", 2, { outcome: "positive", outcome_at: "2026-11-20T10:00:00Z" }), leads: lead("a") }, // already in leads: no duplicate touch
  { ...touch("c1", 1, { outcome: "other", outcome_at: "2026-11-25T08:00:00Z" }), leads: lead("c", { status: "sent" }) }, // lead not in an answered status
  { ...touch("d1", 1, { outcome: "negative", outcome_at: "2026-11-25T08:00:00Z" }), leads: lead("d", { status: "sent" }) },
  { ...touch("x1", 1, { outcome: "negative" }), leads: null },
];
const rows = buildReplyRows(leads as never, outcomeTouches as never, false);
const by = (id: string) => rows.find((r) => r.lead_id === id);

check("one row per lead, test and rehearsal leads dropped, lead with no touches skipped", rows.map((r) => r.lead_id).sort().join() === "a,b,c,d");
check("a: last sent touch with an outcome (touch 2, not the drafted touch 3)", by("a")?.touch_no === 2 && by("a")?.outcome === "positive" && by("a")?.thread_id === "tha2");
check("a: signal-led lane; b: relevance-led lane with null vector kept", by("a")?.lane === "signal-led" && by("b")?.lane === "relevance-led" && by("b")?.vector === null);
check("b: outcome row beats the later sent touch without one; outcome_at stays null", by("b")?.touch_no === 1 && by("b")?.outcome === "positive" && by("b")?.outcome_at === null);
check("c, d come from the outcome read", by("c")?.outcome === "other" && by("d")?.outcome === "negative" && by("c")?.status === "sent");
check("sorted newest outcome_at first, nulls last, then name", rows.map((r) => r.lead_id).join() === "c,d,a,b");
check("includeTest keeps TEST_ and REHEARSAL_ leads", buildReplyRows(leads as never, outcomeTouches as never, true).length === 6);
check("no sent touch falls back to the last touch", buildReplyRows([lead("e", { touches: [touch("e1", 1, { status: "drafted" })] })] as never, [], false)[0]?.touch_no === 1);
check("empty input gives no rows", buildReplyRows([], [], false).length === 0);

if (failed) process.exit(1);
