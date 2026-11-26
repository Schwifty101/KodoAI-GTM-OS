import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { spendFrom, type Spend } from "./metrics";

export type LeadTouch = { touch_no: number; status: string; sent_at: string | null; outcome: string | null; outcome_at: string | null };

/** Spec 7.7: this lead's cost_log rows by provider, and its touches. touches.outcome_at needs migration 0017. */
export async function loadLeadActivity(leadId: string): Promise<{ spend: Spend; touches: LeadTouch[] }> {
  const costs = await fetchAll<{ provider: string; units: number; usd: number | null }>((f, t) =>
    supabase.from("cost_log").select("provider,units,usd").eq("lead_id", leadId).order("created_at").order("id").range(f, t));
  const touches = await fetchAll<LeadTouch>((f, t) =>
    supabase.from("touches").select("touch_no,status,sent_at,outcome,outcome_at").eq("lead_id", leadId).order("touch_no").order("id").range(f, t));
  return { spend: spendFrom(costs), touches };
}
