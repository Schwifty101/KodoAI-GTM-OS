"""Median/max round-trip ms for a trivial read. Run: uv run python -m scripts.measure_db_latency (Mac, then VM)."""
import statistics
import time

from gtm.db import get_db

db = get_db()
ms = []
for _ in range(20):
    t = time.perf_counter()
    db.table("batches").select("id").limit(1).execute()
    ms.append((time.perf_counter() - t) * 1000)
print(f"median {statistics.median(ms):.0f} ms, max {max(ms):.0f} ms (n={len(ms)})")
