import type { Lead } from "@/lib/types";

/** The proof behind a lead: what was observed, where, and the exact quote. Shown next to every model summary. */
export function Evidence({ lead }: { lead: Lead }) {
  const s = lead.signal;
  if (!s) return <p className="muted">No signal pass has run for this lead.</p>;
  const item = (label: string, e: SignalItem) =>
    e ? (
      <div className="evidence">
        <strong>{label}</strong>
        <div>{e.text}{e.date ? ` (${e.date})` : ""}</div>
        <blockquote>“{e.quote}”</blockquote>
        <a href={e.url} target="_blank" rel="noreferrer">{e.url}</a>
      </div>
    ) : (
      <div className="evidence"><strong>{label}</strong> <span className="muted">none observed</span></div>
    );
  return (
    <div>
      {item("Current signal", s.current_signal)}
      {item("Relevant handoff", s.relevant_handoff)}
      {s.likely_objective && <p><strong>Likely objective</strong> (inference): {s.likely_objective}</p>}
      {s.reason_to_respond && <p><strong>Reason to respond</strong>: {s.reason_to_respond}</p>}
      {s.platform && s.platform !== "none" && <p><strong>Booking platform seen</strong>: {s.platform}</p>}
    </div>
  );
}
type SignalItem = NonNullable<Lead["signal"]>["current_signal"];
