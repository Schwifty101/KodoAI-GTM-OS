"""Gmail API access. Drafting and sending are separate calls; creating a draft never sends."""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from html import unescape
from pathlib import Path

from gtm.config import get_settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",  # create drafts and send them
    "https://www.googleapis.com/auth/gmail.readonly",  # read replies
]
SECRETS = Path(__file__).resolve().parent.parent / ".secrets"  # git-ignored


def gmail_service(mailbox: str):
    """OAuth once per mailbox (opens a browser); the token is stored under .secrets/."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token = SECRETS / f"token_{mailbox}.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        client_file = get_settings().google_oauth_client_file
        creds = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES).run_local_server(port=0, login_hint=mailbox)
    SECRETS.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def build_raw_message(to: str, subject: str, body: str, in_reply_to: str | None = None) -> str:
    m = EmailMessage()
    m["To"] = to
    m["Subject"] = subject
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to  # with threadId and a matching subject, this makes Touch 2 and 3 thread in the prospect's client
        m["References"] = in_reply_to
    m.set_content(body)
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def create_draft(svc, to: str, subject: str, body: str, thread_id: str | None = None, in_reply_to: str | None = None) -> str:
    message = {"raw": build_raw_message(to, subject, body, in_reply_to)}
    if thread_id:
        message["threadId"] = thread_id  # Touch 2 and 3 reply in the Touch 1 thread
    return svc.users().drafts().create(userId="me", body={"message": message}).execute()["id"]


def send_draft(svc, draft_id: str) -> str:
    out = svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return out["threadId"]


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def _walk(part: dict):
    yield part
    for p in part.get("parts") or []:
        yield from _walk(p)


def parse_message(m: dict) -> dict:
    """A Gmail API message becomes {from, subject, headers (names lowercased), body (plain text)}."""
    payload = m["payload"]
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    parts = list(_walk(payload))
    plain = [_decode(p["body"]["data"]) for p in parts if p.get("mimeType") == "text/plain" and (p.get("body") or {}).get("data")]
    if plain:
        body = "\n".join(plain)
    else:
        html = " ".join(_decode(p["body"]["data"]) for p in parts if p.get("mimeType") == "text/html" and (p.get("body") or {}).get("data"))
        body = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html)))
    return {"from": headers.get("from", ""), "subject": headers.get("subject", ""), "headers": headers, "body": body.strip()}


def thread_messages(svc, thread_id: str) -> list[dict]:
    t = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    return [parse_message(m) for m in t.get("messages", [])]


def recent_bounces(svc, days: int = 7) -> list[dict]:
    """Delivery-failure notices often arrive outside the original thread, so search for them."""
    q = f"from:(mailer-daemon OR postmaster) newer_than:{days}d"
    ids = svc.users().messages().list(userId="me", q=q).execute().get("messages", [])
    return [parse_message(svc.users().messages().get(userId="me", id=i["id"], format="full").execute()) for i in ids]
