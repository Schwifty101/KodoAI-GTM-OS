from datetime import datetime, timedelta, timezone

from conftest import is_junk_batch

T0 = datetime(2026, 11, 17, tzinfo=timezone.utc)
NOW = (T0 + timedelta(minutes=5)).isoformat()


def test_only_empty_in_session_test_named_batches_are_junk():
    assert is_junk_batch({"name": "A TX 2026-11-17", "created_at": NOW}, False, T0)
    assert is_junk_batch({"name": "REHEARSAL_FA_x", "created_at": NOW}, False, T0)
    assert not is_junk_batch({"name": "Houston TX 2026-11-17", "created_at": NOW}, False, T0)
    assert not is_junk_batch({"name": "A TX 2026-11-17", "created_at": NOW}, True, T0)  # has a lead
    assert not is_junk_batch({"name": "A TX 2026-11-17", "created_at": (T0 - timedelta(days=1)).isoformat()}, False, T0)  # older than session
