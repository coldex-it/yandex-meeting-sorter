from __future__ import annotations

import email
import hashlib
import imaplib
import logging
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr
from zoneinfo import ZoneInfo

from .meeting_summary import extract_meeting_summary
from .models import ParsedMessage, TextAttachment

LOGGER = logging.getLogger(__name__)


class YandexMailReader:
    def __init__(
        self,
        host: str,
        port: int,
        mailbox: str,
        username: str,
        app_password: str,
        timezone: str,
    ) -> None:
        self.host = host
        self.port = port
        self.mailbox = mailbox
        self.username = username
        self.app_password = app_password
        self.timezone = ZoneInfo(timezone)
        self.connection: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "YandexMailReader":
        self.connection = imaplib.IMAP4_SSL(self.host, self.port, timeout=30)
        self.connection.login(self.username, self.app_password)
        status, _ = self.connection.select(self.mailbox, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not select IMAP mailbox: {self.mailbox}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self.connection:
            return
        try:
            self.connection.close()
        except imaplib.IMAP4.error:
            pass
        try:
            self.connection.logout()
        except imaplib.IMAP4.error:
            pass

    def _conn(self) -> imaplib.IMAP4_SSL:
        if self.connection is None:
            raise RuntimeError("IMAP connection is not open")
        return self.connection

    def list_uids_after(self, last_uid: int) -> list[int]:
        criterion = f"UID {last_uid + 1}:*"
        status, data = self._conn().uid("search", None, criterion)
        if status != "OK" or not data:
            raise RuntimeError("IMAP UID search failed")
        raw = data[0].split()
        return [int(uid) for uid in raw if uid and int(uid) > last_uid]

    def list_all_uids(self) -> list[int]:
        status, data = self._conn().uid("search", None, "ALL")
        if status != "OK" or not data:
            raise RuntimeError("IMAP search failed")
        return [int(uid) for uid in data[0].split() if uid]

    def fetch(self, uid: int) -> ParsedMessage:
        status, data = self._conn().uid("fetch", str(uid), "(BODY.PEEK[])")
        if status != "OK" or not data:
            raise RuntimeError(f"Could not fetch email UID {uid}")

        raw_message = next(
            (item[1] for item in data if isinstance(item, tuple) and len(item) > 1),
            None,
        )
        if raw_message is None:
            raise RuntimeError(f"Email UID {uid} has no message body")

        message = email.message_from_bytes(raw_message)
        subject = self._decode_header(message.get("Subject", ""))
        sender = self._sender_address(message)
        message_id = message.get("Message-ID", "").strip()
        if not message_id:
            message_id = f"uid:{uid}:{hashlib.sha256(raw_message).hexdigest()}"

        meeting_datetime = self._message_datetime(message)
        attachments = self._extract_text_attachments(message)
        self._append_generated_summary(message, attachments)

        return ParsedMessage(
            uid=uid,
            message_id=message_id,
            subject=subject,
            sender=sender,
            meeting_datetime=meeting_datetime,
            attachments=attachments,
        )

    def _sender_address(self, message: Message) -> str:
        raw_from = self._decode_header(message.get("From", ""))
        _, address = parseaddr(raw_from)
        return address.strip().casefold()

    @staticmethod
    def _decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except (LookupError, UnicodeError):
            return value

    def _message_datetime(self, message: Message) -> datetime:
        raw_date = message.get("Date")
        if raw_date:
            try:
                dt = parsedate_to_datetime(raw_date)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=self.timezone)
                return dt.astimezone(self.timezone)
            except (TypeError, ValueError, OverflowError):
                LOGGER.warning("Could not parse email Date header: %s", raw_date)
        return datetime.now(self.timezone)

    def _extract_text_attachments(self, message: Message) -> list[TextAttachment]:
        result: list[TextAttachment] = []
        for part in message.walk():
            if part.is_multipart():
                continue

            filename_raw = part.get_filename()
            if not filename_raw:
                continue
            filename = self._decode_header(filename_raw)
            if not filename.lower().endswith((".txt", ".md")):
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            result.append(
                TextAttachment(
                    original_filename=filename,
                    content=payload,
                )
            )
        return result

    @staticmethod
    def _append_generated_summary(
        message: Message,
        attachments: list[TextAttachment],
    ) -> None:
        summary_text = extract_meeting_summary(message)
        if not summary_text:
            return

        transcript = next(
            (
                attachment
                for attachment in attachments
                if not attachment.original_filename.strip().casefold().startswith(
                    "конспект "
                )
            ),
            None,
        )
        if transcript is None:
            LOGGER.warning(
                "Yandex meeting summary found, but no transcript attachment is available"
            )
            return

        summary_filename = f"Конспект {transcript.original_filename.strip()}"
        if any(
            attachment.original_filename.strip().casefold()
            == summary_filename.casefold()
            for attachment in attachments
        ):
            LOGGER.info("Summary attachment already exists: %s", summary_filename)
            return

        attachments.append(
            TextAttachment(
                original_filename=summary_filename,
                content=summary_text.encode("utf-8"),
            )
        )
        LOGGER.info("Extracted meeting summary from email body: %s", summary_filename)
