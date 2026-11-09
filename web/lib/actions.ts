import { supabase } from "./supabase";

// Every operator write goes through here so scripts/verify.ts can exercise the exact same calls under RLS.
async function ok<T extends { error: { message: string } | null }>(p: PromiseLike<T>): Promise<void> {
  const { error } = await p;
  if (error) throw new Error(error.message);
}

/** Approve = ready for the draft pass. Only leads still `selected` are touched. */
export const approveLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ approved: true }).in("id", ids).eq("status", "selected"));

export const unapproveLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ approved: false }).in("id", ids).eq("status", "selected"));

/** Reject = out of the pipeline, with the operator recorded as the reason. */
export const rejectLeads = (ids: string[]) =>
  ok(supabase.from("leads").update({ status: "rejected", reject_reason: "operator", approved: false }).in("id", ids).eq("status", "selected"));
