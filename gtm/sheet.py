"""Google Sheets client: exact-colour reading and the write side (painting, Queue tab)."""
import sys
from dataclasses import dataclass
from pathlib import Path

from gtm.config import get_settings

SHEET_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SECRETS = Path(__file__).resolve().parent.parent / ".secrets"  # git-ignored
PURE = {"green": {"green": 1}, "red": {"red": 1}}
QUEUE_TAB = "Queue"
QUEUE_HEADER = ["business", "owner", "domain", "linkedin", "email", "status", "lead id"]  # A:G


@dataclass
class SheetRow:
    tab: str
    row_no: int  # 1-based, as in the sheet
    cells: list[str]
    colours: list[str | None]


def colour_of(bg: dict | None) -> str | None:
    """'green' or 'red' only for pure fills (each channel within 0.02); tints, blues and white are None."""
    bg = bg or {}
    for name, want in PURE.items():
        if all(abs(bg.get(ch, 0) - want.get(ch, 0)) <= 0.02 for ch in ("red", "green", "blue")):
            return name
    return None


def sheets_service():
    """OAuth once on the Mac (opens a browser); token under .secrets/token_sheets.json."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token = SECRETS / "token_sheets.json"
    creds = Credentials.from_authorized_user_file(str(token), [SHEET_SCOPE]) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not sys.stdin.isatty():  # headless VM: a browser flow would block the worker forever
            raise RuntimeError(f"Sheets token missing or invalid ({token.name}): re-authorise on the Mac")
        client_file = get_settings().google_oauth_client_file
        creds = InstalledAppFlow.from_client_secrets_file(client_file, [SHEET_SCOPE]).run_local_server(
            port=0, login_hint="soban@kodoai.xyz")
    SECRETS.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    return build("sheets", "v4", credentials=creds)


def read_tab(svc, sheet_id: str, tab: str) -> list[SheetRow]:
    """Non-blank rows of one tab; colours come from userEnteredFormat only (never effectiveFormat)."""
    resp = svc.spreadsheets().get(
        spreadsheetId=sheet_id, ranges=[f"'{tab}'!A:Z"], includeGridData=True,
        fields="sheets.data.rowData.values(formattedValue,userEnteredFormat.backgroundColor)").execute()
    sheets = resp.get("sheets", [])
    if not sheets:
        raise ValueError(f"tab {tab!r} not found in sheet")
    out = []
    for no, row in enumerate(sheets[0].get("data", [{}])[0].get("rowData", []), start=1):
        vals = row.get("values", [])
        cells = [str(v["formattedValue"]) if "formattedValue" in v else "" for v in vals]
        last = max((i for i, c in enumerate(cells) if c.strip()), default=-1)
        if last < 0:
            continue
        colours = [colour_of(v.get("userEnteredFormat", {}).get("backgroundColor")) for v in vals]
        colours += [None] * (last + 1 - len(colours))
        out.append(SheetRow(tab, no, cells[:last + 1], colours[:last + 1]))
    return out
