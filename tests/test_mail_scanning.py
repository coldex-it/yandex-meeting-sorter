from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.classifier import MeetingClassifier
from app.email_reader import YandexMailReader
from app.models import ParsedMessage, TextAttachment
from app.service import MeetingSorterService
from app.storage import StateStore


SUBJECT = "Конспект встречи «Coldex - Совещание по Продажам» от 01.10.2026"
RULES = Path(__file__).parents[1] / "config" / "rules.yaml"


def message(uid, *, sender="keeper@telemost.yandex.ru", subject=SUBJECT):
    return ParsedMessage(
        uid=uid,
        message_id=f"<message-{uid}>",
        subject=subject,
        sender=sender,
        meeting_datetime=datetime(2026, 10, 1, tzinfo=timezone.utc),
        attachments=[
            TextAttachment(f"meeting-{uid}.txt", b"transcript"),
            TextAttachment(f"Конспект meeting-{uid}.txt", b"summary"),
        ],
    )


class Mailbox:
    mailbox = "INBOX"

    def __init__(self):
        self.messages = {}
        self.fetched = []
        self.since = None
        self.fail_uid = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def list_all_uids(self):
        return sorted(self.messages)

    def list_uids_after(self, last_uid):
        return [uid for uid in self.list_all_uids() if uid > last_uid]

    def list_uids_since(self, since):
        self.since = since
        return self.list_all_uids()

    def fetch(self, uid):
        self.fetched.append(uid)
        if uid == self.fail_uid:
            raise RuntimeError("Temporary fetch failure")
        return self.messages[uid]


@pytest.fixture
def setup_service(tmp_path):
    mail = Mailbox()
    store = StateStore(tmp_path / "state.sqlite3")
    disk = Mock()
    disk.exists.return_value = False
    service = MeetingSorterService(
        mail_reader_factory=lambda: mail,
        classifier=MeetingClassifier(RULES),
        disk=disk,
        store=store,
        disk_root="/Совещания",
        process_existing=False,
        initial_lookback_messages=100,
    )
    try:
        yield service, mail, store, disk
    finally:
        store.close()


def test_incremental_scan_covers_more_than_ten_new_emails(setup_service):
    service, mail, store, disk = setup_service
    store.set_last_uid(100)
    mail.messages = {uid: message(uid) for uid in range(101, 116)}

    assert service.run_once() == 15
    assert store.get_last_uid() == 115
    assert disk.upload_bytes.call_count == 30
    assert service.run_once() == 0


def test_failed_email_is_retried_before_later_emails(setup_service):
    service, mail, store, disk = setup_service
    store.set_last_uid(100)
    mail.messages = {uid: message(uid) for uid in range(101, 104)}
    mail.fail_uid = 102

    with pytest.raises(RuntimeError, match="UID 102"):
        service.run_once()
    assert store.get_last_uid() == 101
    assert mail.fetched == [101, 102]

    mail.fail_uid = None
    assert service.run_once() == 2
    assert store.get_last_uid() == 103
    assert disk.upload_bytes.call_count == 6


def test_date_scan_recovers_ignored_coldex_title_and_preserves_cursor(setup_service):
    service, mail, store, disk = setup_service
    store.set_last_uid(500)
    mail.messages = {10: message(10)}
    store.record(10, "<message-10>", SUBJECT, status="ignored_unknown_subject")

    assert service.scan_since(date(2026, 10, 1)) == 1
    assert mail.since == date(2026, 10, 1)
    assert store.get_status(10, "<message-10>") == "uploaded"
    assert store.get_details(10, "<message-10>") == "summary_v1_saved"
    assert store.get_last_uid() == 500
    assert disk.upload_bytes.call_count == 2
    assert disk.upload_bytes.call_args.args[0] == (
        "/Совещания/Совещание по Продажам/Конспект meeting-10.txt"
    )

    assert service.scan_since(date(2026, 10, 1)) == 0
    assert disk.upload_bytes.call_count == 2


def test_backfill_adds_summary_to_legacy_upload_without_overwriting(setup_service):
    service, mail, store, disk = setup_service
    mail.messages = {10: message(10)}
    store.record(10, "<message-10>", SUBJECT, status="uploaded")
    disk.exists.side_effect = lambda path: path.endswith("/meeting-10.txt")

    assert service.scan_since(date(2026, 10, 1)) == 1
    disk.upload_bytes.assert_called_once_with(
        "/Совещания/Совещание по Продажам/Конспект meeting-10.txt",
        b"summary",
        overwrite=False,
    )


def test_date_scan_keeps_sender_and_recording_filters(setup_service, caplog):
    service, mail, store, disk = setup_service
    mail.messages = {
        10: message(10, sender="info@calendar.yandex.ru"),
        11: message(11, subject="Запись встречи «Coldex - Совещание по Продажам»"),
    }
    with caplog.at_level("INFO"):
        assert service.scan_since(date(2026, 10, 1)) == 2
    assert store.get_status(10, "<message-10>") == "ignored_sender"
    assert store.get_status(11, "<message-11>") == "ignored_subject_prefix"
    disk.upload_bytes.assert_not_called()
    assert "No meeting files saved" in caplog.text
    assert "'ignored_sender': 1" in caplog.text


def test_backfill_continues_after_failure_but_reports_failure(setup_service):
    service, mail, store, disk = setup_service
    mail.messages = {10: message(10), 11: message(11)}
    mail.fail_uid = 10
    with pytest.raises(RuntimeError, match="Failed to scan 1 email"):
        service.scan_recent(100)
    assert store.get_status(11, "<message-11>") == "uploaded"
    assert disk.upload_bytes.call_count == 2


@pytest.mark.parametrize("response, expected", [(b"20 5 15", [5, 15, 20]), (b"", [])])
def test_imap_date_search_uses_english_month_and_includes_all_results(response, expected):
    reader = YandexMailReader("imap.example.com", 993, "INBOX", "user", "pass", "UTC")
    reader.connection = Mock()
    reader.connection.uid.return_value = ("OK", [response])

    assert reader.list_uids_since(date(2026, 10, 1)) == expected
    reader.connection.uid.assert_called_once_with("search", None, "SINCE 01-Oct-2026")


def test_imap_date_search_failure_is_not_treated_as_empty_mailbox():
    reader = YandexMailReader("imap.example.com", 993, "INBOX", "user", "pass", "UTC")
    reader.connection = Mock()
    reader.connection.uid.return_value = ("NO", [b"Search failed"])
    with pytest.raises(RuntimeError, match="IMAP date search failed"):
        reader.list_uids_since(date(2026, 10, 1))
