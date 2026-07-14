from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    imap_host: str
    imap_port: int
    imap_mailbox: str
    yandex_email: str
    yandex_app_password: str
    yandex_disk_token: str
    yandex_disk_root: str
    poll_interval_seconds: int
    process_existing: bool
    initial_lookback_messages: int
    rules_path: Path
    database_path: Path
    log_level: str
    timezone: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Required environment variable is missing: {name}")
            return value

        def as_bool(name: str, default: bool = False) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        settings = cls(
            imap_host=os.getenv("IMAP_HOST", "imap.yandex.ru").strip(),
            imap_port=int(os.getenv("IMAP_PORT", "993")),
            imap_mailbox=os.getenv("IMAP_MAILBOX", "INBOX").strip(),
            yandex_email=required("YANDEX_EMAIL"),
            yandex_app_password=required("YANDEX_APP_PASSWORD"),
            yandex_disk_token=required("YANDEX_DISK_TOKEN"),
            yandex_disk_root=os.getenv("YANDEX_DISK_ROOT", "/Совещания").strip(),
            poll_interval_seconds=max(10, int(os.getenv("POLL_INTERVAL_SECONDS", "60"))),
            process_existing=as_bool("PROCESS_EXISTING", False),
            initial_lookback_messages=max(1, int(os.getenv("INITIAL_LOOKBACK_MESSAGES", "100"))),
            rules_path=Path(os.getenv("RULES_PATH", "/app/config/rules.yaml")),
            database_path=Path(os.getenv("DATABASE_PATH", "/app/data/meeting_sorter.sqlite3")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            timezone=os.getenv("TIMEZONE", "Europe/Helsinki").strip(),
        )

        if not settings.yandex_disk_root.startswith("/"):
            raise ValueError("YANDEX_DISK_ROOT must start with '/'")
        return settings
