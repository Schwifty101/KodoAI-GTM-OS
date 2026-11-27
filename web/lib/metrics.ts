// Metrics definitions, one source (spec 2026-11-26-plan6-metrics-design.md 7.1 and 7.3). Pure logic only (no supabase import) so scripts/metrics_unit.mts runs without env. All dates are UTC.

export type Grain = "day" | "week" | "month" | "quarter";
export type LeadRow = {
  id: string; place_id: string; batch_id: string | null; batch_no: number | null; status: string; vector: string | null; signal_led: boolean;
  owner_name: string | null; owner_email: string | null; email_verified: boolean | null; reject_reason: string | null; created_at: string; booked_at: string | null;
};
export type TouchRow = { lead_id: string; touch_no: number; status: string; sent_at: string | null; outcome: string | null; outcome_at: string | null };
export type CostDay = { day: string; provider: string; run_id: string | null; units: number; usd: number };
export type RunRow = { id: string; name: string; created_at: string };
export type Prices = { hunter: number; prospeo: number; serper: number };
export type Spend = Record<string, { units: number; usd: number }>;
export type Cohort = { sent: number; bounced: number; delivered: number; replied: number; positive: number; booked: number };
export type Allocation = { byBatchNo: Map<number, Spend>; notNumbered: Spend; noOwners: Spend; unattributed: Spend };
export type BatchRow = Cohort & { batch_no: number; fill: number; base: number; owners: number; spend: Spend };
export type AngleRow = { vector: string; lane: "signal-led" | "relevance-led"; leads: number } & Cohort;
export type HistoryRow = { start: string; scraped: number; owners: number; touch1: number; followups: number; bounces: number; replies: number; booked: number; spend: Spend };

const REPLY_STATUSES = ["replied", "unsubscribed", "booked"];
const REPLY_OUTCOMES = ["positive", "negative", "other", "opt_out"];

/** Migration 0017 adds outcome_at, booked_at and cost_daily; until the owner applies it, pages show this instead of a bare column error. */
export const hint0017 = (message: string) => (/booked_at|outcome_at|cost_daily/.test(message) ? `Migration 0017 is not applied yet (${message})` : message);

// Filters

/** Same rule as gtm/send.py is_test_lead. */
export const isTestLead = (placeId: string) => placeId.startsWith("TEST_") || placeId.startsWith("REHEARSAL_");
export const isTestRun = (name: string) => name.startsWith("TEST") || name.startsWith("REHEARSAL");
/** Drops cost rows of TEST and REHEARSAL runs; rows with no run are kept. */
export function dropTestRuns(costs: CostDay[], runs: RunRow[]): CostDay[] {
  const test = new Set(runs.filter((r) => isTestRun(r.name)).map((r) => r.id));
  return costs.filter((c) => c.run_id === null || !test.has(c.run_id));
}
/** Verified owner: an owner email that verified. */
export const isOwner = (l: { owner_email: string | null; email_verified: boolean | null }) => !!l.owner_email && l.email_verified === true;
/** The batch_metrics rule: a reply status, or any real reply outcome (a bounce is not a reply). */
export const isReplied = (status: string, outcomes: (string | null | undefined)[]) =>
  REPLY_STATUSES.includes(status) || outcomes.some((o) => !!o && REPLY_OUTCOMES.includes(o));
export const isPositive = (status: string, outcomes: (string | null | undefined)[]) => status === "booked" || outcomes.includes("positive");

// Time

const DAY = 86_400_000;
const ymd = (t: number) => new Date(t).toISOString().slice(0, 10);
/** Midnight UTC of the YYYY-MM-DD (or full ISO) date, as epoch ms. */
const dayMs = (iso: string) => Date.parse(ymd(Date.parse(iso.length === 10 ? `${iso}T00:00:00Z` : iso)) + "T00:00:00Z");

/** Bucket start as UTC YYYY-MM-DD; weeks start Monday, quarters Jan/Apr/Jul/Oct 1. */
export function periodStart(iso: string, grain: Grain): string {
  const t = dayMs(iso);
  const d = new Date(t);
  if (grain === "day") return ymd(t);
  if (grain === "week") return ymd(t - ((d.getUTCDay() + 6) % 7) * DAY);
  const m = grain === "month" ? d.getUTCMonth() : d.getUTCMonth() - (d.getUTCMonth() % 3);
  return ymd(Date.UTC(d.getUTCFullYear(), m, 1));
}

/** Every bucket start from the bucket of `from` through the bucket of `to`, empty ones included. */
export function periodRange(from: string, to: string, grain: Grain): string[] {
  const out: string[] = [];
  const end = periodStart(to, grain);
  for (let s = periodStart(from, grain); s <= end;) {
    out.push(s);
    const d = new Date(dayMs(s));
    const next = grain === "day" ? dayMs(s) + DAY : grain === "week" ? dayMs(s) + 7 * DAY
      : Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + (grain === "month" ? 1 : 3), 1);
    s = ymd(next);
  }
  return out;
}

/** The range of equal length in days that ends the day before `from`. */
export function previousRange(from: string, to: string): { from: string; to: string } {
  const f = dayMs(from);
  const len = (dayMs(to) - f) / DAY + 1;
  return { from: ymd(f - len * DAY), to: ymd(f - DAY) };
}

// Money

export function spendFrom(rows: { provider: string; units: number; usd: number | null }[]): Spend {
  const s: Spend = {};
  for (const r of rows) {
    const p = (s[r.provider] ??= { units: 0, usd: 0 });
    p.units += Number(r.units) || 0;
    p.usd += Number(r.usd) || 0;
  }
  return s;
}

export const addSpend = (a: Spend, b: Spend): Spend =>
  spendFrom([...Object.entries(a), ...Object.entries(b)].map(([provider, v]) => ({ provider, ...v })));

const scale = (s: Spend, k: number): Spend =>
  Object.fromEntries(Object.entries(s).map(([p, v]) => [p, { units: v.units * k, usd: v.usd * k }]));

export const PRICE_OF: Record<string, keyof Prices> = { hunter: "hunter", hunter_import: "hunter", prospeo: "prospeo", serper: "serper", serper_maps: "serper" };

/** Recorded dollars of every provider plus credits times their price (0 = unpriced adds nothing). Groq tokens never become money. */
export function pricedUsd(s: Spend, p: Prices): number {
  let usd = 0;
  for (const [prov, v] of Object.entries(s)) usd += v.usd + (PRICE_OF[prov] ? v.units * p[PRICE_OF[prov]] : 0);
  return usd;
}

/** Each provider's units and usd divided by n; null when n is 0. */
export const perUnit = (s: Spend, n: number): Spend | null => (n ? scale(s, 1 / n) : null);
/** k of n as a fraction; null when n is 0, never NaN. */
export const rate = (k: number, n: number): number | null => (n ? k / n : null);

// Cohorts

const real = (leads: LeadRow[]) => leads.filter((l) => !isTestLead(l.place_id));
const touchesBy = (touches: TouchRow[]) => {
  const m = new Map<string, TouchRow[]>();
  for (const t of touches) {
    const a = m.get(t.lead_id);
    if (a) a.push(t); else m.set(t.lead_id, [t]);
  }
  return m;
};

// ponytail: reads every lead and sent touch in the browser; fine to a few thousand leads, move cohorts into a view when a page load takes seconds.
/** The Touch 1 sent cohort of these leads (test leads dropped). Rates use delivered = sent minus bounced. */
export function cohort(leads: LeadRow[], touches: TouchRow[]): Cohort {
  const by = touchesBy(touches);
  const c: Cohort = { sent: 0, bounced: 0, delivered: 0, replied: 0, positive: 0, booked: 0 };
  for (const l of real(leads)) {
    const ts = by.get(l.id) ?? [];
    if (!ts.some((t) => t.touch_no === 1 && t.status === "sent")) continue;
    const outs = ts.map((t) => t.outcome);
    c.sent++;
    if (l.status === "bounced") c.bounced++;
    if (isReplied(l.status, outs)) c.replied++;
    if (isPositive(l.status, outs)) c.positive++;
    if (l.status === "booked") c.booked++;
  }
  c.delivered = c.sent - c.bounced;
  return c;
}

/** Spec 7.3: each run's spend split equally over its verified owners; the four buckets add up to total spend. */
export function allocateSpend(costs: CostDay[], leads: LeadRow[]): Allocation {
  const al: Allocation = { byBatchNo: new Map(), notNumbered: {}, noOwners: {}, unattributed: {} };
  const runs = new Map<string | null, CostDay[]>();
  for (const c of costs) {
    const a = runs.get(c.run_id);
    if (a) a.push(c); else runs.set(c.run_id, [c]);
  }
  const owners = real(leads).filter(isOwner);
  for (const [run, rows] of runs) {
    const s = spendFrom(rows);
    if (run === null) { al.unattributed = addSpend(al.unattributed, s); continue; }
    const os = owners.filter((l) => l.batch_id === run);
    if (!os.length) { al.noOwners = addSpend(al.noOwners, s); continue; }
    const share = scale(s, 1 / os.length);
    for (const o of os) {
      if (o.batch_no == null) al.notNumbered = addSpend(al.notNumbered, share);
      else al.byBatchNo.set(o.batch_no, addSpend(al.byBatchNo.get(o.batch_no) ?? {}, share));
    }
  }
  return al;
}

/** One row per batch number, newest first. fill counts base (leads outside the OS); rates come from the cohort only. */
export function batchRows(leads: LeadRow[], touches: TouchRow[], alloc: Allocation, base: Record<number, number>): BatchRow[] {
  const by = new Map<number, LeadRow[]>();
  for (const l of real(leads)) if (l.batch_no != null) by.set(l.batch_no, [...(by.get(l.batch_no) ?? []), l]);
  const nos = new Set([...by.keys(), ...Object.keys(base).map(Number), ...alloc.byBatchNo.keys()]);
  return [...nos].sort((a, b) => b - a).map((batch_no) => {
    const ls = by.get(batch_no) ?? [];
    const b = base[batch_no] ?? 0;
    return { batch_no, ...cohort(ls, touches), fill: ls.length + b, base: b, owners: ls.filter(isOwner).length, spend: alloc.byBatchNo.get(batch_no) ?? {} };
  });
}

/** Cohort per vector and lane over numbered leads (or one batch number); groups with nothing sent still appear. */
export function byAngle(leads: LeadRow[], touches: TouchRow[], batchNo?: number): AngleRow[] {
  const groups = new Map<string, { vector: string; lane: AngleRow["lane"]; ls: LeadRow[] }>();
  for (const l of real(leads)) {
    if (l.batch_no == null || (batchNo !== undefined && l.batch_no !== batchNo)) continue;
    const vector = l.vector ?? "(none)";
    const lane = l.signal_led ? "signal-led" : "relevance-led";
    const k = `${vector}\u0000${lane}`;
    const g = groups.get(k);
    if (g) g.ls.push(l); else groups.set(k, { vector, lane, ls: [l] });
  }
  return [...groups.values()]
    .sort((a, b) => (a.vector < b.vector ? -1 : a.vector > b.vector ? 1 : a.lane < b.lane ? -1 : a.lane > b.lane ? 1 : 0))
    .map(({ vector, lane, ls }) => ({ vector, lane, leads: ls.length, ...cohort(ls, touches) }));
}

/** Rejected by reason and no_buyer split by whether an owner was named; descending by n, then reason. */
export function whereLeadsDie(leads: LeadRow[]): { reason: string; n: number }[] {
  const m = new Map<string, number>();
  for (const l of real(leads)) {
    const r = l.status === "rejected" ? (l.reject_reason?.trim() || "rejected, no reason")
      : l.status === "no_buyer" ? (l.owner_name?.trim() ? "no_buyer: owner named" : "no_buyer: no owner found") : null;
    if (r) m.set(r, (m.get(r) ?? 0) + 1);
  }
  return [...m].map(([reason, n]) => ({ reason, n })).sort((a, b) => b.n - a.n || (a.reason < b.reason ? -1 : a.reason > b.reason ? 1 : 0));
}

const isReplyOutcome = (o: string | null) => !!o && REPLY_OUTCOMES.includes(o);

/** Counts and spend per UTC bucket by event date; null timestamps are never bucketed (see undatedCounts). */
export function historyRows(a: { leads: LeadRow[]; touches: TouchRow[]; costs: CostDay[]; grain: Grain; from: string; to: string }): HistoryRow[] {
  const rows = periodRange(a.from, a.to, a.grain).map((start): HistoryRow => ({ start, scraped: 0, owners: 0, touch1: 0, followups: 0, bounces: 0, replies: 0, booked: 0, spend: {} }));
  const idx = new Map(rows.map((r, i) => [r.start, i]));
  const lo = dayMs(a.from), hi = dayMs(a.to);
  const at = (iso: string | null): HistoryRow | undefined => {
    if (!iso) return undefined;
    const t = dayMs(iso);
    return t < lo || t > hi ? undefined : rows[idx.get(periodStart(iso, a.grain))!];
  };
  const ls = real(a.leads);
  const ids = new Set(ls.map((l) => l.id));
  for (const l of ls) {
    const r = at(l.created_at);
    if (r) { r.scraped++; if (isOwner(l)) r.owners++; }
    const b = at(l.booked_at);
    if (b) b.booked++;
  }
  for (const t of a.touches) {
    if (!ids.has(t.lead_id)) continue;
    const s = t.status === "sent" ? at(t.sent_at) : undefined;
    if (s) { if (t.touch_no === 1) s.touch1++; else s.followups++; }
    const o = at(t.outcome_at);
    if (o && t.outcome === "bounce") o.bounces++;
    if (o && isReplyOutcome(t.outcome)) o.replies++;
  }
  for (const c of a.costs) {
    const r = at(c.day);
    if (r) r.spend = addSpend(r.spend, spendFrom([c]));
  }
  return rows;
}

/** Outcomes and bookings with no event date (stored before migration 0017); test leads dropped. */
export function undatedCounts(touches: TouchRow[], leads: LeadRow[]): { bounces: number; replies: number; booked: number } {
  const ls = real(leads);
  const ids = new Set(ls.map((l) => l.id));
  const undated = touches.filter((t) => ids.has(t.lead_id) && t.outcome_at === null);
  return {
    bounces: undated.filter((t) => t.outcome === "bounce").length,
    replies: undated.filter((t) => isReplyOutcome(t.outcome)).length,
    booked: ls.filter((l) => l.status === "booked" && l.booked_at === null).length,
  };
}
