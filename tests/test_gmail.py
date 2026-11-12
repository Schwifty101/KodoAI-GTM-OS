import base64
from email import message_from_bytes

from gtm.gmail import build_raw_message, create_draft, send_draft


class _Exec:
    def __init__(self, out, sink, name, kw):
        self.out, self.sink, self.name, self.kw = out, sink, name, kw

    def execute(self):
        self.sink.append((self.name, self.kw))
        return self.out


class FakeGmail:
    """Records the calls gtm.gmail makes: users().drafts().create/send."""

    def __init__(self):
        self.calls = []

    def users(self):
        return self

    def drafts(self):
        return self

    def create(self, **kw):
        return _Exec({"id": "draft-1"}, self.calls, "create", kw)

    def send(self, **kw):
        return _Exec({"id": "msg-1", "threadId": "thread-1"}, self.calls, "send", kw)


def _decode(raw: str):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_build_raw_message_sets_recipient_subject_and_body():
    m = _decode(build_raw_message("owner@spa.com", "Quick question", "Hi Dana,\n\nBody."))
    assert m["To"] == "owner@spa.com"
    assert m["Subject"] == "Quick question"
    assert m.get_payload(decode=True).decode().strip() == "Hi Dana,\n\nBody."


def test_create_draft_returns_draft_id_and_sends_raw_message():
    svc = FakeGmail()
    assert create_draft(svc, "owner@spa.com", "Hi", "Body") == "draft-1"
    name, kw = svc.calls[0]
    assert kw["userId"] == "me"
    assert _decode(kw["body"]["message"]["raw"])["To"] == "owner@spa.com"


def test_send_draft_returns_thread_id_and_sends_that_draft():
    svc = FakeGmail()
    assert send_draft(svc, "draft-1") == "thread-1"
    assert svc.calls[0][1]["body"] == {"id": "draft-1"}


def test_creating_a_draft_never_calls_send():
    svc = FakeGmail()
    create_draft(svc, "a@b.com", "s", "b")
    assert [c[0] for c in svc.calls] == ["create"]


def test_create_draft_in_an_existing_thread_sets_the_thread_id():
    svc = FakeGmail()
    create_draft(svc, "a@b.com", "Re: s", "b", thread_id="thread-9")
    assert svc.calls[0][1]["body"]["message"]["threadId"] == "thread-9"


def test_create_draft_without_a_thread_sets_no_thread_id():
    svc = FakeGmail()
    create_draft(svc, "a@b.com", "s", "b")
    assert "threadId" not in svc.calls[0][1]["body"]["message"]


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode()


def test_parse_message_reads_headers_and_plain_text_body():
    from gtm.gmail import parse_message

    api = {"payload": {"mimeType": "text/plain", "headers": [{"name": "From", "value": "Dana <dana@glow.com>"}, {"name": "Subject", "value": "Re: Hi"},
                                                           {"name": "Auto-Submitted", "value": "auto-replied"}], "body": {"data": _b64("Sounds good.")}}}
    m = parse_message(api)
    assert m["from"] == "Dana <dana@glow.com>" and m["subject"] == "Re: Hi" and m["body"] == "Sounds good."
    assert m["headers"]["auto-submitted"] == "auto-replied"  # header names are lowercased


def test_parse_message_prefers_plain_text_in_multipart_and_strips_html_otherwise():
    from gtm.gmail import parse_message

    multi = {"payload": {"mimeType": "multipart/alternative", "headers": [], "parts": [
        {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}}, {"mimeType": "text/plain", "body": {"data": _b64("plain")}}]}}
    assert parse_message(multi)["body"] == "plain"
    html_only = {"payload": {"mimeType": "text/html", "headers": [], "body": {"data": _b64("<p>Hello <b>there</b></p>")}}}
    assert parse_message(html_only)["body"] == "Hello there"


def test_build_raw_message_sets_reply_headers_when_replying():
    m = _decode(build_raw_message("a@b.com", "Re: s", "b", in_reply_to="<m1@mail.gmail.com>"))
    assert m["In-Reply-To"] == "<m1@mail.gmail.com>" and m["References"] == "<m1@mail.gmail.com>"


def test_build_raw_message_has_no_reply_headers_by_default():
    m = _decode(build_raw_message("a@b.com", "s", "b"))
    assert m["In-Reply-To"] is None and m["References"] is None


def test_create_draft_passes_the_reply_header_through():
    svc = FakeGmail()
    create_draft(svc, "a@b.com", "Re: s", "b", thread_id="t", in_reply_to="<m1@x>")
    assert _decode(svc.calls[0][1]["body"]["message"]["raw"])["In-Reply-To"] == "<m1@x>"
