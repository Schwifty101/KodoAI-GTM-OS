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
    cli.main(["verify-sheet", "--batch", "b1"])  # dry run returns normally so a UI preview job ends done
    out = capsys.readouterr().out
    assert "0.5 x 2" in out and "--confirm" in out


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


def test_draft_takes_exactly_one_of_batch_and_batch_no():
    p = cli.build_parser()
    assert p.parse_args(["draft", "--batch", "b1"]).batch_no is None
    a = p.parse_args(["draft", "--batch-no", "3"])
    assert (a.batch, a.batch_no) == (None, 3)
    for argv in (["draft"], ["draft", "--batch", "b1", "--batch-no", "3"]):
        with pytest.raises(SystemExit):
            p.parse_args(argv)


# --- Plan 9: recontact and backfill-contacts. Fakes only: never the real ledger, Hunter or settings. ---
class _ReadOnlyDb:
    """Every read returns no rows; any write is a failure."""
    not_ = property(lambda self: self)

    def table(self, name):
        return self

    def execute(self):
        return argparse.Namespace(data=[])

    def __getattr__(self, name):
        if name in ("insert", "update", "upsert", "delete"):
            raise AssertionError(f"dry run wrote via {name}")
        return lambda *a, **k: self


# two rows with a send date (the later one first, to prove the week lines are sorted), one without (skipped)
NOTION_CSV = (
    "Founder,Role,Company,Email,Website,State,Status,Initial Sent\n"
    "Jane Doe,Owner,Secret Clinic,jane.doe@secretclinic.example,https://secretclinic.example,TX,Sent,2026-10-01\n"
    "Sam Poe,Founder,Quiet Spa,sam@quietspa.example,https://quietspa.example,UT,Sent,2026-09-01\n"
    "John Roe,Founder,Hidden Spa,john@hiddenspa.example,https://hiddenspa.example,UT,Sent,\n")


def _ledger_env(monkeypatch, tmp_path):
    import gtm.contact_backfill as cb

    f = tmp_path / "notion.csv"
    f.write_bytes(b"\xef\xbb\xbf" + NOTION_CSV.encode())  # a BOM, as Notion exports it
    monkeypatch.setattr(cli, "get_db", lambda: _ReadOnlyDb())
    monkeypatch.setattr(cb, "setting", lambda key, db=None: 60)
    return str(f)


def test_recontact_and_backfill_commands_parse_and_confirm_defaults_false():
    p = cli.build_parser()
    a = p.parse_args(["recontact"])
    assert (a.confirm, a.limit, a.fn) == (False, None, cli.cmd_recontact)
    a = p.parse_args(["recontact", "--limit", "5", "--confirm"])
    assert (a.confirm, a.limit) == (True, 5)
    b = p.parse_args(["backfill-contacts", "n.csv"])
    assert (b.file, b.sheet, b.confirm, b.fn) == ("n.csv", False, False, cli.cmd_backfill_contacts)
    b = p.parse_args(["backfill-contacts", "n.csv", "--sheet", "--confirm"])
    assert (b.sheet, b.confirm) == (True, True)
    with pytest.raises(SystemExit):
        p.parse_args(["backfill-contacts"])  # FILE is required


def test_recontact_dry_run_builds_no_hunter_pool(monkeypatch, capsys):
    import gtm.recontact_pass as rp

    monkeypatch.setattr(cli, "HunterPool", lambda *a, **k: pytest.fail("built a Hunter pool"))
    monkeypatch.setattr(cli, "get_db", lambda: _ReadOnlyDb())  # a write raises
    monkeypatch.setattr(rp, "setting", lambda key, db=None: {"recontact_days": 60, "recontact_max_rounds": 3, "recontact_hunter_allowance_credits": 0.0}[key])
    cli.main(["recontact", "--limit", "5"])
    out = capsys.readouterr().out
    assert "recontact dry run" in out and "nothing written" in out


def test_recontact_confirm_builds_the_pool_and_passes_the_limit(monkeypatch):
    from datetime import date

    import gtm.recontact_pass as rp

    seen = []
    monkeypatch.setattr(cli, "get_db", lambda: "db")
    monkeypatch.setattr(cli, "get_settings", lambda: argparse.Namespace(hunter_keys=["k1"], daily_cap=40))  # build_parser reads daily_cap
    monkeypatch.setattr(cli, "HunterPool", lambda keys, **kw: ("pool", keys))
    monkeypatch.setattr(rp, "run_recontact", lambda *a: seen.append(a))
    cli.main(["recontact", "--limit", "5", "--confirm"])
    assert seen == [("db", ("pool", ["k1"]), 5, True, date.today())]


def test_recontact_refusal_exits_with_the_reason(monkeypatch):
    import gtm.recontact_pass as rp

    def refuse(*a):
        raise ValueError("--limit N (a positive number) is required with --confirm")

    monkeypatch.setattr(cli, "get_db", lambda: "db")
    monkeypatch.setattr(cli, "get_settings", lambda: argparse.Namespace(hunter_keys=[], daily_cap=40))
    monkeypatch.setattr(cli, "HunterPool", lambda *a, **k: None)
    monkeypatch.setattr(rp, "run_recontact", refuse)
    with pytest.raises(SystemExit, match="--limit"):
        cli.main(["recontact", "--confirm"])


def test_backfill_contacts_dry_run_writes_nothing(monkeypatch, tmp_path, capsys):
    path = _ledger_env(monkeypatch, tmp_path)  # the db fake raises on any insert/update/upsert/delete
    cli.main(["backfill-contacts", path])
    out = capsys.readouterr().out
    assert "inserted': 0" in out and "dry run: nothing written" in out


def test_backfill_contacts_prints_counts_only(monkeypatch, tmp_path, capsys):
    import re

    path = _ledger_env(monkeypatch, tmp_path)
    cli.main(["backfill-contacts", path])
    out = capsys.readouterr().out
    assert "outcome:\n  no_reply 2" in out and "skipped:\n  no_send_date 1" in out
    weeks = re.findall(r"^  (\d{4}-\d{2}-\d{2}) 1$", out, re.M)
    assert len(weeks) == 2 and weeks == sorted(weeks)  # one line per week, oldest first (the CSV lists the later contact first)
    for private in ("jane", "doe", "sam", "poe", "roe", "secret", "quiet", "hidden", "example", "@"):
        assert private not in out.lower()


def test_backfill_contacts_missing_file_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "get_db", lambda: pytest.fail("touched the database"))
    with pytest.raises(SystemExit, match="cannot read"):
        cli.main(["backfill-contacts", str(tmp_path / "nope.csv")])


def test_backfill_contacts_sheet_flag_reads_the_setting_or_refuses(monkeypatch, tmp_path):
    import gtm.contact_backfill as cb
    import gtm.settings_store as ss

    path = _ledger_env(monkeypatch, tmp_path)
    monkeypatch.setattr(ss, "setting", lambda key, db=None: "")
    monkeypatch.setattr(cb, "plan_backfill", lambda *a, **k: pytest.fail("planned without a sheet id"))
    with pytest.raises(SystemExit, match="sheet_id"):
        cli.main(["backfill-contacts", path, "--sheet"])
    seen = []
    monkeypatch.setattr(ss, "setting", lambda key, db=None: "SHEET123")
    monkeypatch.setattr(cb, "plan_backfill", lambda db, text, sheet_id=None, svc=None: seen.append(sheet_id) or ([], []))
    cli.main(["backfill-contacts", path, "--sheet"])
    cli.main(["backfill-contacts", path])
    assert seen == ["SHEET123", None]  # without --sheet no sheet is read
