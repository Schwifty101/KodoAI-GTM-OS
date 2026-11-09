# Spike E: Gmail API and sending limits (2026-11-10)

## Limits (Google Workspace sending limits page, fetched 2026-11-10)
- Paid accounts: **2,000 messages per day per user** (mail merge 1,500); 3,000 external recipients and 3,000 unique recipients a day; messages sent via the Gmail API are capped at 500 recipients each (we send to one).
- Exceeding a limit blocks new sends for **up to 24 hours** (receiving still works); limits apply over a rolling 24 hours and "can change without notice".
- **Trial accounts: 500 messages a day**, and limits do not rise during the trial; they rise after the domain has cumulatively paid at least $100 (up to 75 days). I do not know whether `kodoai.xyz` is on a paid or trial plan; Soban to confirm.
- These are Google's hard limits. The binding limit for cold email is reputation, not these numbers: the mailbox is warmed at about 15-30 emails a day (MailReach).

## What is built
`gtm/gmail.py` (tested against a fake Gmail service, 4 tests): `build_raw_message`, `create_draft(svc, to, subject, body) -> draft id`, `send_draft(svc, draft_id) -> thread id`, `gmail_service(mailbox)` (OAuth, token saved in git-ignored `.secrets/`). Creating a draft never sends. Scopes: `gmail.compose` (drafts and send) and `gmail.readonly` (read replies).

## Needs Soban (one-time, about 10 minutes)
1. In Google Cloud Console, create a project (or reuse one), then enable the **Gmail API**.
2. OAuth consent screen: user type **Internal** if the project belongs to the kodoai.xyz Workspace org (no app review, tokens do not expire after 7 days); otherwise External in Testing mode, where refresh tokens expire after 7 days and need re-login.
3. Credentials: create an **OAuth client ID, type Desktop app**, and download the JSON.
4. Save it as `.secrets/google_oauth_client.json` and set `GOOGLE_OAUTH_CLIENT_FILE=.secrets/google_oauth_client.json` in `.env`.
5. Run `uv run python -c "from gtm.gmail import *; from gtm.gmail import gmail_service as g; s=g('soban@kodoai.xyz'); print(create_draft(s,'soban@kodoai.xyz','GTM OS test','Draft only, not sent.'))"`: a browser opens, approve, and a draft appears in Gmail Drafts.

## Open
Live draft check (step 5) not done until the credential exists.
