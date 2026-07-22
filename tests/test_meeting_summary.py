from __future__ import annotations

import email
from email.message import EmailMessage

from app.email_reader import YandexMailReader
from app.meeting_summary import extract_meeting_summary
from app.models import TextAttachment


MARKER = "В конспекте могут быть неточности — проверяйте важное."


def test_extracts_plain_text_after_marker_only() -> None:
    message = EmailMessage()
    message.set_content(
        "Конспект встречи\n"
        "«Совещание Техническое»\n"
        "Конспектирование началось 21.07.2026 в 14:25 (MSK)\n"
        "Ссылка на встречу: https://telemost.360.yandex.ru/j/0956642590\n"
        "Во вложении — файл с полной расшифровкой.\n"
        f"{MARKER}\n\n"
        "Основные итоги\n"
        "- Бот имеет ограничения и может допускать ошибки.\n"
        "- Следующая задача назначена на пятницу.\n"
    )

    assert extract_meeting_summary(message) == (
        "Основные итоги\n"
        "- Бот имеет ограничения и может допускать ошибки.\n"
        "- Следующая задача назначена на пятницу."
    )


def test_decodes_quoted_printable_html_utf8() -> None:
    message = EmailMessage()
    message.set_content("Fallback without marker")
    message.add_alternative(
        """
        <html>
          <head><style>.hidden { display:none; }</style></head>
          <body>
            <p>Конспект встречи</p>
            <p>«Совещание Техническое»</p>
            <p>В конспекте могут быть неточности — проверяйте важное.</p>
            <h2>Задачи</h2>
            <ul>
              <li>Бот имеет ограничения и может допускать ошибки.</li>
              <li>Проверить интеграцию.</li>
            </ul>
          </body>
        </html>
        """,
        subtype="html",
        charset="utf-8",
        cte="quoted-printable",
    )

    raw = message.as_bytes()
    parsed = email.message_from_bytes(raw)

    assert extract_meeting_summary(parsed) == (
        "Задачи\n"
        "- Бот имеет ограничения и может допускать ошибки.\n"
        "- Проверить интеграцию."
    )


def test_returns_none_without_marker() -> None:
    message = EmailMessage()
    message.set_content("Обычное письмо без конспекта")

    assert extract_meeting_summary(message) is None


def test_appends_utf8_summary_named_from_transcript() -> None:
    message = EmailMessage()
    message.set_content(f"Преамбула\n{MARKER}\nИтог встречи")
    attachments = [
        TextAttachment(
            original_filename=(
                "2026-07-21 14:25 (MSK) Совещание Техническое.txt"
            ),
            content=b"transcript",
        )
    ]

    YandexMailReader._append_generated_summary(message, attachments)

    assert len(attachments) == 2
    assert attachments[1].original_filename == (
        "Конспект 2026-07-21 14:25 (MSK) Совещание Техническое.txt"
    )
    assert attachments[1].content.decode("utf-8") == "Итог встречи"


def test_does_not_duplicate_existing_summary_attachment() -> None:
    message = EmailMessage()
    message.set_content(f"Преамбула\n{MARKER}\nИтог встречи")
    attachments = [
        TextAttachment("2026-07-21 meeting.txt", b"transcript"),
        TextAttachment("Конспект 2026-07-21 meeting.txt", b"summary"),
    ]

    YandexMailReader._append_generated_summary(message, attachments)

    assert len(attachments) == 2
