from app.service import MeetingSorterService


def test_colon_is_replaced_in_yandex_disk_filename():
    original = "2026-07-14 14:18 (MSK) Техническое совещание.txt"
    result = MeetingSorterService._sanitize_yandex_filename(original)
    assert result == "2026-07-14 14-18 (MSK) Техническое совещание.txt"


def test_file_name_without_colon_is_unchanged():
    original = "2026-07-14 Техническое совещание.txt"
    result = MeetingSorterService._sanitize_yandex_filename(original)
    assert result == original
