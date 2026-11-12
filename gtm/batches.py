"""Selected leads are numbered into batches of 100. A lead's number is fixed once assigned."""
from collections import Counter

from gtm.db import fetch_all

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


def assign_batches(db) -> int:
    new = fetch_all(lambda: db.table("leads").select("id").eq("status", "selected").is_("batch_no", "null").order("created_at").order("id"))
    if not new:
        return 0
    counts = Counter(r["batch_no"] for r in fetch_all(lambda: db.table("leads").select("id,batch_no").not_.is_("batch_no", "null").order("id")))
    for r, no in zip(new, plan_numbers(dict(counts), len(new))):
        db.table("leads").update({"batch_no": no}).eq("id", r["id"]).execute()
    return len(new)  # ponytail: two concurrent selects could race on the same batch; one worker runs selects serially
