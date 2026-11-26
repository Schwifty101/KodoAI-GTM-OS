import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { enqueueJobOnce } from "./actions";
import { CONFIRM_KINDS, baseKind, isConfirmFlag, type JobRow } from "./runnow";
import type { Job, SpendRow } from "./types";

export const BATCH_SIZE = 100;

export type BatchNoRow = {
  batch_no: number; leads: number; byStatus: Record<string, number>;
  apify_usd: number; hunter_credits: number; prospeo_credits: number; serper_queries: number; gemini_usd: number;
};

/** `base` = leads already in this batch outside the OS (the batch_base setting): they count as filled, like gtm/batches.py and the autopilot do. */
export const fillLabel = (r: Pick<BatchNoRow, "leads">, base = 0) => `${r.leads + base} of ${BATCH_SIZE}`;

/** The batch_base setting ({"3": 32}) as {3: 32}; anything that is not a whole-number key with a number value is ignored. */
export function batchBase(v: unknown): Record<number, number> {
  const o = v && typeof v === "object" ? (v as Record<string, unknown>) : {};
  return Object.fromEntries(Object.entries(o).filter(([k, n]) => Number.isInteger(Number(k)) && typeof n === "number").map(([k, n]) => [Number(k), n as number]));
}

export type OutreachBatch = { batch_no: number; leads: number; base: number; selected: number; approved: number; drafted: number; sent: number; replied: number };

/**
 * One row per batch of 100, newest first. `leads` is the fill: OS-numbered leads plus the batch_base share (a batch that holds only base leads still gets a row).
 * Counts are by lead status: `approved` is the part of `selected` already approved (drafting makes a lead `drafted`); `replied` includes booked.
 */
export function outreachRows(leads: { batch_no: number; status: string; approved: boolean }[], base: Record<number, number> = {}): OutreachBatch[] {
  const rows = new Map<number, OutreachBatch>();
  const row = (n: number) => {
    let r = rows.get(n);
    if (!r) rows.set(n, r = { batch_no: n, leads: base[n] ?? 0, base: base[n] ?? 0, selected: 0, approved: 0, drafted: 0, sent: 0, replied: 0 });
    return r;
  };
  for (const n of Object.keys(base)) row(Number(n));
  for (const l of leads) {
    const r = row(l.batch_no);
    r.leads++;
    if (l.status === "selected") { r.selected++; if (l.approved) r.approved++; }
    else if (l.status === "drafted") r.drafted++;
    else if (l.status === "sent") r.sent++;
    else if (l.status === "replied" || l.status === "booked") r.replied++;
  }
  return [...rows.values()].sort((a, b) => b.batch_no - a.batch_no);
}

export async function loadOutreachBatches(base: Record<number, number> = {}): Promise<OutreachBatch[]> {
  const leads = await fetchAll<{ batch_no: number; status: string; approved: boolean }>((f, t) =>
    supabase.from("leads").select("batch_no,status,approved").not("batch_no", "is", null).order("batch_no").order("id").range(f, t));
  return outreachRows(leads, base);
}

export type BatchSpend = Pick<BatchNoRow, "apify_usd" | "hunter_credits" | "prospeo_credits" | "serper_queries" | "gemini_usd">;
const NO_SPEND: BatchSpend = { apify_usd: 0, hunter_credits: 0, prospeo_credits: 0, serper_queries: 0, gemini_usd: 0 };

/** Spend recorded against each batch of 100 (batch_no_spend: only cost rows that carry a lead). A batch with no row has no recorded cost: callers count zero. */
export async function loadBatchSpend(): Promise<Map<number, BatchSpend>> {
  const sp = await supabase.from("batch_no_spend").select("*");
  if (sp.error) throw new Error(sp.error.message);
  return new Map((sp.data ?? []).map((s) => [Number(s.batch_no), {
    apify_usd: Number(s.apify_usd ?? 0), hunter_credits: Number(s.hunter_credits ?? 0), prospeo_credits: Number(s.prospeo_credits ?? 0),
    serper_queries: Number(s.serper_queries ?? 0), gemini_usd: Number(s.gemini_usd ?? 0),
  }]));
}

export type BatchCard = OutreachBatch & BatchSpend;

/** The Outreach batches cards: each batch's counts plus the spend recorded against it (zero when the view has no row). */
export const batchCards = (rows: OutreachBatch[], spend: Map<number, BatchSpend>): BatchCard[] =>
  rows.map((r) => ({ ...r, ...(spend.get(r.batch_no) ?? NO_SPEND) }));

/** Batches of 100 (leads.batch_no), newest first; a batch with no spend row (the view is empty until a lead-linked cost is logged) counts zero. */
export async function loadBatchNos(): Promise<BatchNoRow[]> {
  const leads = await fetchAll<{ batch_no: number; status: string }>((f, t) =>
    supabase.from("leads").select("batch_no,status").not("batch_no", "is", null).order("batch_no").order("id").range(f, t));
  const spend = await loadBatchSpend();
  const rows = new Map<number, BatchNoRow>();
  for (const l of leads) {
    let r = rows.get(l.batch_no);
    if (!r) rows.set(l.batch_no, r = { batch_no: l.batch_no, leads: 0, byStatus: {}, ...(spend.get(l.batch_no) ?? NO_SPEND) });
    r.leads++;
    r.byStatus[l.status] = (r.byStatus[l.status] ?? 0) + 1;
  }
  return [...rows.values()].sort((a, b) => b.batch_no - a.batch_no);
}

export type RetryRow = { batch_id: string; name: string; created_at: string; named: number; unnamed: number };

/** Per scrape run: no_buyer leads with a saved owner name (retryable) versus none (parked). Only runs with at least one no_buyer. */
export async function loadRetryCandidates(): Promise<RetryRow[]> {
  const leads = await fetchAll<{ batch_id: string | null; owner_name: string | null }>((f, t) =>
    supabase.from("leads").select("batch_id,owner_name").eq("status", "no_buyer").order("id").range(f, t));
  const counts = new Map<string, { named: number; unnamed: number }>();
  for (const l of leads) {
    if (!l.batch_id) continue;
    const c = counts.get(l.batch_id) ?? { named: 0, unnamed: 0 };
    if (l.owner_name && l.owner_name.trim()) c.named++; else c.unnamed++;
    counts.set(l.batch_id, c);
  }
  if (!counts.size) return [];
  const b = await supabase.from("batches").select("id,name,created_at").in("id", [...counts.keys()]);
  if (b.error) throw new Error(b.error.message);
  return (b.data ?? []).map((x) => ({ batch_id: x.id, name: x.name, created_at: x.created_at, ...counts.get(x.id)! }))
    .sort((a, c) => c.created_at.localeCompare(a.created_at));
}

export const retryArgv = (batchId: string) => ["--batch", batchId, "--retry-no-buyer", "--named-only"];

type JobLike = Pick<Job, "kind" | "status" | "payload">;

const retryJobs = (jobs: JobLike[], batchId: string) =>
  jobs.filter((j) => j.kind === "enrich" && ["queued", "running", "paused_budget"].includes(j.status)
    && JSON.stringify(j.payload?.argv ?? []) === JSON.stringify(retryArgv(batchId)));

export const retryOpen = (jobs: JobLike[], batchId: string) => retryJobs(jobs, batchId).length > 0;

/** Why the Retry later button of one scrape run is disabled ("" = enabled). A retry paused on budget is not "queued or running": it waits for credit. */
export function retryWhy(jobs: JobLike[], batchId: string, named: number, allBlocked: boolean): string {
  if (named === 0) return "no named owners";
  const open = retryJobs(jobs, batchId);
  if (open.some((j) => j.status !== "paused_budget")) return "already queued or running";
  if (open.length) return "paused on budget";
  return allBlocked ? "Hunter and Prospeo are both blocked" : "";
}

/** A scrape run with no leads (an empty tile) and no intake-step job naming it: hidden behind the "show empty runs" toggle. */
export const isEmptyRun = (run: { batch_id: string; scraped: number }, jobs: JobRow[]) =>
  Number(run.scraped) === 0 && !jobs.some((j) => (j.payload?.argv ?? []).includes(run.batch_id));

/** The Autopilot card's inputs start from the stored limit (0 = no limit), so Start / Resume never resets it to the built-in default. */
export const limitInputs = (stored: number) => ({ limit: stored === 0 ? "" : String(stored), noLimit: stored === 0 });

// Intake runs: the per-run pipeline row. Job rows come from loadBatchJobs; step gating is stepState in runnow.ts.
const STEP_KINDS = ["clean", "verify-sheet", "enrich", "signals", "select", "import-sheet"];
const OPEN = ["queued", "running", "paused_budget"];

/** Scrape runs start at clean; a sheet import is already imported and has the extra verify-sheet step before enrich. */
export const INTAKE_ORDER = ["clean", "enrich", "signals", "select"];
export const SHEET_ORDER = ["import", "clean", "verify-sheet", "enrich", "signals", "select"];

/** A sheet-import intake run, by name: the same test gtm/sheet_queue.py uses (BATCH_NAME "Sheet import" in gtm/sheet_import.py). */
export const isSheetBatch = (name: string) => name.startsWith("Sheet import");

/** Lead status each step reads (what its confirm dialog counts). */
export const STEP_INPUT: Record<string, string> = { clean: "scraped", enrich: "cleaned", signals: "enriched", select: "signalled" };

/**
 * The last 200 intake-step jobs, any status, newest first; `_test` twins are included so the verify scripts and the browser check can drive it.
 * ponytail: with a busy autopilot older jobs fall out of the window, so a step of an old run can grey; widen the limit or read lead statuses if that bites.
 */
export async function loadBatchJobs(): Promise<JobRow[]> {
  const { data, error } = await supabase.from("jobs").select("id,kind,status,payload,result,error,created_at,finished_at")
    .in("kind", [...STEP_KINDS, ...STEP_KINDS.map((k) => `${k}_test`)]).order("created_at", { ascending: false }).limit(200);
  if (error) throw new Error(error.message);
  return (data ?? []) as JobRow[];
}

/** Leads of a source batch in one status (head count, no rows). */
export async function countByStatus(batchId: string, status: string): Promise<number> {
  const { count, error } = await supabase.from("leads").select("id", { count: "exact", head: true }).eq("batch_id", batchId).eq("status", status);
  if (error) throw new Error(error.message);
  return count ?? 0;
}

/** What enrich would work on: cleaned leads of the run (it spends Hunter and Prospeo credits per email found). */
export const countCleaned = (batchId: string) => countByStatus(batchId, "cleaned");

/** Jobs that count as "step done" for stepState: a sheet pass's dry run (no --confirm) changed nothing, so only its apply counts. */
export const doneJobs = (jobs: JobRow[]) => jobs.filter((j) => !CONFIRM_KINDS.includes(baseKind(j.kind)) || (j.payload?.argv ?? []).some(isConfirmFlag));

/** True while a job of this kind for this run is queued, running or paused for budget (any flags: a retry and a plain enrich must not overlap). */
export const stepOpen = (jobs: JobRow[], kind: string, batchId: string) =>
  jobs.some((j) => baseKind(j.kind) === kind && OPEN.includes(j.status) && (j.payload?.argv ?? []).includes(batchId));

export function creditState(spend: SpendRow[], vals: Record<string, unknown>) {
  return (["hunter", "prospeo"] as const).map((provider) => {
    const s = spend.find((r) => r.provider === provider);
    const cap = Number(vals[`cap_${provider}_credits_day`] ?? 0);
    const today = Number(s?.units_today ?? 0);
    return { provider, today, cap, month: Number(s?.units_month ?? 0), blocked: cap === 0 || today >= cap };
  });
}

/** The only paid action on the page: queues the retry; the VM worker runs it. Refused while an identical job is open. */
export const retryLater = (batchId: string) => enqueueJobOnce("enrich", retryArgv(batchId));
