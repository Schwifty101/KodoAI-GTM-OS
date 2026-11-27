// Pure checks for web/lib/metricsFormat.ts. Run: cd web && npx tsx scripts/metricsformat_unit.mts
import assert from "node:assert/strict";
import { defaultFrom, kOf, spendText } from "../lib/metricsFormat";
import { periodRange, type Grain } from "../lib/metrics";

const P0 = { hunter: 0, prospeo: 0, serper: 0 };

assert.equal(kOf(0, 0), "n/a");
assert.equal(kOf(3, 0), "n/a");
assert.equal(kOf(1, 4), "1 of 4 (25%)");
assert.equal(kOf(0, 4), "0 of 4 (0%)");

assert.equal(spendText(null, P0), "n/a");
assert.equal(spendText({}, P0), "$0.0000");
// Recorded dollars as $, unpriced credits as credits, groq as tokens; never NaN.
assert.equal(spendText({ apify: { units: 0, usd: 2 }, hunter: { units: 1.5, usd: 0 }, groq: { units: 900, usd: 0 } }, P0), "$2.00 + 1.5 hunter credits + 900 groq tokens");
// A priced credit becomes dollars and leaves the credit list.
assert.equal(spendText({ hunter: { units: 10, usd: 0 } }, { ...P0, hunter: 0.05 }), "$0.50");

for (const g of ["day", "week", "month", "quarter"] as Grain[]) {
  for (const to of ["2026-11-26", "2026-01-03", "2026-03-31"]) assert.equal(periodRange(defaultFrom(g, to), to, g).length, 8, `${g} ${to}`);
}

console.log("metricsformat_unit: all checks passed");
