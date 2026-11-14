import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { enqueueJobOnce } from "./actions";
import type { Job, SpendRow } from "./types";

export const BATCH_SIZE = 100;

export type BatchNoRow = {
  batch_no: number; leads: number; byStatus: Record<string, number>;
  apify_usd: number; hunter_credits: number; prospeo_credits: number; serper_queries: number; gemini_usd: number;
};

export const fillLabel = (r: BatchNoRow) => `${r.leads} of ${BATCH_SIZE}`;

/** Batches of 100 (leads.batch_no), newest first; a batch with no spend row (the view is empty until a lead-linked cost is logged) counts zero. */
export async function loadBatchNos(): Promise<BatchNoRow[]> {
  const leads = await fetchAll<{ batch_no: number; status: string }>((f, t) =>
    supabase.from("leads").select("batch_no,status").not("batch_no", "is", null).order("batch_no").order("id").range(f, t));
  const sp = await supabase.from("batch_no_spend").select("*");
  if (sp.error) throw new Error(sp.error.message);
  const spend = new Map((sp.data ?? []).map((s) => [Number(s.batch_no), s]));
  const rows = new Map<number, BatchNoRow>();
  for (const l of leads) {
    let r = rows.get(l.batch_no);
    if (!r) {
      const s = spend.get(l.batch_no);
      r = { batch_no: l.batch_no, leads: 0, byStatus: {}, apify_usd: Number(s?.apify_usd ?? 0), hunter_credits: Number(s?.hunter_credits ?? 0),
        prospeo_credits: Number(s?.prospeo_credits ?? 0), serper_queries: Number(s?.serper_queries ?? 0), gemini_usd: Number(s?.gemini_usd ?? 0) };
      rows.set(l.batch_no, r);
    }
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

export const retryOpen = (jobs: Job[], batchId: string) =>
  jobs.some((j) => j.kind === "enrich" && ["queued", "running", "paused_budget"].includes(j.status)
    && JSON.stringify(j.payload?.argv ?? []) === JSON.stringify(retryArgv(batchId)));

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
