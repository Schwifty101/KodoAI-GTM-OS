from contextlib import contextmanager
from contextvars import ContextVar

from gtm.db import get_db

_ctx: ContextVar[dict] = ContextVar("spend_context", default={})


@contextmanager
def spend_context(batch_id: str | None = None, lead_id: str | None = None):
    """Paid calls made inside inherit this batch and lead; nested contexts merge."""
    token = _ctx.set({**_ctx.get(), **{k: v for k, v in (("batch_id", batch_id), ("lead_id", lead_id)) if v is not None}})
    try:
        yield
    finally:
        _ctx.reset(token)


def log_cost(
    provider: str,
    units: float,
    usd: float | None,
    batch_id: str | None = None,
    lead_id: str | None = None,
    note: str = "",
) -> None:
    ctx = _ctx.get()
    get_db().table("cost_log").insert(
        {"provider": provider, "units": units, "usd": usd, "batch_id": batch_id or ctx.get("batch_id"), "lead_id": lead_id or ctx.get("lead_id"), "note": note}
    ).execute()
