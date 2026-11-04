"use client";

/**
 * The extraction ledger — what has already been handed out.
 *
 * This screen is the other half of the Extract button. The mark is only useful
 * if it can be inspected and undone: an operator who pulled 30 rows and never
 * sent them needs those businesses back in the queue, and one who is about to
 * send needs to see what went out last time.
 *
 * Two honesty constraints:
 *
 *   - The numbers shown are the ones **stored at pull time**, not a live read of
 *     the business's contacts. A later run raising a number's §9.3 evidence must
 *     not rewrite the record of a message that has already been sent.
 *   - Clearing is not §15. It retracts "already sent" and nothing else — no
 *     business row, no contact, no `do_not_contact` entry is touched. That is
 *     said on screen, because "clear" next to a delete button that *does* write
 *     a permanent suppression is exactly the confusion worth pre-empting.
 *
 * The batch filter is the third: "what did I already send the Commission Escape
 * message to?" is the question that decides what today's pull can say, and it
 * has to be answerable per run and per batch. It matches on the batch **recorded
 * at pull time**, so a business that has since gained a website still appears
 * under the batch it was actually messaged in.
 *
 * Selection is re-copying, not re-extracting. The ledger's rows are already
 * marked; ticking some of them and copying only those numbers is how an operator
 * resumes a send that stopped halfway, or re-sends to a subset, without pulling
 * anything new. It writes nothing — no mark, no clear, no suppression.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  copyToClipboard,
  type BatchCatalogue,
  type ExtractionEntry,
  type RunSummary,
} from "@/lib/api";

export default function ExtractedScreen() {
  const [entries, setEntries] = useState<ExtractionEntry[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [catalogue, setCatalogue] = useState<BatchCatalogue | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [runFilter, setRunFilter] = useState<string>("");
  const [batchFilter, setBatchFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // The row a shift-click extends *from*, as an index into the list as
  // rendered — "everything between these two rows" is a statement about what is
  // on screen, and the screen is what the operator is reading.
  const anchor = useRef<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const runIds = runFilter ? [runFilter] : [];
    api
      .extractions(runIds, batchFilter ? [batchFilter] : [])
      .then((rows) => {
        setEntries(rows);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
    // Unscoped by batch on purpose: these are what the filter is choosing
    // between, so narrowing them would leave every option but one reading 0.
    api.extractionCounts(runIds).then(setCounts).catch(() => setCounts({}));
  }, [runFilter, batchFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    api.listRuns().then(setRuns).catch((e) => setError(String(e)));
    api.batches().then(setCatalogue).catch((e) => setError(String(e)));
  }, []);

  // A filter change, a clear or a reload replaces the list. Ids that are no
  // longer on it must not stay selected, or "copy 12 selected" would put numbers
  // on the clipboard from rows the operator can no longer see.
  useEffect(() => {
    anchor.current = null;
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const live = new Set(entries.map((e) => e.id));
      const next = new Set([...prev].filter((id) => live.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [entries]);

  /**
   * Tick one row, or — holding shift — every row between it and the last one
   * ticked. The whole range takes the clicked box's new state, so shift-clicking
   * a ticked row clears the span as readily as it fills one.
   */
  const toggleRow = useCallback(
    (index: number, checked: boolean, extend: boolean) => {
      setSelected((prev) => {
        const next = new Set(prev);
        const from = extend && anchor.current !== null ? anchor.current : index;
        const [lo, hi] = from <= index ? [from, index] : [index, from];
        for (let i = lo; i <= hi; i += 1) {
          const id = entries[i]?.id;
          if (!id) continue;
          if (checked) next.add(id);
          else next.delete(id);
        }
        return next;
      });
      // The anchor follows the row actually clicked, shift or not, so a second
      // shift-click extends from there rather than from the first row ever
      // touched.
      anchor.current = index;
    },
    [entries],
  );

  const numbers = useMemo(
    () => [...new Set(entries.flatMap((e) => e.numbers))],
    [entries],
  );
  // Selected rows in listed order, deduped the same way `numbers` is: two
  // businesses sharing a landline are one paste, not two.
  const selectedNumbers = useMemo(
    () => [
      ...new Set(
        entries.filter((e) => selected.has(e.id)).flatMap((e) => e.numbers),
      ),
    ],
    [entries, selected],
  );
  const allSelected = entries.length > 0 && selected.size === entries.length;
  const total = useMemo(
    () => Object.values(counts).reduce((sum, n) => sum + n, 0),
    [counts],
  );

  async function copyNumbers(list: string[], what: string) {
    setNotice(
      (await copyToClipboard(list.join("\n")))
        ? `Copied ${list.length} ${what} number(s).`
        : "The browser refused the clipboard.",
    );
  }

  async function clearOne(entry: ExtractionEntry) {
    try {
      await api.clearExtraction(entry.id);
      setNotice(
        `${entry.business_name ?? "That business"} is back in the queue — the ` +
          "next Extract can offer it again. Nothing else changed.",
      );
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  async function clearAll() {
    // Names both scopes, because the button clears exactly what is listed — a
    // clear that quietly ignored the batch filter would retract 130 sends from a
    // screen showing 22.
    const batchName = batchFilter
      ? (catalogue?.batches.find((b) => b.slug === batchFilter)?.name ??
        "unbatched")
      : null;
    const scope = [
      batchName ? `the ${batchName} batch of` : null,
      runFilter ? "this run's extracted list" : "the whole extracted list",
    ]
      .filter(Boolean)
      .join(" ");

    if (
      !window.confirm(
        `Clear ${scope} (${entries.length} entr${entries.length === 1 ? "y" : "ies"})?\n\n` +
          "Every one of these businesses becomes extractable again. No business, " +
          "contact or §15 suppression is deleted — this only retracts the " +
          '"already sent" mark.',
      )
    ) {
      return;
    }
    try {
      const result = await api.clearExtractions(
        runFilter ? [runFilter] : [],
        batchFilter ? [batchFilter] : [],
      );
      setNotice(`Cleared ${result.cleared} entr${result.cleared === 1 ? "y" : "ies"}.`);
      load();
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <>
      <h1>Extracted</h1>
      <p className="subtitle">
        Businesses already pulled for outreach. Clearing one puts it back in the
        queue — it is not a §15 suppression. Tick rows (shift-click for a range)
        to re-copy just those numbers.
      </p>

      {error && <div className="notice bad">{error}</div>}
      {notice && <div className="notice info">{notice}</div>}

      <div className="panel">
        <div className="row">
          <div className="field" style={{ flex: "2 1 320px" }}>
            <label>Run</label>
            <select value={runFilter} onChange={(e) => setRunFilter(e.target.value)}>
              <option value="">every run</option>
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.city} × {r.category} · {r.businesses} businesses
                </option>
              ))}
            </select>
          </div>
          <div
            className="field"
            style={{ flex: "1 1 300px" }}
            title="Matches the batch recorded when the pull happened, so a business that has moved batch since still appears under the message it actually got."
          >
            <label>Outreach batch</label>
            <select
              value={batchFilter}
              onChange={(e) => setBatchFilter(e.target.value)}
            >
              <option value="">every batch — {total} extracted</option>
              {(catalogue?.batches ?? []).map((b) => (
                <option key={b.slug} value={b.slug}>
                  {b.id} · {b.name} — {counts[b.slug] ?? 0}
                </option>
              ))}
              {catalogue && (
                <option value={catalogue.unbatched_slug}>
                  no batch defined — {counts[catalogue.unbatched_slug] ?? 0}
                </option>
              )}
            </select>
          </div>
        </div>
      </div>

      <div className="toolbar">
        <b>{entries.length}</b>
        <span className="muted">
          extracted{loading && " · loading…"} · {numbers.length} distinct number(s)
        </span>
        {selected.size > 0 && (
          <>
            <span className="badge likely">
              {selected.size} selected · {selectedNumbers.length} number(s)
            </span>
            {/* "Deselect", never "clear" — on this screen clear is the word for
                retracting a send, and the two must not blur together. */}
            <button className="small" onClick={() => setSelected(new Set())}>
              Deselect all
            </button>
          </>
        )}
        <span className="spacer" />
        <Link href="/results">
          <button>Back to results</button>
        </Link>
        {/* Two buttons rather than one that changes meaning: "copy" landing on a
            subset because three rows happened to be ticked is the kind of
            surprise that gets the wrong list messaged. */}
        {selected.size > 0 && (
          <button
            className="primary"
            onClick={() => copyNumbers(selectedNumbers, "selected")}
            disabled={selectedNumbers.length === 0}
            title="Only the numbers on the ticked rows, as they were sent"
          >
            Copy {selectedNumbers.length} selected
          </button>
        )}
        <button
          onClick={() => copyNumbers(numbers, "listed")}
          disabled={numbers.length === 0}
          title="Re-copy every number in this list, as it was sent"
        >
          Copy all numbers
        </button>
        <button className="danger" onClick={clearAll} disabled={entries.length === 0}>
          Clear {entries.length} listed
        </button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 28 }}>
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = selected.size > 0 && !allSelected;
                  }}
                  onChange={(e) => {
                    anchor.current = null;
                    setSelected(
                      e.target.checked ? new Set(entries.map((x) => x.id)) : new Set(),
                    );
                  }}
                  disabled={entries.length === 0}
                  title="Select every row listed"
                />
              </th>
              <th>business</th>
              <th>batch</th>
              <th>city</th>
              <th className="num">score</th>
              <th>website</th>
              <th>numbers sent</th>
              <th>extracted_at</th>
              <th>pull</th>
              <th style={{ width: 70 }} />
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr
                key={entry.id}
                className={selected.has(entry.id) ? "selected" : ""}
              >
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(entry.id)}
                    onChange={(e) =>
                      toggleRow(
                        index,
                        e.target.checked,
                        // The change came from a click on the box, so the native
                        // event is the MouseEvent that carries the modifier. A
                        // keyboard toggle has no shiftKey and reads as false,
                        // which is the right answer for it.
                        (e.nativeEvent as MouseEvent).shiftKey === true,
                      )
                    }
                    title="Click to select · shift-click to select the range from the last row you clicked"
                  />
                </td>
                <td>{entry.business_name ?? <span className="muted">—</span>}</td>
                <td className="small">
                  <LedgerBatch entry={entry} catalogue={catalogue} />
                </td>
                <td>{entry.city ?? <span className="muted">—</span>}</td>
                <td className="num mono">
                  {entry.lead_score ?? <span className="muted">—</span>}
                </td>
                <td>
                  {entry.website ? (
                    <a href={entry.website} target="_blank" rel="noreferrer">
                      {entry.website.replace(/^https?:\/\//, "").slice(0, 30)}
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="mono small">
                  {/* Blank, not 0 — a business can be extracted having had no
                      confirmed or likely number, and the batch count says so. */}
                  {entry.numbers.length ? (
                    entry.numbers.join(" · ")
                  ) : (
                    <span className="muted">no qualifying number</span>
                  )}
                </td>
                <td className="small mono muted">
                  {entry.extracted_at?.slice(0, 19).replace("T", " ") ?? "—"}
                </td>
                <td className="small muted">
                  {/* NULL batch_size is an "extract all" pull, not a missing
                      value — the size was "everything that was left". */}
                  {entry.batch_size ? `top ${entry.batch_size}` : "all"}
                </td>
                <td style={{ textAlign: "right" }}>
                  <button
                    className="small"
                    onClick={() => clearOne(entry)}
                    title="Put this business back in the queue. Deletes nothing else."
                  >
                    Clear
                  </button>
                </td>
              </tr>
            ))}
            {entries.length === 0 && !loading && (
              <tr>
                <td colSpan={10}>
                  <span className="muted">
                    {batchFilter
                      ? "Nothing from this batch has been extracted yet."
                      : "Nothing extracted yet."}{" "}
                    Use <b>Extract</b> on the results table to pull the top 30, 50
                    or 100 — or all of it — of whatever is filtered there.
                  </span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

/**
 * Which batch this business was messaged in.
 *
 * Two facts, and the difference between them matters. `batch` is what was
 * recorded at pull time — the message that actually went out. `current_batch` is
 * where the cascade puts the business today. They diverge when a later run finds
 * a website or the review count crosses 200, and a follow-up that assumed the
 * current batch would repeat the wrong pitch. So the recorded one is what is
 * shown, and a move is flagged rather than smoothed over.
 *
 * A row pulled before the column existed has no recorded batch at all; it falls
 * back to the current one and says so, because inventing history for it would be
 * worse than admitting we did not record it.
 */
function LedgerBatch({
  entry,
  catalogue,
}: {
  entry: ExtractionEntry;
  catalogue: BatchCatalogue | null;
}) {
  const slug = entry.batch ?? entry.current_batch;
  const spec = catalogue?.batches.find((b) => b.slug === slug);
  const moved =
    entry.batch && entry.current_batch && entry.batch !== entry.current_batch;
  const movedTo = catalogue?.batches.find((b) => b.slug === entry.current_batch);

  if (!spec) {
    return (
      <span className="muted" title="The cascade has no definitions for this category.">
        —
      </span>
    );
  }
  return (
    <>
      <span
        className="badge likely"
        title={
          entry.batch
            ? `${spec.name} — recorded when this pull happened.`
            : `${spec.name} — derived now: this row was pulled before the batch was recorded.`
        }
      >
        {spec.id}
        {!entry.batch && <span className="muted"> ?</span>}
      </span>
      {moved && (
        <span
          className="muted small"
          title="This business has moved batch since it was messaged — a later run changed one of the cascade's inputs. The message it got was the one above."
        >
          {" "}
          → {movedTo?.id ?? entry.current_batch}
        </span>
      )}
    </>
  );
}
