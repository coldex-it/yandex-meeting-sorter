from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from functools import partial

from .classifier import MeetingClassifier
from .config import Settings
from .disk_client import YandexDiskClient
from .email_reader import YandexMailReader
from .service import MeetingSorterService
from .storage import StateStore

LOGGER = logging.getLogger(__name__)
STOP_REQUESTED = False


def request_stop(signum, frame) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True
    LOGGER.info("Stop requested")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def build_service(settings: Settings) -> tuple[MeetingSorterService, StateStore]:
    classifier = MeetingClassifier(settings.rules_path)
    disk = YandexDiskClient(settings.yandex_disk_token)
    store = StateStore(settings.database_path)
    mail_factory = partial(
        YandexMailReader,
        host=settings.imap_host,
        port=settings.imap_port,
        mailbox=settings.imap_mailbox,
        username=settings.yandex_email,
        app_password=settings.yandex_app_password,
        timezone=settings.timezone,
    )
    service = MeetingSorterService(
        mail_reader_factory=mail_factory,
        classifier=classifier,
        disk=disk,
        store=store,
        disk_root=settings.yandex_disk_root,
        process_existing=settings.process_existing,
        initial_lookback_messages=settings.initial_lookback_messages,
    )
    return service, store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sort Yandex meeting transcripts")
    parser.add_argument("--once", action="store_true", help="Check mailbox once and exit")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate environment and rules without connecting to external services",
    )
    parser.add_argument(
        "--retry-ignored",
        action="store_true",
        help="Retry emails previously stored as ignored_unknown_subject",
    )
    parser.add_argument(
        "--scan-last",
        type=int,
        metavar="N",
        help="Inspect the last N mailbox emails, regardless of the saved last UID",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = Settings.from_env()
        configure_logging(settings.log_level)
        MeetingClassifier(settings.rules_path)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.check_config:
        print("Configuration is valid")
        return 0

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    service, store = build_service(settings)
    try:
        service.initialize()

        if args.retry_ignored:
            service.retry_ignored_unknown_subjects()
            return 0

        if args.scan_last is not None:
            if args.scan_last < 1:
                raise ValueError("--scan-last must be greater than zero")
            service.scan_recent(args.scan_last)
            return 0

        while not STOP_REQUESTED:
            try:
                count = service.run_once()
                if count:
                    LOGGER.info("Mailbox pass complete: %d email(s) inspected", count)
            except Exception:
                LOGGER.exception("Mailbox pass failed")

            if args.once:
                break

            for _ in range(settings.poll_interval_seconds):
                if STOP_REQUESTED:
                    break
                time.sleep(1)
    finally:
        store.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
