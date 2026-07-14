from __future__ import annotations

import logging
from pathlib import PurePosixPath

from .classifier import MeetingClassifier
from .disk_client import YandexDiskClient
from .email_reader import YandexMailReader
from .models import ParsedMessage
from .storage import StateStore

LOGGER = logging.getLogger(__name__)


class MeetingSorterService:
    def __init__(
        self,
        mail_reader_factory,
        classifier: MeetingClassifier,
        disk: YandexDiskClient,
        store: StateStore,
        disk_root: str,
        process_existing: bool,
        initial_lookback_messages: int,
    ) -> None:
        self.mail_reader_factory = mail_reader_factory
        self.classifier = classifier
        self.disk = disk
        self.store = store
        self.disk_root = "/" + disk_root.strip("/")
        self.process_existing = process_existing
        self.initial_lookback_messages = initial_lookback_messages

    def initialize(self) -> None:
        info = self.disk.get_disk_info()
        LOGGER.info(
            "Connected to Yandex Disk as %s",
            info.get("user", {}).get("login", "unknown"),
        )
        self.disk.ensure_folder_tree(self.disk_root)

        if self.store.get_last_uid() is not None:
            return

        with self.mail_reader_factory() as mail:
            uids = mail.list_all_uids()

        if not uids:
            self.store.set_last_uid(0)
            return

        if self.process_existing:
            start_index = min(len(uids), self.initial_lookback_messages)
            start_uid = max(0, uids[-start_index] - 1)
            self.store.set_last_uid(start_uid)
            LOGGER.info(
                "First run: will inspect up to %d existing emails",
                self.initial_lookback_messages,
            )
        else:
            self.store.set_last_uid(uids[-1])
            LOGGER.info(
                "First run: existing emails skipped. Waiting for messages after UID %d",
                uids[-1],
            )

    def run_once(self) -> int:
        last_uid = self.store.get_last_uid() or 0
        processed_count = 0

        with self.mail_reader_factory() as mail:
            uids = mail.list_uids_after(last_uid)
            for uid in sorted(uids):
                try:
                    message = mail.fetch(uid)
                    self._process_message(message)
                    processed_count += 1
                except Exception:
                    LOGGER.exception(
                        "Failed to process email UID %d; it will be retried",
                        uid,
                    )
                    break
                else:
                    self.store.set_last_uid(uid)

        return processed_count

    def scan_recent(self, limit: int) -> int:
        if limit < 1:
            raise ValueError("scan limit must be greater than zero")

        with self.mail_reader_factory() as mail:
            uids = mail.list_all_uids()[-limit:]
            inspected_count = 0

            for uid in uids:
                try:
                    message = mail.fetch(uid)
                    status = self.store.get_status(
                        message.uid,
                        message.message_id,
                    )

                    if status == "uploaded":
                        LOGGER.info(
                            "Email UID %d already uploaded; skipped",
                            uid,
                        )
                        continue

                    self._process_message(
                        message,
                        force=status is not None,
                    )
                    inspected_count += 1
                except Exception:
                    LOGGER.exception("Failed to scan email UID %d", uid)

        LOGGER.info(
            "Recent scan complete: %d email(s) inspected from the last %d",
            inspected_count,
            len(uids),
        )
        return inspected_count

    def retry_ignored_unknown_subjects(self) -> int:
        uids = self.store.list_uids_by_status("ignored_unknown_subject")
        if not uids:
            LOGGER.info("No previously ignored unknown subjects to retry")
            return 0

        uploaded_count = 0
        with self.mail_reader_factory() as mail:
            for uid in uids:
                try:
                    message = mail.fetch(uid)
                    if self.classifier.classify(message.subject) is None:
                        LOGGER.info(
                            "Still unknown after rules update: %s",
                            message.subject,
                        )
                        continue
                    self._process_message(message, force=True)
                    uploaded_count += 1
                except Exception:
                    LOGGER.exception(
                        "Failed to retry previously ignored email UID %d",
                        uid,
                    )

        LOGGER.info(
            "Retry complete: %d of %d previously ignored email(s) uploaded",
            uploaded_count,
            len(uids),
        )
        return uploaded_count

    def _process_message(
        self,
        message: ParsedMessage,
        force: bool = False,
    ) -> None:
        if not force and self.store.is_processed(
            message.uid,
            message.message_id,
        ):
            LOGGER.info("Email UID %d already processed", message.uid)
            return

        classification = self.classifier.classify(message.subject)
        if classification is None:
            LOGGER.info(
                "Ignored unknown meeting subject: %s",
                message.subject,
            )
            self.store.record(
                message.uid,
                message.message_id,
                message.subject,
                status="ignored_unknown_subject",
            )
            return

        if not message.attachments:
            LOGGER.warning(
                "Known meeting email has no TXT/MD attachment: %s",
                message.subject,
            )
            self.store.record(
                message.uid,
                message.message_id,
                message.subject,
                status="ignored_no_text_attachment",
            )
            return

        target_folder = self._join_disk_path(
            self.disk_root,
            classification.folder,
        )
        self.disk.ensure_folder_tree(target_folder)

        uploaded_paths: list[str] = []

        for attachment in message.attachments:
            filename = self._validate_original_filename(
                attachment.original_filename,
            )
            target_path = self._join_disk_path(target_folder, filename)
            if self.disk.exists(target_path):
                LOGGER.info(
                    "File already exists on Yandex Disk; skipped: %s",
                    target_path,
                )
                uploaded_paths.append(target_path)
                continue

            self.disk.upload_bytes(
                target_path,
                attachment.content,
                overwrite=False,
            )
            uploaded_paths.append(target_path)
            LOGGER.info(
                "Uploaded email UID %d attachment %s to %s",
                message.uid,
                attachment.original_filename,
                target_path,
            )

        self.store.record(
            message.uid,
            message.message_id,
            message.subject,
            status="uploaded",
            disk_paths=uploaded_paths,
        )

    @staticmethod
    def _validate_original_filename(value: str) -> str:
        filename = value.strip()
        if not filename or filename in {".", ".."}:
            raise ValueError("Attachment has an empty or unsafe filename")
        if "/" in filename or "\x00" in filename:
            raise ValueError(
                f"Attachment filename contains an unsafe character: {value!r}"
            )
        return filename

    @staticmethod
    def _join_disk_path(*parts: str) -> str:
        clean = [part.strip("/") for part in parts if part and part.strip("/")]
        return "/" + str(PurePosixPath(*clean))
