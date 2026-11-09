from gtm.db import get_db


def log_cost(
    provider: str,
    units: float,
    usd: float | None,
    batch_id: str | None = None,
    lead_id: str | None = None,
    note: str = "",
) -> None:
    get_db().table("cost_log").insert(
        {"provider": provider, "units": units, "usd": usd, "batch_id": batch_id, "lead_id": lead_id, "note": note}
    ).execute()
