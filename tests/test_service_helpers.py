from app.service import MeetingSorterService


def test_colon_is_replaced_in_yandex_disk_filename():
    original = "2026-07-14 14:18 (MSK) Техническое совещание.txt"
    result = MeetingSorterService._sanitize_yandex_filename(original)
    assert result == "2026-07-14 14-18 (MSK) Техническое совещание.txt"


def test_file_name_without_colon_is_unchanged():
    original = "2026-07-14 Техническое совещание.txt"
    result = MeetingSorterService._sanitize_yandex_filename(original)
    assert result == original


from datetime import datetime, timezone

from app.models import ParsedMessage


class _ClassifierSpy:
    def __init__(self):
        self.called = False

    def classify(self, subject):
        self.called = True
        return None


class _StoreSpy:
    def __init__(self):
        self.records = []

    def is_processed(self, uid, message_id):
        return False

    def record(self, uid, message_id, subject, status, disk_paths=None, details=None):
        self.records.append({"status": status, "details": details})


class _DiskStub:
    pass


def _message(sender: str, subject: str) -> ParsedMessage:
    return ParsedMessage(
        uid=1,
        message_id="<test@example.com>",
        subject=subject,
        sender=sender,
        meeting_datetime=datetime.now(timezone.utc),
        attachments=[],
    )


def _service(classifier, store):
    return MeetingSorterService(
        mail_reader_factory=None,
        classifier=classifier,
        disk=_DiskStub(),
        store=store,
        disk_root="/Совещания",
        process_existing=False,
        initial_lookback_messages=100,
    )


def test_disallowed_sender_is_ignored_before_classification():
    classifier = _ClassifierSpy()
    store = _StoreSpy()
    service = _service(classifier, store)

    service._process_message(
        _message("other@example.com", "Конспект встречи «продажи»")
    )

    assert classifier.called is False
    assert store.records[-1]["status"] == "ignored_sender"


def test_allowed_sender_is_case_insensitive():
    classifier = _ClassifierSpy()
    store = _StoreSpy()
    service = _service(classifier, store)

    service._process_message(
        _message("KEEPER@TELEMOST.YANDEX.RU", "Обычная тема")
    )

    assert classifier.called is True
    assert store.records[-1]["status"] == "ignored_unknown_subject"


def test_excluded_subject_prefix_is_ignored_before_classification():
    classifier = _ClassifierSpy()
    store = _StoreSpy()
    service = _service(classifier, store)

    service._process_message(
        _message(
            "keeper@telemost.yandex.ru",
            "  ЗАПИСЬ ВСТРЕЧИ 14.07.2026",
        )
    )

    assert classifier.called is False
    assert store.records[-1]["status"] == "ignored_subject_prefix"
