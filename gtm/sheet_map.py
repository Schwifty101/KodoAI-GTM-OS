"""Map sheet tabs to lead fields: block detection (Utah has two header rows) and header-text column mapping."""
import re
from dataclasses import dataclass

from gtm.sheet import SheetRow

TAB_STATE = {"Utah": "UT", "Newyork": "NY", "Texas": "TX"}
# One header per tab (sheet-format merges extra blocks under it). A tab with several blocks and an entry here is merged to this header.
MERGE_TARGET = {"Utah": ["business", "maps_category", "website", "buyer_name", "buyer_role", "linkedin_url", "email", "email_person",
                         "other_people", "maps_url", "city", "fit", "role_check", "role_evidence", "role_evidence_url",
                         "linkedin_to_check", "email_type", "email_status", "email_source", "notes"]}
MERGE_ALIAS = {  # a later block's own header (lower-case) -> target column
    "company": "business", "city": "city", "website": "website", "fit": "fit", "buyer": "buyer_name", "role": "buyer_role",
    "role check": "role_check", "role evidence (quote)": "role_evidence", "role evidence url": "role_evidence_url",
    "linkedin (confirmed)": "linkedin_url", "linkedin (to check)": "linkedin_to_check", "email": "email", "email type": "email_type",
    "email status": "email_status", "email source": "email_source", "notes": "notes"}
# Columns the importer reads: see HEADERS. Every other merged column (email_person, other_people, fit, role_check, role_evidence,
# role_evidence_url, email_type, email_status, email_source, notes) is kept in the sheet and ignored by design.
HEADERS = {  # header text (lower-case) -> field; unknown headers are ignored
    "linkedin_to_check": "owner_linkedin_check",
    "business": "name", "company": "name", "maps_category": "category", "website": "website",
    "buyer_name": "owner_name", "buyer": "owner_name", "buyer_role": "owner_title", "role": "owner_title",
    "linkedin_url": "owner_linkedin", "linkedin (confirmed)": "owner_linkedin", "linkedin (to check)": "owner_linkedin_check",
    "email": "owner_email", "maps_url": "maps_url", "city": "city", "metro": "city",
}


@dataclass
class MappedRow:
    tab: str
    block: int
    row_no: int
    fields: dict[str, str]
    emails: list[str]
    colour: str | None
    width: int


def _is_header(r: SheetRow) -> bool:
    return bool(r.cells) and r.cells[0].strip().lower() in ("business", "company")


def header_map(cells: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i, c in enumerate(cells):
        f = HEADERS.get(c.strip().lower())
        if f and f not in out:
            out[f] = i
    return out


def blocks(rows: list[SheetRow], tab: str = "") -> list[tuple[dict[str, int], list[SheetRow]]]:
    tab = rows[0].tab if rows else tab
    out: list[tuple[dict[str, int], list[SheetRow]]] = []
    for r in rows:
        if _is_header(r):
            out.append((header_map(r.cells), []))
        elif out:
            out[-1][1].append(r)
        else:
            raise ValueError(f"tab {tab!r}: data row {r.row_no} before any header row")
    if not out:
        raise ValueError(f"tab {tab!r}: no header row (first cell 'business' or 'Company') found")
    return out


def _cell(cells: list[str], i: int | None) -> str:
    return cells[i].strip() if i is not None and i < len(cells) else ""


def map_tab(tab: str, rows: list[SheetRow]) -> list[MappedRow]:
    out = []
    headers = [r for r in rows if _is_header(r)]
    for n, (hm, data) in enumerate(blocks(rows, tab), start=1):
        width = len(headers[n - 1].cells)
        for r in data:
            f = {k: _cell(r.cells, hm.get(k)) for k in set(hm) - {"owner_linkedin_check"}}
            f["owner_linkedin"] = f.get("owner_linkedin") or _cell(r.cells, hm.get("owner_linkedin_check"))
            f["state"] = TAB_STATE.get(tab, "")
            emails = [t for t in re.split(r"[\s,;]+", f.get("owner_email", "").lower()) if "@" in t]
            colour = "red" if "red" in r.colours else "green" if "green" in r.colours else None
            out.append(MappedRow(tab, n, r.row_no, f, emails, colour, width))
    return out
