// Home page logic (spec 2026-11-26-plan6-metrics-design.md 7.5). Pure: no supabase import, no clock reads (callers pass `now`).
import { pricedUsd, type Prices, type Spend } from "./metrics";

const DAY = 86_400_000;
const utcDay = (t: Date) => Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate());

/** ISO UTC bounds of the local calendar day `daysAgo` before `now`: from inclusive, to exclusive (gte/lt). DST days come out 23 or 25 hours. */
export function dayRange(now: Date, daysAgo: number): { from: string; to: string } {
  const [y, m, d] = [now.getFullYear(), now.getMonth(), now.getDate() - daysAgo];
  return { from: new Date(y, m, d).toISOString(), to: new Date(y, m, d + 1).toISOString() };
}

/** The gtm/budget.py credit rule (operating-layer 16). `geminiUsdSince` is Gemini dollars since credit_balance_as_of; dates are UTC. */
export function creditStatus(
  v: { credit_end_date: string; credit_balance_usd: number; credit_balance_as_of: string },
  geminiUsdSince: number,
  now: Date,
): { remaining: number; daysLeft: number; ended: boolean; warn: string | null } {
  const remaining = Math.max(0, v.credit_balance_usd - geminiUsdSince);
  const end = Date.parse(`${v.credit_end_date.slice(0, 10)}T00:00:00Z`);
  const daysLeft = Math.max(0, Math.round((end - utcDay(now)) / DAY));
  const ended = utcDay(now) >= end || remaining === 0;
  const warn = ended ? "Google credit has ended"
    : remaining < 0.2 * v.credit_balance_usd ? "Google credit is under 20 percent left"
    : daysLeft < 14 ? `Google credit ends in under 14 days (${daysLeft} left)` : null;
  return { remaining, daysLeft, ended, warn };
}

const CREDIT_PRICE: Record<string, keyof Prices> = { hunter: "hunter", hunter_import: "hunter", prospeo: "prospeo", serper: "serper", serper_maps: "serper" };

/** Month spend against the PKR budget. Gemini rows count only once the Google credit ended; credit providers with no price entered are listed as units. */
export function budgetMeter(
  monthSpend: Spend,
  creditEnded: boolean,
  v: { monthly_budget_pkr: number; pkr_per_usd: number },
  p: Prices,
): { spentUsd: number; budgetUsd: number; pct: number | null; creditsUnpriced: Record<string, number> } {
  const counted = Object.fromEntries(Object.entries(monthSpend).filter(([prov]) => creditEnded || !prov.startsWith("gemini")));
  const spentUsd = pricedUsd(counted, p);
  const budgetUsd = v.pkr_per_usd > 0 ? v.monthly_budget_pkr / v.pkr_per_usd : 0;
  const creditsUnpriced = Object.fromEntries(
    Object.entries(monthSpend).filter(([prov, s]) => CREDIT_PRICE[prov] && s.units > 0 && !p[CREDIT_PRICE[prov]]).map(([prov, s]) => [prov, s.units]),
  );
  return { spentUsd, budgetUsd, pct: Number.isFinite(budgetUsd) && budgetUsd > 0 ? (spentUsd / budgetUsd) * 100 : null, creditsUnpriced };
}

export type HomeCounts = {
  replies: number; mailboxPaused: string | null; approvedWhileOff: number; followupsDrafted: number;
  draftsWaiting: number; selectedUnapproved: number; batch: { no: number; fill: number } | null;
};

const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;

/** One line, first match wins (spec 7.5). */
export function nextAction(c: HomeCounts): { text: string; href: string } {
  if (c.replies > 0) return { text: `${n(c.replies, "reply needs", "replies need")} a look`, href: "/replies" };
  if (c.mailboxPaused !== null) return { text: c.mailboxPaused ? `Mailbox paused: ${c.mailboxPaused}` : "Mailbox paused", href: "/send" };
  if (c.approvedWhileOff > 0) return { text: `${n(c.approvedWhileOff, "approved email is", "approved emails are")} waiting while sending is off`, href: "/send" };
  if (c.followupsDrafted > 0) return { text: `${n(c.followupsDrafted, "follow-up", "follow-ups")} waiting for approval`, href: "/send" };
  if (c.draftsWaiting > 0) return { text: `${n(c.draftsWaiting, "draft", "drafts")} waiting for review`, href: "/drafts" };
  if (c.selectedUnapproved > 0) return { text: `${n(c.selectedUnapproved, "selected lead", "selected leads")} waiting for approval`, href: "/review" };
  if (c.batch) return { text: `Batch ${String(c.batch.no).padStart(2, "0")} is filling: ${c.batch.fill} of 100`, href: "/batches" };
  return { text: "Nothing waiting", href: "/leads" };
}
