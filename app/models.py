from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Classification:
    meeting_name: str
    folder: str


@dataclass(frozen=True)
class TextAttachment:
    original_filename: str
    content: bytes


@dataclass(frozen=True)
class ParsedMessage:
    uid: int
    message_id: str
    subject: str
    meeting_datetime: datetime
    attachments: list[TextAttachment]
