import { supabase } from "./supabase";
import { fetchAll } from "./fetchAll";
import { BATCH_SIZE, batchBase, loadOutreachBatches } from "./batches";
import { dayRange, type HomeCounts } from "./home";
import { dropTestRuns, isOwner, isTestLead, spendFrom, type CostDay, type RunRow, type Spend } from "./metrics";
import { replyBucket } from "./replies";
import { settingDefaults } from "./settings";

export type HomeData = {
  yesterday: { scraped: number; owners: number; numbered: number; touch1: number; followups: number };
  counts: HomeCounts; monthSpend: Spend; geminiSince: number; autopilot: string;
};

type Page<T> = PromiseLike<{ data: T[] | null; error: { message: string } | null }>;
type Lead = { place_id: string };
type Joined = { touch_no: number; leads: Lead }; // the embedded lead of a touch is one row, not a list
const KEYS = ["sending_on", "batch_base", "credit_balance_as_of", "autopilot_state"];

/**
 * Spec 7.5: everything Home shows, read once per visit. "Yesterday" is the browser's previous local calendar day (dayRange);
 * the month and the Google credit run in UTC like cost_daily. includeTest keeps TEST_ and REHEARSAL_ leads and test runs.
 * cost_daily and touches.outcome_at need migration 0017: callers pass the error through hint0017.
 * ponytail: the open batch comes from loadOutreachBatches, which does not see place_id, so a test lead holding a batch number would count; rehearsal rows keep batch_no null.
 */
export async function loadHome(now: Date, includeTest = false): Promise<HomeData> {
  const st = await supabase.from("settings").select("key,value").in("key", KEYS);
  if (st.error) throw new Error(st.error.message);
  const set: Record<string, unknown> = { ...settingDefaults(), ...Object.fromEntries((st.data ?? []).map((r) => [r.key, r.value])) };
  const keep = (placeId: string) => includeTest || !isTestLead(placeId);
  const sendingOn = set.sending_on === true;
  const { from, to } = dayRange(now, 1);
  const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString().slice(0, 10);
  const asOf = String(set.credit_balance_as_of).slice(0, 10);
  const since = asOf < monthStart ? asOf : monthStart;
  const touches = (statuses: string[]) => fetchAll<Joined>((a, b) =>
    supabase.from("touches").select("touch_no,leads!inner(place_id)").in("status", statuses).order("id").range(a, b) as unknown as Page<Joined>);

  const [yLeads, ySent, selected, drafted, queued, replied, mb, batches, costs, runs] = await Promise.all([
    fetchAll<Lead & { owner_email: string | null; email_verified: boolean | null; batch_no: number | null }>((a, b) =>
      supabase.from("leads").select("place_id,owner_email,email_verified,batch_no").gte("created_at", from).lt("created_at", to).order("id").range(a, b)),
    fetchAll<Joined>((a, b) =>
      supabase.from("touches").select("touch_no,leads!inner(place_id)").eq("status", "sent").gte("sent_at", from).lt("sent_at", to).order("id").range(a, b) as unknown as Page<Joined>),
    fetchAll<Lead>((c, d) => supabase.from("leads").select("place_id").eq("status", "selected").eq("approved", false).order("id").range(c, d)),
    touches(["drafted"]),
    sendingOn ? Promise.resolve([] as Joined[]) : touches(["approved", "scheduled"]),
    fetchAll<{ lead_id: string; touch_no: number; outcome: string | null; leads: Lead }>((a, b) =>
      supabase.from("touches").select("lead_id,touch_no,outcome,leads!inner(place_id,status)").eq("status", "sent").eq("leads.status", "replied").order("id").range(a, b) as unknown as Page<{ lead_id: string; touch_no: number; outcome: string | null; leads: Lead }>),
    supabase.from("mailboxes").select("id,paused_reason").eq("paused", true).order("id").limit(1),
    loadOutreachBatches(batchBase(set.batch_base)),
    fetchAll<CostDay>((a, b) => supabase.from("cost_daily").select("day,provider,run_id,units,usd").gte("day", since).order("day").order("provider").order("run_id").range(a, b)),
    includeTest ? Promise.resolve([] as RunRow[]) : fetchAll<RunRow>((a, b) => supabase.from("batches").select("id,name,created_at").order("id").range(a, b)),
  ]);
  if (mb.error) throw new Error(mb.error.message);

  const sent = ySent.filter((t) => keep(t.leads.place_id));
  const ls = yLeads.filter((l) => keep(l.place_id));
  const last = new Map<string, (typeof replied)[number]>(); // each replied lead's last sent touch decides its bucket
  for (const t of replied) if (keep(t.leads.place_id) && t.touch_no > (last.get(t.lead_id)?.touch_no ?? 0)) last.set(t.lead_id, t);
  const open = batches.find((r) => r.leads < BATCH_SIZE);
  const cd = dropTestRuns(costs.map((c) => ({ ...c, units: Number(c.units), usd: Number(c.usd) })), runs); // runs is empty when includeTest

  return {
    yesterday: {
      scraped: ls.length, owners: ls.filter(isOwner).length, numbered: ls.filter((l) => l.batch_no !== null).length,
      touch1: sent.filter((t) => t.touch_no === 1).length, followups: sent.filter((t) => t.touch_no > 1).length,
    },
    counts: {
      selectedUnapproved: selected.filter((l) => keep(l.place_id)).length,
      draftsWaiting: drafted.filter((t) => t.touch_no === 1 && keep(t.leads.place_id)).length,
      followupsDrafted: drafted.filter((t) => t.touch_no > 1 && keep(t.leads.place_id)).length,
      approvedWhileOff: queued.filter((t) => keep(t.leads.place_id)).length,
      replies: [...last.values()].filter((t) => replyBucket("replied", t.outcome) === "look").length,
      mailboxPaused: mb.data?.[0] ? (mb.data[0].paused_reason ?? "") : null, // "" = paused with no reason; nextAction prints just "Mailbox paused"
      batch: open ? { no: open.batch_no, fill: open.leads } : null,
    },
    monthSpend: spendFrom(cd.filter((c) => c.day >= monthStart)),
    geminiSince: cd.filter((c) => c.provider === "gemini" && c.day >= asOf).reduce((s, c) => s + c.usd, 0),
    autopilot: String(set.autopilot_state ?? "off"),
  };
}
