// Pure-logic checks for the Batches page helpers in web/lib/batches.ts. No database, no network:
// batches.ts imports the Supabase client, so dummy env values let it load; nothing here calls it.
// Run: cd web && npx tsx scripts/batches_unit.mts
import assert from "node:assert/strict";
import type { JobRow } from "../lib/runnow";

process.env.NEXT_PUBLIC_SUPABASE_URL ??= "http://127.0.0.1:1";
process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ??= "unit-test-key";
const { batchCards, isEmptyRun, limitInputs, outreachRows, retryArgv, retryOpen, retryWhy } = await import("../lib/batches");

let n = 0;
const job = (kind: string, status: string, argv: string[]): JobRow => ({
  id: `j${++n}`, kind, status, payload: { argv }, result: null, error: null, created_at: "2026-11-25T12:00:00Z", finished_at: null,
});

// batchCards: counts from outreachRows plus recorded spend; a batch without a spend row counts zero
const rows = outreachRows([
  { batch_no: 3, status: "selected", approved: true }, { batch_no: 3, status: "sent", approved: false }, { batch_no: 4, status: "drafted", approved: false },
], { 3: 32 });
const spend = new Map([[3, { apify_usd: 0.5, hunter_credits: 7, prospeo_credits: 2, serper_queries: 40, gemini_usd: 0.0123 }]]);
const cards = batchCards(rows, spend);
assert.deepEqual(cards.map((c) => c.batch_no), [4, 3], "newest first, order kept");
assert.equal(cards[1].leads, 34); assert.equal(cards[1].base, 32); assert.equal(cards[1].selected, 1); assert.equal(cards[1].approved, 1); assert.equal(cards[1].sent, 1);
assert.deepEqual([cards[1].apify_usd, cards[1].hunter_credits, cards[1].prospeo_credits, cards[1].serper_queries, cards[1].gemini_usd], [0.5, 7, 2, 40, 0.0123], "spend joined by batch_no");
assert.deepEqual([cards[0].apify_usd, cards[0].hunter_credits, cards[0].prospeo_credits, cards[0].serper_queries, cards[0].gemini_usd], [0, 0, 0, 0, 0], "no spend row = zero, nothing invented");
assert.equal(cards[0].drafted, 1);
assert.deepEqual(batchCards([], spend), [], "no batches, no cards");

// retryWhy: paused_budget is its own label; queued or running wins; blocked comes last
const RA = retryArgv("B1");
assert.equal(retryWhy([], "B1", 0, false), "no named owners");
assert.equal(retryWhy([job("enrich", "queued", RA)], "B1", 0, false), "no named owners", "no named owners beats an open job");
assert.equal(retryWhy([], "B1", 3, false), "", "enabled");
assert.equal(retryWhy([], "B1", 3, true), "Hunter and Prospeo are both blocked");
assert.equal(retryWhy([job("enrich", "queued", RA)], "B1", 3, false), "already queued or running");
assert.equal(retryWhy([job("enrich", "running", RA)], "B1", 3, true), "already queued or running");
assert.equal(retryWhy([job("enrich", "paused_budget", RA)], "B1", 3, false), "paused on budget");
assert.equal(retryWhy([job("enrich", "paused_budget", RA)], "B1", 3, true), "paused on budget", "paused beats blocked");
assert.equal(retryWhy([job("enrich", "paused_budget", RA), job("enrich", "queued", RA)], "B1", 3, false), "already queued or running", "a live job wins over an old paused one");
assert.equal(retryWhy([job("enrich", "done", RA), job("enrich", "failed", RA)], "B1", 3, false), "", "finished jobs do not block");
assert.equal(retryWhy([job("enrich", "paused_budget", retryArgv("B2"))], "B1", 3, false), "", "another run's job");
assert.equal(retryWhy([job("enrich", "paused_budget", ["--batch", "B1"])], "B1", 3, false), "", "a plain enrich is not a retry");
assert.equal(retryWhy([job("signals", "paused_budget", RA)], "B1", 3, false), "", "another kind");
assert.equal(retryOpen([job("enrich", "paused_budget", RA)], "B1"), true, "retryOpen still counts paused_budget");
assert.equal(retryOpen([job("enrich", "done", RA)], "B1"), false);

// isEmptyRun: scraped 0 and no job naming the run
assert.equal(isEmptyRun({ batch_id: "B1", scraped: 0 }, []), true, "empty tile");
assert.equal(isEmptyRun({ batch_id: "B1", scraped: 0 }, [job("clean", "done", ["--batch", "B2"])]), true, "another run's job");
assert.equal(isEmptyRun({ batch_id: "B1", scraped: 0 }, [job("clean", "failed", ["--batch", "B1"])]), false, "a job names it, whatever its status");
assert.equal(isEmptyRun({ batch_id: "B1", scraped: 12 }, []), false, "has leads");
assert.equal(isEmptyRun({ batch_id: "B1", scraped: "0" as unknown as number }, []), true, "a numeric string from the view still counts as 0");

// limitInputs: the card starts from the stored limit
assert.deepEqual(limitInputs(5), { limit: "5", noLimit: false });
assert.deepEqual(limitInputs(0.5), { limit: "0.5", noLimit: false });
assert.deepEqual(limitInputs(0), { limit: "", noLimit: true }, "0 = no limit: box ticked, field empty so unticking cannot silently start with 0");

console.log("batches_unit: all checks passed");
