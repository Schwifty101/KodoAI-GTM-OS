// Pure-logic checks for web/lib/dashboard.ts. No database, no network.
// Run: cd web && npx tsx scripts/dashboard_unit.mts
import assert from "node:assert/strict";
import { COLS, batchLabel, costRows, dashboardRows, pct, type DashLead, type DashTouch } from "../lib/dashboard";

const t = (touch_no: number, status: string, outcome: string | null = null): DashTouch => ({ touch_no, status, outcome });
const lead = (batch_no: number | null, status: string, o: { email?: boolean; touches?: DashTouch[] } = {}): DashLead => ({
  batch_no, status, owner_email: o.email === false ? null : "a@b.co", email_verified: o.email === false ? null : true, touches: o.touches ?? [],
});

// pct: zero divisor, rounding, and a small share that is not zero
assert.equal(pct(5, 0), null, "no divisor, no rate");
assert.equal(pct(0, 0), null);
assert.equal(pct(0, 10), "0%");
assert.equal(pct(1, 3), "33%");
assert.equal(pct(1, 300), "<1%", "something is there but under one percent");
assert.equal(pct(10, 10), "100%");
assert.equal(batchLabel(3), "Batch 03");
assert.equal(batchLabel(12), "Batch 12");

// Rates come from the column named in COLS: replied and bounced are shares of sent, not of each other
assert.deepEqual(COLS.map((c) => [c.key, c.of]), [
  ["leads", null], ["enriched", "leads"], ["drafted", "enriched"], ["sent", "drafted"], ["bounced", "sent"], ["replied", "sent"], ["positive", "replied"], ["booked", "positive"],
]);

// Grouping: batches newest first, then pipeline, then everything else by status
const leads: DashLead[] = [
  lead(3, "selected"),
  lead(3, "drafted", { touches: [t(1, "approved")] }),
  lead(3, "sent", { touches: [t(1, "sent"), t(2, "scheduled")] }),
  lead(3, "replied", { touches: [t(1, "sent", "negative")] }),
  lead(3, "booked", { touches: [t(1, "sent", "positive")] }),
  lead(3, "bounced", { touches: [t(1, "sent")] }),
  lead(3, "unsubscribed", { touches: [t(1, "sent", "opt_out")] }),
  lead(3, "replied", { touches: [t(1, "sent", "positive")] }),
  lead(4, "selected"),
  lead(null, "cleaned", { email: false }),
  lead(null, "enriched"),
  lead(null, "signalled"),
  lead(null, "sent", { touches: [t(1, "sent")] }),
  lead(null, "no_buyer", { email: false }),
  lead(null, "no_buyer", { email: false }),
  lead(null, "rejected", { email: false }),
  lead(null, "scraped", { email: false }),
  lead(null, "suppressed"),
];
const d = dashboardRows(leads);
assert.deepEqual(d.batches.map((b) => b.batch_no), [4, 3], "newest first");
assert.deepEqual(d.batches[0].f, { leads: 1, enriched: 1, drafted: 0, sent: 0, bounced: 0, replied: 0, positive: 0, booked: 0 });
assert.deepEqual(d.batches[1].f, { leads: 8, enriched: 8, drafted: 7, sent: 6, bounced: 1, replied: 4, positive: 2, booked: 1 }, "batch 3: unsubscribed and any outcome count as replied; booked or a positive outcome as positive");
assert.deepEqual(d.pipeline, { leads: 4, enriched: 3, drafted: 1, sent: 1, bounced: 0, replied: 0, positive: 0, booked: 0 }, "cleaned, enriched, signalled and a never-numbered sent lead");
assert.deepEqual(d.other, { no_buyer: 2, rejected: 1, scraped: 1, suppressed: 1 }, "not in play: counted by status, not in a row");
assert.equal(d.all.leads, 1 + 8 + 4, "All is the batches plus the pipeline row");
assert.equal(d.all.leads + Object.values(d.other).reduce((a, n) => a + n, 0), leads.length, "every lead is in a row or in the not-in-play note");
for (const c of COLS) assert.equal(d.all[c.key], d.batches.reduce((a, b) => a + b.f[c.key], 0) + d.pipeline[c.key], `All ${c.key}`);

// A batch number with a rejected or no_buyer lead still counts that lead in the batch (it holds the number)
assert.equal(dashboardRows([lead(5, "rejected", { email: false })]).batches[0].f.leads, 1);
// A lead whose touches are missing (null) does not throw
assert.equal(dashboardRows([{ ...lead(5, "selected"), touches: null as unknown as DashTouch[] }]).batches[0].f.drafted, 0);
// Nothing at all
const none = dashboardRows([]);
assert.deepEqual(none.batches, []);
assert.equal(none.all.leads, 0);

// costRows: dollars are Apify plus Gemini; per-lead and per-reply are null (not zero, not NaN) when there is nothing to divide by
const sp = (batch_no: number, apify_usd: number, gemini_usd: number, hunter_credits = 0, prospeo_credits = 0, serper_queries = 0) => ({ batch_no, apify_usd, gemini_usd, hunter_credits, prospeo_credits, serper_queries });
const c = costRows(d.batches, [sp(3, 0.5, 1.5, 51, 2, 127)]);
assert.deepEqual(c.rows.map((r) => r.batch_no), [4, 3]);
assert.equal(c.rows[0].usd, 0, "a batch with no spend row counts zero");
assert.equal(c.rows[0].perEnriched, 0, "zero spend over one enriched lead is 0, not n/a");
assert.equal(c.rows[0].perReply, null, "no replies: n/a, never a divide by zero");
assert.equal(c.rows[1].usd, 2);
assert.equal(c.rows[1].perEnriched, 2 / 8);
assert.equal(c.rows[1].perReply, 2 / 4);
assert.equal(c.rows[1].hunter_credits, 51);
assert.equal(c.all.usd, 2);
assert.equal(c.all.perEnriched, 2 / 9, "All divides by the enriched leads of the batches only, matching where the spend comes from");
assert.equal(c.all.perReply, 2 / 4);
assert.equal(c.all.serper_queries, 127);
const empty = costRows([], []);
assert.deepEqual(empty.rows, []);
assert.equal(empty.all.perEnriched, null);
assert.equal(empty.all.perReply, null);
const noEnr = costRows(dashboardRows([lead(7, "selected", { email: false })]).batches, [sp(7, 1, 1)]);
assert.equal(noEnr.rows[0].perEnriched, null, "spend but no enriched lead: n/a");

console.log("dashboard_unit: all checks passed");
