"""`gtm worker`: runs queued jobs one at a time by calling the same CLI passes."""
import contextlib
import io
import time

from gtm.budget import BudgetExceeded
from gtm.db import get_db
from gtm.jobs import claim, finish, requeue_stale

ALLOWED = {"scrape", "clean", "enrich", "signals", "select", "draft", "followups", "replies"}  # send is not job-runnable until Plan 4


def _run_pass(kind: str, argv: list[str]) -> str:
    from gtm.cli import build_parser  # cli imports worker for the `worker` command

    a = build_parser().parse_args([kind, *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        a.fn(a)
    return out.getvalue()


def run_one(db, run_pass=_run_pass) -> str | None:
    job = claim(db)
    if not job:
        return None
    try:
        if job["kind"] not in ALLOWED:
            raise ValueError(f"job kind {job['kind']!r} cannot be run by the worker")
        out = run_pass(job["kind"], job["payload"].get("argv", []))
        finish(db, job["id"], "done", {"output": out[-4000:]})
    except BudgetExceeded as e:
        finish(db, job["id"], "paused_budget", error=str(e))
    except SystemExit as e:
        finish(db, job["id"], "failed", error=f"exited: {e.code}")
    except Exception as e:
        finish(db, job["id"], "failed", error=f"{type(e).__name__}: {e}")
    return job["id"]


def main(poll_seconds: int = 15) -> None:
    db, last_sweep = get_db(), 0.0
    try:
        while True:
            if time.monotonic() - last_sweep > 3600:
                requeue_stale(db)
                last_sweep = time.monotonic()
            if not run_one(db):
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        pass
