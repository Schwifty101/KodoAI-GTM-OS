export const STATUSES = [
  "scraped", "cleaned", "rejected", "enriched", "no_buyer", "signalled", "selected",
  "drafted", "sent", "replied", "booked", "bounced", "suppressed", "unsubscribed",
] as const;
export const VECTORS = ["conversion_recovery", "capacity", "rebooking_retention"] as const;

export type Evidence = { text: string; url: string; quote: string; date?: string };
export type SignalRecord = {
  current_signal: Evidence | null;
  relevant_handoff: Evidence | null;
  likely_objective?: string | null;
  reason_to_respond?: string | null;
  platform?: string | null;
  judged_on?: string;
};

export type Lead = {
  id: string;
  name: string;
  city: string | null;
  state: string | null;
  domain: string | null;
  website: string | null;
  status: string;
  vector: string | null;
  signal_led: boolean;
  approved: boolean;
  owner_name: string | null;
  owner_title: string | null;
  owner_email: string | null;
  email_source: string | null;
  select_reason: string | null;
  reject_reason: string | null;
  rating: number | null;
  review_count: number | null;
  signal: SignalRecord | null;
  batch_id: string | null;
  created_at: string;
  batches: { name: string } | null;
};

export const LEAD_COLUMNS =
  "id,name,city,state,domain,website,status,vector,signal_led,approved,owner_name,owner_title,owner_email,email_source,select_reason,reject_reason,rating,review_count,signal,batch_id,created_at,batches(name)";

export type Mailbox = { id: string; address: string; daily_cap: number; enabled_on: string | null; paused: boolean; paused_reason: string | null };
export type Touch = {
  id: string; lead_id: string; touch_no: number; status: string; subject: string | null; body: string | null;
  scheduled_for: string | null; sent_at: string | null; outcome: string | null;
  leads: { name: string; owner_email: string | null; status: string; mailbox_id: string | null } | null;
};
