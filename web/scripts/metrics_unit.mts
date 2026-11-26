// Pure-logic checks for web/lib/metrics.ts. No database, no network.
// Run: cd web && npx tsx scripts/metrics_unit.mts (also under TZ=Asia/Karachi and TZ=America/Los_Angeles)
import {
  addSpend, allocateSpend, batchRows, byAngle, cohort, dropTestRuns, historyRows, isOwner, isPositive, isReplied, isTestLead, isTestRun,
  perUnit, periodRange, periodStart, previousRange, pricedUsd, rate, spendFrom, undatedCounts, whereLeadsDie,
  type CostDay, type LeadRow, type Spend, type TouchRow,
} from "../lib/metrics";

let failed = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`ok ${name}`);
  else { failed++; console.log(`FAIL ${name}`); }
}

let n = 0;
const lead = (o: Partial<LeadRow> = {}): LeadRow => ({
  id: `l${++n}`, place_id: `P${n}`, batch_id: null, batch_no: null, status: "sent", vector: null, signal_led: false,
  owner_name: null, owner_email: null, email_verified: null, reject_reason: null, created_at: "2026-11-01T12:00:00Z", booked_at: null, ...o,
});
const touch = (lead_id: string, o: Partial<TouchRow> = {}): TouchRow => ({
  lead_id, touch_no: 1, status: "sent", sent_at: "2026-11-02T12:00:00Z", outcome: null, outcome_at: null, ...o,
});
const owner = { owner_name: "Ann", owner_email: "ann@x.com", email_verified: true };
const near = (a: number, b: number) => Math.abs(a - b) < 1e-9;
const same = (a: Spend, b: Spend) => {
  const ks = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...ks].every((k) => near(a[k]?.units ?? 0, b[k]?.units ?? 0) && near(a[k]?.usd ?? 0, b[k]?.usd ?? 0));
};

// Filters
check("isTestLead: TEST_ and REHEARSAL_ are test, others are not", isTestLead("TEST_a") && isTestLead("REHEARSAL_a") && !isTestLead("ChIJabc") && !isTestLead("test_a"));
check("isTestRun: names starting TEST or REHEARSAL", isTestRun("TEST metrics") && isTestRun("REHEARSAL x") && !isTestRun("Austin TX") && !isTestRun("My TEST"));
check("isOwner: owner_email set and email_verified true", isOwner(owner) && !isOwner({ owner_email: "a@x.com", email_verified: false }) && !isOwner({ owner_email: null, email_verified: true }) && !isOwner({ owner_email: "a@x.com", email_verified: null }));
check("isReplied: statuses replied, unsubscribed, booked", isReplied("replied", []) && isReplied("unsubscribed", []) && isReplied("booked", []) && !isReplied("sent", []));
check("isReplied: outcomes positive, negative, other, opt_out; bounce is not", ["positive", "negative", "other", "opt_out"].every((o) => isReplied("sent", [null, o])) && !isReplied("bounced", ["bounce", null, undefined]));
check("isPositive: booked status or a positive outcome", isPositive("booked", []) && isPositive("sent", ["negative", "positive"]) && !isPositive("replied", ["negative", "other"]));

// Time
check("periodStart: week starts Monday", periodStart("2026-11-29T23:00:00Z", "week") === "2026-11-23" && periodStart("2026-11-23T00:00:00Z", "week") === "2026-11-23" && periodStart("2026-11-22T12:00:00Z", "week") === "2026-11-16");
check("periodStart: 2026-12-31 is Q4 and 2027-01-01 is Q1", periodStart("2026-12-31T23:59:59Z", "quarter") === "2026-10-01" && periodStart("2027-01-01T00:00:00Z", "quarter") === "2027-01-01");
check("periodStart ignores the process time zone", periodStart("2026-11-01T23:30:00Z", "day") === "2026-11-01" && periodStart("2026-11-01T00:30:00Z", "day") === "2026-11-01" && periodStart("2026-11-30T23:30:00Z", "month") === "2026-11-01" && periodStart("2026-11-01", "day") === "2026-11-01");
check("periodStart: month and date-only input", periodStart("2026-02-15", "month") === "2026-02-01" && periodStart("2026-05-20", "quarter") === "2026-04-01");
check("periodRange lists empty buckets too", JSON.stringify(periodRange("2026-11-01", "2026-11-04", "day")) === JSON.stringify(["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"])
  && JSON.stringify(periodRange("2026-11-25", "2026-12-08", "week")) === JSON.stringify(["2026-11-23", "2026-11-30", "2026-12-07"])
  && JSON.stringify(periodRange("2026-11-15", "2027-02-01", "quarter")) === JSON.stringify(["2026-10-01", "2027-01-01"])
  && JSON.stringify(periodRange("2026-12-15", "2027-01-15", "month")) === JSON.stringify(["2026-12-01", "2027-01-01"]));
const pr = previousRange("2026-11-10", "2026-11-16");
check("previousRange: same length, ends the day before from", pr.from === "2026-11-03" && pr.to === "2026-11-09" && JSON.stringify(previousRange("2026-03-01", "2026-03-01")) === JSON.stringify({ from: "2026-02-28", to: "2026-02-28" }));

// Money
check("rate: n of 0 is null, never NaN", rate(0, 0) === null && rate(3, 0) === null && rate(1, 4) === 0.25);
const sp = spendFrom([{ provider: "apify", units: 1, usd: 0.5 }, { provider: "apify", units: 2, usd: null }, { provider: "hunter", units: 3, usd: null }]);
check("spendFrom sums units and usd per provider, null usd is 0", same(sp, { apify: { units: 3, usd: 0.5 }, hunter: { units: 3, usd: 0 } }));
check("addSpend adds per provider and keeps both sides", same(addSpend({ a: { units: 1, usd: 1 } }, { a: { units: 2, usd: 0 }, b: { units: 1, usd: 2 } }), { a: { units: 3, usd: 1 }, b: { units: 1, usd: 2 } }));
const credits: Spend = { apify: { units: 10, usd: 2 }, hunter: { units: 4, usd: 0 }, hunter_import: { units: 2, usd: 0 }, prospeo: { units: 5, usd: 0 }, serper: { units: 100, usd: 0 }, serper_maps: { units: 100, usd: 0 }, groq: { units: 9999, usd: 0 } };
check("pricedUsd: unpriced credits add nothing, a price adds units times price, hunter_import uses the hunter price",
  near(pricedUsd(credits, { hunter: 0, prospeo: 0, serper: 0 }), 2) && near(pricedUsd(credits, { hunter: 0.5, prospeo: 0, serper: 0 }), 5) && near(pricedUsd(credits, { hunter: 0, prospeo: 0.1, serper: 0.001 }), 2.7));
check("pricedUsd: groq never becomes money", near(pricedUsd({ groq: { units: 1e6, usd: 0 } }, { hunter: 1, prospeo: 1, serper: 1 }), 0));
const pu = perUnit({ apify: { units: 4, usd: 2 } }, 2);
check("perUnit: null when n is 0", perUnit({ apify: { units: 4, usd: 2 } }, 0) === null && !!pu && same(pu, { apify: { units: 2, usd: 1 } }));

// Cohorts
check("cohort: nothing sent gives zeros", JSON.stringify(cohort([], [])) === JSON.stringify({ sent: 0, bounced: 0, delivered: 0, replied: 0, positive: 0, booked: 0 })
  && cohort([lead({ status: "drafted" })], []).sent === 0);
{
  const a = lead(), b = lead({ status: "drafted" }), c = lead({ status: "sent" });
  const ts = [touch(a.id), touch(b.id, { status: "approved", sent_at: null }), touch(c.id, { touch_no: 2 })];
  check("cohort counts only leads whose Touch 1 is sent", cohort([a, b, c], ts).sent === 1);
}
{
  const ls = [lead({ status: "replied" }), lead({ status: "unsubscribed" }), lead({ status: "booked" }), lead(), lead(), lead(), lead(), lead({ status: "bounced" }), lead()];
  const outs = [null, null, null, "positive", "negative", "other", "opt_out", "bounce", null];
  const ts = ls.map((l, i) => touch(l.id, { outcome: outs[i] }));
  const c = cohort(ls, ts);
  check("cohort: replied is status replied, unsubscribed, booked or outcome positive, negative, other, opt_out; a bounce outcome is not a reply", c.replied === 7 && c.positive === 2 && c.booked === 1);
  check("cohort: delivered is sent minus bounced", c.sent === 9 && c.bounced === 1 && c.delivered === 8);
}
{
  const t1 = lead({ place_id: "TEST_x", status: "replied" }), t2 = lead({ place_id: "REHEARSAL_y", status: "booked" }), r = lead();
  const c = cohort([t1, t2, r], [touch(t1.id), touch(t2.id), touch(r.id)]);
  check("cohort excludes TEST_ and REHEARSAL_ leads", c.sent === 1 && c.replied === 0 && c.booked === 0);
}
{
  const runs = [{ id: "rT", name: "TEST run", created_at: "" }, { id: "rR", name: "REHEARSAL run", created_at: "" }, { id: "rA", name: "Austin", created_at: "" }];
  const cd = (run_id: string | null): CostDay => ({ day: "2026-11-01", provider: "apify", run_id, units: 1, usd: 1 });
  const kept = dropTestRuns([cd("rT"), cd("rR"), cd("rA"), cd(null), cd("unknown")], runs);
  check("dropTestRuns drops TEST and REHEARSAL runs and keeps null-run rows", kept.length === 3 && kept.some((c) => c.run_id === null) && kept.some((c) => c.run_id === "rA") && !kept.some((c) => c.run_id === "rT" || c.run_id === "rR"));
}

// Allocation
const cday = (run_id: string | null, provider: string, units: number, usd: number): CostDay => ({ day: "2026-11-01", provider, run_id, units, usd });
{
  const o1 = lead({ batch_id: "R1", batch_no: 3, ...owner }), o2 = lead({ batch_id: "R1", batch_no: 4, ...owner }), f = lead({ batch_id: "R1", status: "no_buyer" });
  const al = allocateSpend([cday("R1", "apify", 2, 4), cday("R1", "hunter", 6, 0)], [o1, o2, f]);
  check("allocateSpend: a run's spend splits equally over its verified owners", same(al.byBatchNo.get(3)!, { apify: { units: 1, usd: 2 }, hunter: { units: 3, usd: 0 } }) && same(al.byBatchNo.get(4)!, { apify: { units: 1, usd: 2 }, hunter: { units: 3, usd: 0 } }));
}
{
  const t = lead({ place_id: "TEST_o", batch_id: "R2", batch_no: 3, ...owner }), u = lead({ batch_id: "R2", owner_email: "a@x.com", email_verified: false });
  const al = allocateSpend([cday("R2", "apify", 1, 1)], [t, u]);
  check("allocateSpend: a run with spend and no verified owner lands in noOwners", same(al.noOwners, { apify: { units: 1, usd: 1 } }) && al.byBatchNo.size === 0);
}
check("allocateSpend: a null-run row lands in unattributed", same(allocateSpend([cday(null, "gemini", 0, 0.3)], []).unattributed, { gemini: { units: 0, usd: 0.3 } }));
{
  const o = lead({ batch_id: "R3", ...owner });
  const al = allocateSpend([cday("R3", "apify", 3, 3)], [o]);
  check("allocateSpend: owners not yet numbered land in notNumbered", same(al.notNumbered, { apify: { units: 3, usd: 3 } }) && al.byBatchNo.size === 0);
}
{
  const ls = [lead({ batch_id: "A", batch_no: 3, ...owner }), lead({ batch_id: "A", batch_no: 3, ...owner }), lead({ batch_id: "A", ...owner }), lead({ batch_id: "B", batch_no: 4, ...owner })];
  const cs = [cday("A", "apify", 7, 1.1), cday("A", "hunter", 5, 0), cday("B", "apify", 1, 0.37), cday("C", "serper", 9, 0), cday(null, "gemini", 0, 0.21)];
  const al = allocateSpend(cs, ls);
  const total = spendFrom(cs);
  const sum = [...al.byBatchNo.values(), al.notNumbered, al.noOwners, al.unattributed].reduce(addSpend, {});
  check("allocateSpend conserves total spend over its four buckets", same(sum, total));
}

// Batches
{
  const s = lead({ batch_no: 3, status: "replied", ...owner }), d = lead({ batch_no: 3, status: "drafted" }), t = lead({ batch_no: 3, place_id: "TEST_b" });
  const ts = [touch(s.id), touch(t.id)];
  const al = allocateSpend([], [s, d, t]);
  const rows = batchRows([s, d, t], ts, al, { 3: 32, 1: 50 });
  const r3 = rows.find((r) => r.batch_no === 3)!;
  check("batchRows: base counts toward fill and not toward rates", r3.fill === 34 && r3.base === 32 && r3.owners === 1 && r3.sent === 1 && r3.replied === 1 && r3.delivered === 1);
  const r1 = rows.find((r) => r.batch_no === 1);
  check("batchRows: a base-only batch still gets a row", !!r1 && r1.fill === 50 && r1.sent === 0 && JSON.stringify(r1.spend) === "{}");
  check("batchRows: newest first", JSON.stringify(rows.map((r) => r.batch_no)) === "[3,1]");
  const r4 = batchRows([lead({ batch_no: 4, status: "drafted" })], [], al, {})[0];
  check("batchRows: a batch with no sends has null rates", r4.batch_no === 4 && rate(r4.replied, r4.delivered) === null && rate(r4.bounced, r4.sent) === null);
  const al2 = allocateSpend([cday("R9", "apify", 2, 2)], [lead({ batch_id: "R9", batch_no: 5, ...owner })]);
  check("batchRows: spend comes from byBatchNo", same(batchRows([], [], al2, {})[0]?.spend ?? {}, { apify: { units: 2, usd: 2 } }));
}

// Angles
{
  const a = lead({ batch_no: 3, vector: "laser", signal_led: true }), b = lead({ batch_no: 3, vector: "laser", signal_led: false, status: "drafted" }),
    c = lead({ batch_no: 4, vector: null, signal_led: false }), d = lead({ batch_no: null, vector: "laser", signal_led: true }), e = lead({ batch_no: 3, place_id: "TEST_e", vector: "laser", signal_led: true });
  const ts = [touch(a.id), touch(c.id), touch(d.id), touch(e.id)];
  const rows = byAngle([a, b, c, d, e], ts);
  const key = rows.map((r) => `${r.vector}/${r.lane}/${r.leads}/${r.sent}`).join(",");
  check("byAngle: groups by vector and lane", key === "(none)/relevance-led/1/1,laser/relevance-led/1/0,laser/signal-led/1/1");
  check("byAngle: signal_led false is relevance-led", rows.filter((r) => r.lane === "relevance-led").length === 2);
  check("byAngle: a batch filter keeps only that batch", byAngle([a, b, c, d, e], ts, 4).map((r) => r.vector).join() === "(none)");
}

// Where leads die
{
  const ls = [lead({ status: "rejected", reject_reason: "day_spa" }), lead({ status: "rejected", reject_reason: "day_spa" }), lead({ status: "rejected", reject_reason: null }),
    lead({ status: "no_buyer", owner_name: "Bo" }), lead({ status: "no_buyer", owner_name: "  " }), lead({ status: "no_buyer" }), lead({ status: "no_buyer", place_id: "TEST_z" }), lead({ status: "sent" })];
  const w = whereLeadsDie(ls);
  check("whereLeadsDie: sorted descending and splits no_buyer named from no owner found", JSON.stringify(w) === JSON.stringify([
    { reason: "day_spa", n: 2 }, { reason: "no_buyer: no owner found", n: 2 }, { reason: "no_buyer: owner named", n: 1 }, { reason: "rejected, no reason", n: 1 }]));
}

// History
{
  const a = lead({ created_at: "2026-11-02T23:30:00Z", ...owner, status: "booked", booked_at: "2026-11-04T00:30:00Z" });
  const b = lead({ created_at: "2026-11-03T00:30:00Z" });
  const old = lead({ created_at: "2026-10-01T00:00:00Z" });
  const tl = lead({ place_id: "TEST_h", created_at: "2026-11-02T10:00:00Z" });
  const ts = [
    touch(a.id, { sent_at: "2026-11-03T23:59:00Z", outcome: "positive", outcome_at: "2026-11-04T01:00:00Z" }),
    touch(a.id, { touch_no: 2, sent_at: "2026-11-04T10:00:00Z" }),
    touch(b.id, { sent_at: "2026-11-03T05:00:00Z", outcome: "bounce", outcome_at: "2026-11-03T06:00:00Z" }),
    touch(b.id, { touch_no: 2, status: "approved", sent_at: null }),
    touch(tl.id, { sent_at: "2026-11-03T05:00:00Z", outcome: "negative", outcome_at: "2026-11-03T06:00:00Z" }),
  ];
  const costs = [cday(null, "apify", 1, 1), { ...cday(null, "apify", 2, 2), day: "2026-11-03" }, { ...cday(null, "apify", 5, 5), day: "2026-12-01" }];
  const h = historyRows({ leads: [a, b, old, tl], touches: ts, costs, grain: "day", from: "2026-11-02", to: "2026-11-04" });
  const by = Object.fromEntries(h.map((r) => [r.start, r]));
  check("historyRows: events land in their UTC bucket (sent_at, outcome_at, booked_at, created_at)", h.length === 3
    && by["2026-11-02"].scraped === 1 && by["2026-11-02"].owners === 1 && by["2026-11-03"].scraped === 1 && by["2026-11-03"].owners === 0
    && by["2026-11-03"].touch1 === 2 && by["2026-11-04"].followups === 1 && by["2026-11-03"].followups === 0
    && by["2026-11-03"].bounces === 1 && by["2026-11-03"].replies === 0 && by["2026-11-04"].replies === 1 && by["2026-11-04"].booked === 1
    && same(by["2026-11-03"].spend, { apify: { units: 2, usd: 2 } }) && JSON.stringify(by["2026-11-02"].spend) === "{}");
  const wk = historyRows({ leads: [a, b, old, tl], touches: ts, costs, grain: "week", from: "2026-11-02", to: "2026-11-04" });
  check("historyRows: a week bucket sums its days and ignores events outside the range", wk.length === 1 && wk[0].start === "2026-11-02" && wk[0].scraped === 2 && wk[0].touch1 === 2 && same(wk[0].spend, { apify: { units: 2, usd: 2 } }));
}
{
  const a = lead({ status: "booked", booked_at: null }), b = lead({ status: "replied" }), t = lead({ place_id: "TEST_u", status: "booked" });
  const ts = [touch(a.id, { outcome: "positive", outcome_at: null }), touch(b.id, { outcome: "bounce", outcome_at: null }), touch(b.id, { touch_no: 2, outcome: "negative", outcome_at: null }), touch(t.id, { outcome: "positive" })];
  const h = historyRows({ leads: [a, b, t], touches: ts, costs: [], grain: "month", from: "1970-01-01", to: "2026-11-30" });
  const total = h.reduce((s, r) => s + r.replies + r.bounces + r.booked, 0);
  const u = undatedCounts(ts, [a, b, t]);
  check("historyRows: an outcome without outcome_at is counted in undatedCounts, not bucketed", total === 0 && JSON.stringify(u) === JSON.stringify({ bounces: 1, replies: 2, booked: 1 }));
}

if (failed) { console.log(`metrics_unit: ${failed} FAILED`); process.exit(1); }
console.log("metrics_unit: all checks passed");
