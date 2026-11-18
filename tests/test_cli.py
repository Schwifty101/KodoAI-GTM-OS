import argparse

import pytest

from gtm import budget, cli


def test_blocked_scrape_creates_no_batch(monkeypatch):
    def blocked(*a, **k):
        raise budget.BudgetExceeded("cap")

    monkeypatch.setattr(budget, "require", blocked)
    monkeypatch.setattr(cli, "get_db", lambda: pytest.fail("db touched"))
    monkeypatch.setattr(cli, "new_batch", lambda *a, **k: pytest.fail("batch created"))
    a = argparse.Namespace(query=None, max_places=5, city="X", state="TX", max_usd=1.0)
    with pytest.raises(budget.BudgetExceeded):
        cli.cmd_scrape(a)


@pytest.mark.parametrize("command", ["replies", "followups", "send"])
def test_reply_checks_use_reply_model(monkeypatch, command):
    db = object()
    seen = []
    monkeypatch.setattr(cli, "get_db", lambda: db)
    monkeypatch.setattr(cli, "get_settings", lambda: object())
    monkeypatch.setattr(cli, "run_replies", lambda db, gmail, llm: seen.append(llm))
    monkeypatch.setattr(cli, "run_followups", lambda *args: 0)
    monkeypatch.setattr(cli, "send_tick", lambda db, gmail, llm, *args, **kw: seen.append(llm))
    getattr(cli, f"cmd_{command}")(argparse.Namespace(confirm=True, anytime=False))
    assert seen == [cli.complete_reply_json]


def test_cmd_send_dry_run_writes_nothing(monkeypatch, capsys):
    class Db:  # any write (update/insert) would be an AttributeError
        def table(self, name):
            return self

        def select(self, *a):
            return self

        def execute(self):
            return argparse.Namespace(data=[{"id": "m", "address": "a@x", "paused": False, "daily_cap": 40, "enabled_on": "2026-11-10"}])

    monkeypatch.setattr(cli, "get_db", lambda: Db())
    monkeypatch.setattr(cli, "get_settings", lambda: argparse.Namespace(ramp_start=20, ramp_step=3, daily_cap=40))
    monkeypatch.setattr(cli, "sending_days", lambda db, mid, d: 0)
    monkeypatch.setattr(cli, "send_tick", lambda *a, **k: pytest.fail("sent"))
    with pytest.raises(SystemExit):
        cli.cmd_send(argparse.Namespace(confirm=False, anytime=False))
    assert "allowance today=20" in capsys.readouterr().out


def test_mailbox_unpause_restarts_the_ramp(monkeypatch):
    """Unpausing clears the pause AND sets ramp_from to today (ramp restarts at 20; the bounce window forgets the old spike)."""
    from datetime import date

    seen = {}

    class Table:
        def update(self, v): seen["update"] = v; return self
        def eq(self, *a): seen["eq"] = a; return self
        def execute(self): return self

    class Db:
        def table(self, name): seen["table"] = name; return Table()

    monkeypatch.setattr(cli, "get_db", lambda: Db())
    cli.cmd_mailbox(argparse.Namespace(action="unpause", address="x@example.com"))
    assert seen["update"] == {"paused": False, "paused_reason": None, "ramp_from": date.today().isoformat()}
    assert seen["table"] == "mailboxes" and seen["eq"] == ("address", "x@example.com")


SHEET_CMDS = [["import-sheet"], ["verify-sheet", "--batch", "b1"], ["sheet-queue"], ["sheet-paint"]]


@pytest.mark.parametrize("argv", SHEET_CMDS)
def test_sheet_commands_parse_and_confirm_defaults_false(argv):
    assert cli.build_parser().parse_args(argv).confirm is False
    assert cli.build_parser().parse_args([*argv, "--confirm"]).confirm is True


@pytest.mark.parametrize("argv", [c for c in SHEET_CMDS if c[0] != "verify-sheet"])  # verify-sheet needs no sheet
def test_sheet_commands_refuse_when_sheet_id_empty(monkeypatch, argv):
    import gtm.settings_store as ss
    import gtm.sheet as sheet

    monkeypatch.setattr(ss, "setting", lambda key, db=None: "")
    monkeypatch.setattr(cli, "get_db", lambda: None)
    monkeypatch.setattr(sheet, "sheets_service", lambda: pytest.fail("built a Sheets service"))
    with pytest.raises(SystemExit, match="sheet_id"):
        cli.main([*argv, "--confirm"])


@pytest.mark.parametrize("argv", [["import-sheet"], ["sheet-format"], ["sheet-queue"], ["sheet-paint"]])
def test_sheet_id_flag_overrides_setting(monkeypatch, argv):
    import gtm.settings_store as ss

    seen = []
    monkeypatch.setattr(ss, "setting", lambda key, db=None: True if key == "sheet_writeback_on" else "SETTINGID")
    monkeypatch.setattr(cli, "get_db", lambda: None)
    assert cli.build_parser().parse_args([*argv, "--sheet-id", "abc123xyz"]).sheet_id == "abc123xyz"
    assert cli._sheet_id(cli.build_parser().parse_args([*argv, "--sheet-id", "abc123xyz"])) == "abc123xyz"
    assert cli._sheet_id(cli.build_parser().parse_args(argv)) == "SETTINGID"


def test_sheet_format_passes_override_id_and_prints_only_six_chars(monkeypatch, capsys):
    import gtm.settings_store as ss
    import gtm.sheet as sheet
    import gtm.sheet_format as sf

    seen = {}
    monkeypatch.setattr(ss, "setting", lambda key, db=None: pytest.fail("read the setting"))
    monkeypatch.setattr(sheet, "sheets_service", lambda: object())
    monkeypatch.setattr(sf, "run_format", lambda svc, sid, **kw: seen.update(sid=sid, **kw))
    cli.main(["sheet-format", "--sheet-id", "abc123xyz", "--merge-only"])
    out = capsys.readouterr().out
    assert seen["sid"] == "abc123xyz" and seen["merge_only"] is True and "abc123" in out and "abc123xyz" not in out


def test_sheet_format_blocked_exits_1_without_traceback_or_extra_message(monkeypatch, capsys):
    import gtm.settings_store as ss
    import gtm.sheet as sheet
    import gtm.sheet_format as sf

    def boom(*a, **k):
        raise sf.Blocked("Utah: merged cells")
    monkeypatch.setattr(ss, "setting", lambda key, db=None: "SID123456")
    monkeypatch.setattr(sheet, "sheets_service", lambda: object())
    monkeypatch.setattr(sf, "run_format", boom)
    with pytest.raises(SystemExit) as e:
        cli.main(["sheet-format"])
    assert e.value.code == 1 and "merged cells" not in capsys.readouterr().err


def test_sheet_format_merge_flags_are_exclusive():
    p = cli.build_parser()
    assert p.parse_args(["sheet-format", "--merge-only"]).merge_only and p.parse_args(["sheet-format", "--no-merge"]).no_merge
    with pytest.raises(SystemExit):
        p.parse_args(["sheet-format", "--merge-only", "--no-merge"])


def test_verify_sheet_refuses_without_confirm(monkeypatch, capsys):
    import gtm.settings_store as ss
    import gtm.sheet_verify as sv

    import gtm.select as sel

    monkeypatch.setattr(sel, "_blocklists", lambda db: (set(), set()))
    monkeypatch.setattr(ss, "setting", lambda key, db=None: "sid")
    monkeypatch.setattr(cli, "HunterPool", lambda *a, **k: pytest.fail("built a pool"))
    monkeypatch.setattr(sv, "run_verify_sheet", lambda *a, **k: pytest.fail("verified"))

    class Q:
        data = [{"id": 1, "owner_name": "A B", "owner_title": "Owner"}, {"id": 2, "owner_name": "C D", "owner_title": "Founder"}]
        not_ = property(lambda self: self)

        def __getattr__(self, name):
            return lambda *a, **k: self

        def execute(self):
            return self

    class DB:
        def table(self, name):
            return Q()

    monkeypatch.setattr(cli, "get_db", lambda: DB())
    with pytest.raises(SystemExit, match="--confirm"):
        cli.main(["verify-sheet", "--batch", "b1"])
    assert "0.5 x 2" in capsys.readouterr().out


def test_verify_sheet_estimate_excludes_blocked_leads(monkeypatch, capsys):
    import gtm.select as sel
    import gtm.settings_store as ss

    monkeypatch.setattr(ss, "setting", lambda key, db=None: "sid")
    monkeypatch.setattr(sel, "_blocklists", lambda db: ({"bad.com"}, {"sent.com"}))

    class Q:
        o = {"owner_name": "A B", "owner_title": "Owner"}
        data = [{"id": 1, "owner_email": "a@bad.com", "domain": "bad.com", **o}, {"id": 2, "owner_email": "b@sent.com", **o},
                {"id": 3, "owner_email": "c@ok.com", "domain": "ok.com", **o},
                {"id": 4, "owner_email": "d@ok.com", "owner_name": None, "owner_title": "Owner"},  # skipped later: no owner
                {"id": 5, "owner_email": "e@ok.com", "owner_name": "E F", "owner_title": "Practice Manager"}]  # skipped: not a decision-maker
        not_ = property(lambda self: self)

        def __getattr__(self, name):
            return lambda *a, **k: self

        def execute(self):
            return self

    class DB:
        def table(self, name):
            return Q()

    monkeypatch.setattr(cli, "get_db", lambda: DB())
    with pytest.raises(SystemExit, match="--confirm"):
        cli.main(["verify-sheet", "--batch", "b1"])
    assert "0.5 x 1 = 0.5" in capsys.readouterr().out


def _import_env(monkeypatch):
    import gtm.settings_store as ss
    import gtm.sheet as sheet
    import gtm.sheet_import as si

    read = []
    monkeypatch.setattr(ss, "setting", lambda key, db=None: "sid")
    monkeypatch.setattr(cli, "get_db", lambda: None)
    monkeypatch.setattr(sheet, "sheets_service", lambda: object())
    monkeypatch.setattr(si, "read_tab", lambda svc, sid, tab: read.append(tab) or [])
    monkeypatch.setattr(si, "map_tab", lambda tab, rows: [])
    monkeypatch.setattr(si, "_load", lambda db: ([], [], {}))
    return read


def test_import_sheet_tab_limits_one_call_and_the_next_reads_all_tabs(monkeypatch):
    read = _import_env(monkeypatch)
    cli.main(["import-sheet", "--tab", "Texas"])
    assert read == ["Texas"]
    read.clear()
    cli.main(["import-sheet"])
    assert read == ["Utah", "Newyork", "Texas"]


def test_import_sheet_unknown_tab_exits_naming_it(monkeypatch):
    read = _import_env(monkeypatch)
    with pytest.raises(SystemExit, match="Nope"):
        cli.main(["import-sheet", "--tab", "Nope"])
    assert read == []


def test_sheet_paint_checks_writeback_switch_before_building_service(monkeypatch):
    import gtm.settings_store as ss
    import gtm.sheet as sheet

    monkeypatch.setattr(ss, "setting", lambda key, db=None: "sid" if key == "sheet_id" else False)
    monkeypatch.setattr(cli, "get_db", lambda: None)
    monkeypatch.setattr(sheet, "sheets_service", lambda: pytest.fail("built a Sheets service"))
    with pytest.raises(SystemExit, match="sheet_writeback_on"):
        cli.main(["sheet-paint", "--confirm"])
