"""`gtm worker`: runs queued jobs one at a time by calling the same CLI passes."""
import contextlib
import io
import signal
import threading
import time

from gtm.budget import BudgetExceeded
from gtm.db import get_db
from gtm.jobs import claim, finish, heartbeat, requeue_stale
from gtm.schedule import tick

ALLOWED = {"scrape", "clean", "enrich", "signals", "select", "draft", "followups", "replies", "walk"}  # send is not job-runnable until Plan 4
BEAT_SECONDS = 30.0


@contextlib.contextmanager
def beating(db, job_id: str, every: float | None = None):
    """Heartbeat the job from a daemon thread while the block runs."""
    stop = threading.Event()

    def loop():
        while not stop.wait(every or BEAT_SECONDS):
            heartbeat(db, job_id)

    threading.Thread(target=loop, daemon=True).start()
    try:
        yield
    finally:
        stop.set()


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
        with beating(db, job["id"]):
            out = run_pass(job["kind"], job["payload"].get("argv", []))
        finish(db, job["id"], "done", {"output": out[-4000:]})
    except KeyboardInterrupt:
        finish(db, job["id"], "cancelled", error="interrupted")
        raise
    except BudgetExceeded as e:
        finish(db, job["id"], "paused_budget", error=str(e))
    except SystemExit as e:
        finish(db, job["id"], "failed", error=f"exited: {e.code}")
    except Exception as e:
        finish(db, job["id"], "failed", error=f"{type(e).__name__}: {e}")
    return job["id"]


def main(poll_seconds: int = 15) -> None:
    db, last_sweep = get_db(), float("-inf")
    # ponytail: heartbeat and stale cutoff both use the worker clock; a skewed VM clock of minutes would mis-stale jobs, use DB now() if that ever bites
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # systemd stop cancels the job via KeyboardInterrupt
    try:
        while True:
            if time.monotonic() - last_sweep > 300:
                requeue_stale(db)
                last_sweep = time.monotonic()
            try:
                tick(db)
            except Exception as e:  # a schedule error must never stop the loop
                print(f"schedule tick failed: {type(e).__name__}: {e}")
            if not run_one(db):
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        pass
