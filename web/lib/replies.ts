// Replies page logic (spec 2026-11-26-plan6-metrics-design.md 7.6). Pure: no supabase import.

export type ReplyBucket = "look" | "positive" | "booked" | "declined" | "bounced";

/** Which Replies section a lead belongs in, from its status and its latest touch outcome; null when it is not a reply. */
export function replyBucket(status: string, outcome: string | null): ReplyBucket | null {
  if (status === "booked") return "booked";
  if (status === "bounced" || outcome === "bounce") return "bounced";
  if (status === "unsubscribed" || outcome === "negative" || outcome === "opt_out") return "declined";
  if (status !== "replied") return null;
  return outcome === "positive" ? "positive" : outcome === null || outcome === "other" ? "look" : null;
}

/** Unverified format until the browser run (spec 7.6). */
export const gmailThreadUrl = (address: string, threadId: string) => `https://mail.google.com/mail/?authuser=${encodeURIComponent(address)}#all/${threadId}`;
