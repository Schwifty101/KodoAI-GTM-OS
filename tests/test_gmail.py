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
