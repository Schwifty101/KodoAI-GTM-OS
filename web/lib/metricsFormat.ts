// Presentational formatters for the Metrics page. Pure (no supabase import) so scripts/metricsformat_unit.mts runs without env.
import { pct } from "./dashboard";
import { periodStart, pricedUsd, type Grain, type Prices, type Spend } from "./metrics";

export const money = (n: number | null) => (n == null ? "n/a" : `$${Number(n).toFixed(Number(n) < 0.1 ? 4 : 2)}`);
const qty = (n: number) => String(Math.round(n * 100) / 100);

/** "k of n (p%)"; "n/a" when n is 0. */
export const kOf = (k: number, n: number) => (n ? `${k} of ${n} (${pct(k, n)})` : "n/a");

/** Priced dollars, plus each provider whose units stay unpriced (credits; groq tokens). null prints n/a. */
export function spendText(s: Spend | null, p: Prices): string {
  if (!s) return "n/a";
  const left = Object.entries(s).filter(([prov, v]) => v.units > 0 && v.usd === 0 && pricedUsd({ [prov]: v }, p) === 0)
    .map(([prov, v]) => `${qty(v.units)} ${prov} ${prov === "groq" ? "tokens" : "credits"}`);
  return [money(pricedUsd(s, p)), ...left].join(" + ");
}

/** Start date of the range that holds the last 8 periods of the grain ending with the period of `to` (UTC). */
export function defaultFrom(grain: Grain, to: string): string {
  const d = new Date(`${periodStart(to, grain)}T00:00:00Z`);
  const y = d.getUTCFullYear(), m = d.getUTCMonth(), day = d.getUTCDate();
  const t = grain === "day" ? Date.UTC(y, m, day - 7) : grain === "week" ? Date.UTC(y, m, day - 49) : Date.UTC(y, m - (grain === "month" ? 7 : 21), 1);
  return new Date(t).toISOString().slice(0, 10);
}
