"""Gmail API access. Drafting and sending are separate calls; creating a draft never sends."""

from __future__ import annotations

import base64
from email.message import EmailMessage
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


def build_raw_message(to: str, subject: str, body: str) -> str:
    m = EmailMessage()
    m["To"] = to
    m["Subject"] = subject
    m.set_content(body)
    return base64.urlsafe_b64encode(m.as_bytes()).decode()


def create_draft(svc, to: str, subject: str, body: str) -> str:
    out = svc.users().drafts().create(userId="me", body={"message": {"raw": build_raw_message(to, subject, body)}}).execute()
    return out["id"]


def send_draft(svc, draft_id: str) -> str:
    out = svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    return out["threadId"]
