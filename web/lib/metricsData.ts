import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { dropTestRuns, isTestLead, type CostDay, type LeadRow, type RunRow, type TouchRow } from "./metrics";

const LEAD_SELECT = "id,place_id,batch_id,batch_no,status,vector,signal_led,owner_name,owner_email,email_verified,reject_reason,created_at,booked_at";

/** Everything the Metrics page computes from (read only). Sent touches only. Test leads, their touches and test runs' cost rows are dropped unless includeTest. */
export async function loadMetricsData(includeTest = false): Promise<{ leads: LeadRow[]; touches: TouchRow[]; costs: CostDay[]; runs: RunRow[] }> {
  const [leads, touches, rawCosts, runs] = await Promise.all([
    fetchAll<LeadRow>((f, t) => supabase.from("leads").select(LEAD_SELECT).order("id").range(f, t)),
    fetchAll<TouchRow>((f, t) => supabase.from("touches").select("lead_id,touch_no,status,sent_at,outcome,outcome_at").eq("status", "sent")
      .order("lead_id").order("touch_no").order("id").range(f, t)),
    fetchAll<CostDay>((f, t) => supabase.from("cost_daily").select("day,provider,run_id,units,usd").order("day").order("provider").order("run_id").range(f, t)),
    fetchAll<RunRow>((f, t) => supabase.from("batches").select("id,name,created_at").order("id").range(f, t)),
  ]);
  // PostgREST returns numeric as strings.
  const costs = rawCosts.map((c) => ({ ...c, units: Number(c.units) || 0, usd: Number(c.usd) || 0 }));
  if (includeTest) return { leads, touches, costs, runs };
  const real = leads.filter((l) => !isTestLead(l.place_id));
  const ids = new Set(real.map((l) => l.id));
  return { leads: real, touches: touches.filter((t) => ids.has(t.lead_id)), costs: dropTestRuns(costs, runs), runs };
}
