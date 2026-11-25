"""Selected leads are numbered into batches of 100. A lead's number is fixed once assigned."""
from collections import Counter

from gtm.db import fetch_all
from gtm.settings_store import setting

BATCH_SIZE = 100


def plan_numbers(counts: dict[int, int], n_new: int, size: int = BATCH_SIZE) -> list[int]:
    """Batch number for each of n_new new leads: top up the highest batch first, then open the next numbers."""
    no = max(counts, default=1)
    used = counts.get(no, 0)
    out = []
    for _ in range(n_new):
        if used >= size:
            no, used = no + 1, 0
        out.append(no)
        used += 1
    return out


def assign_batches(db, lead_ids: list[str] | None = None) -> int:
    """Number selected leads without a batch; lead_ids limits the candidates (default: all)."""
    if lead_ids is not None and not lead_ids:
        return 0
    def cand():
        q = db.table("leads").select("id").eq("status", "selected").is_("batch_no", "null")
        return (q if lead_ids is None else q.in_("id", lead_ids)).order("created_at").order("id")
    new = fetch_all(cand)
    if not new:
        return 0
    counts = Counter(r["batch_no"] for r in fetch_all(lambda: db.table("leads").select("id,batch_no").not_.is_("batch_no", "null").order("id")))
    for k, v in setting("batch_base", db).items():  # leads already in a batch outside the OS
        counts[int(k)] += v
    for r, no in zip(new, plan_numbers(dict(counts), len(new))):
        db.table("leads").update({"batch_no": no}).eq("id", r["id"]).execute()
    return len(new)  # ponytail: two concurrent selects could race on the same batch; one worker runs selects serially


def renumber(db, old: int, new: int, confirm: bool = False, include_drafted: bool = False) -> int:
    """Move selected (and, with include_drafted, drafted) leads from batch old to new; returns how many match (moved only with confirm). Refuses to overfill batch new."""
    ids = [r["id"] for r in fetch_all(lambda: db.table("leads").select("id").eq("batch_no", old).in_("status", ["selected", "drafted"] if include_drafted else ["selected"]).order("id"))]
    there = len(fetch_all(lambda: db.table("leads").select("id").eq("batch_no", new).order("id")))
    total = there + setting("batch_base", db).get(str(new), 0) + len(ids)
    if total > BATCH_SIZE:
        raise ValueError(f"batch {new} would hold {total} leads (max {BATCH_SIZE}): nothing moved")
    if confirm and ids:
        db.table("leads").update({"batch_no": new}).in_("id", ids).execute()
    return len(ids)
