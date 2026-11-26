import type { BatchNoRow } from "./batches";

// Dashboard by outreach batch (leads.batch_no). Pure logic only (no supabase import) so scripts/dashboard_unit.mts runs without env. Funnel rules are the batch_metrics view's (supabase/migrations/0006), re-keyed from scrape run to batch number.

export type DashTouch = { touch_no: number; status: string; outcome: string | null };
export type DashLead = { batch_no: number | null; status: string; owner_email: string | null; email_verified: boolean | null; touches: DashTouch[] };
export const DASH_LEAD_SELECT = "batch_no,status,owner_email,email_verified,touches(touch_no,status,outcome)";

/** `of` is the column a rate is taken from; bounced and replied are both shares of sent (replied of bounced would mean nothing). */
export const COLS = [
  { key: "leads", label: "Leads", hint: "leads numbered into the batch", of: null },
  { key: "enriched", label: "Enriched", hint: "enriched or better: a named owner with a verified email", of: "leads" },
  { key: "drafted", label: "Drafted", hint: "Touch 1 written", of: "enriched" },
  { key: "sent", label: "Sent", hint: "Touch 1 sent", of: "drafted" },
  { key: "bounced", label: "Bounced", hint: "", of: "sent" },
  { key: "replied", label: "Replied", hint: "any real reply, including opt-outs", of: "sent" },
  { key: "positive", label: "Positive", hint: "marked by you, or booked", of: "replied" },
  { key: "booked", label: "Booked", hint: "marked by you", of: "positive" },
] as const;
export type Col = (typeof COLS)[number]["key"];
export type Funnel = Record<Col, number>;
export type BatchFunnel = { batch_no: number; f: Funnel };

const REPLY_OUTCOMES = ["positive", "negative", "other", "opt_out"];
const PIPELINE = ["cleaned", "enriched", "signalled", "selected", "drafted", "sent", "replied", "booked", "bounced", "unsubscribed"];

export const batchLabel = (n: number) => `Batch ${String(n).padStart(2, "0")}`;

/** Share of `of` as "12%"; null when `of` is zero; "<1%" when something is there but rounds to nothing. */
export function pct(v: number, of: number): string | null {
  if (!of) return null;
  const p = (100 * v) / of;
  return v > 0 && p < 1 ? "<1%" : `${Math.round(p)}%`;
}

const zero = (): Funnel => ({ leads: 0, enriched: 0, drafted: 0, sent: 0, bounced: 0, replied: 0, positive: 0, booked: 0 });

/** Same tests as the batch_metrics view: replied and positive come from lead status or a touch outcome. */
function add(f: Funnel, l: DashLead) {
  const t = l.touches ?? [];
  f.leads++;
  if (l.owner_email && l.email_verified) f.enriched++;
  if (t.some((x) => x.touch_no === 1)) f.drafted++;
  if (t.some((x) => x.touch_no === 1 && x.status === "sent")) f.sent++;
  if (l.status === "bounced") f.bounced++;
  if (["replied", "unsubscribed", "booked"].includes(l.status) || t.some((x) => x.outcome && REPLY_OUTCOMES.includes(x.outcome))) f.replied++;
  if (l.status === "booked" || t.some((x) => x.outcome === "positive")) f.positive++;
  if (l.status === "booked") f.booked++;
}

const sum = (fs: Funnel[]): Funnel => fs.reduce((a, f) => { for (const c of COLS) a[c.key] += f[c.key]; return a; }, zero());

/**
 * One funnel per batch number (newest first), one for leads with no number that are still in play, and the total of both.
 * `other` counts the rest by status (scraped, rejected, no_buyer, suppressed): they are not in play, so they stay out of the table.
 */
export function dashboardRows(leads: DashLead[]) {
  const by = new Map<number, Funnel>();
  const pipeline = zero();
  const other: Record<string, number> = {};
  for (const l of leads) {
    if (l.batch_no != null) {
      let f = by.get(l.batch_no);
      if (!f) by.set(l.batch_no, f = zero());
      add(f, l);
    } else if (PIPELINE.includes(l.status)) add(pipeline, l);
    else other[l.status] = (other[l.status] ?? 0) + 1;
  }
  const batches: BatchFunnel[] = [...by].map(([batch_no, f]) => ({ batch_no, f })).sort((a, b) => b.batch_no - a.batch_no);
  return { batches, pipeline, all: sum([...batches.map((b) => b.f), pipeline]), other };
}

export type CostRow = { batch_no: number | null; apify_usd: number; gemini_usd: number; hunter_credits: number; prospeo_credits: number; serper_queries: number; usd: number; perEnriched: number | null; perReply: number | null };

/** Spend per batch from the /batches loader (loadBatchNos); a batch with no spend row counts zero. Dollars are Apify plus Gemini: Hunter, Prospeo and Serper are logged in credits or queries, not priced. Per-lead and per-reply are null, not zero, when the divisor is 0. */
export function costRows(batches: BatchFunnel[], spend: Pick<BatchNoRow, "batch_no" | "apify_usd" | "gemini_usd" | "hunter_credits" | "prospeo_credits" | "serper_queries">[]): { rows: CostRow[]; all: CostRow } {
  const row = (batch_no: number | null, s: Omit<CostRow, "batch_no" | "usd" | "perEnriched" | "perReply">, f: Funnel): CostRow => {
    const usd = s.apify_usd + s.gemini_usd;
    return { batch_no, ...s, usd, perEnriched: f.enriched ? usd / f.enriched : null, perReply: f.replied ? usd / f.replied : null };
  };
  const rows = batches.map(({ batch_no, f }) => {
    const s = spend.find((x) => x.batch_no === batch_no);
    return row(batch_no, { apify_usd: s?.apify_usd ?? 0, gemini_usd: s?.gemini_usd ?? 0, hunter_credits: s?.hunter_credits ?? 0, prospeo_credits: s?.prospeo_credits ?? 0, serper_queries: s?.serper_queries ?? 0 }, f);
  });
  const t = (k: "apify_usd" | "gemini_usd" | "hunter_credits" | "prospeo_credits" | "serper_queries") => rows.reduce((a, r) => a + r[k], 0);
  const all = row(null, { apify_usd: t("apify_usd"), gemini_usd: t("gemini_usd"), hunter_credits: t("hunter_credits"), prospeo_credits: t("prospeo_credits"), serper_queries: t("serper_queries") }, sum(batches.map((b) => b.f)));
  return { rows, all };
}
