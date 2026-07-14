from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import Classification


@dataclass(frozen=True)
class Rule:
    pattern: re.Pattern[str]
    canonical_name: str
    folder: str
    preserve_match: bool


class MeetingClassifier:
    QUOTED_TITLE_PATTERNS = (
        re.compile(r"«\s*(.*?)\s*»", re.UNICODE),
        re.compile(r'"\s*(.*?)\s*"', re.UNICODE),
    )

    def __init__(self, rules_path: Path):
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
        rules_data = raw.get("rules", [])
        if not rules_data:
            raise ValueError(f"No classification rules found in {rules_path}")

        self.rules: list[Rule] = []
        for item in rules_data:
            flags = re.IGNORECASE | re.UNICODE
            self.rules.append(
                Rule(
                    pattern=re.compile(str(item["pattern"]), flags),
                    canonical_name=str(item["canonical_name"]).strip(),
                    folder=str(item["folder"]).strip(),
                    preserve_match=bool(item.get("preserve_match", False)),
                )
            )

    @staticmethod
    def normalize_subject(subject: str) -> str:
        return re.sub(r"\s+", " ", subject.replace("\u00a0", " ")).strip()

    @classmethod
    def extract_meeting_title(cls, subject: str) -> str:
        meeting_title, _ = cls._classification_target(subject)
        return meeting_title

    @classmethod
    def _classification_target(cls, subject: str) -> tuple[str, bool]:
        normalized = cls.normalize_subject(subject)
        for pattern in cls.QUOTED_TITLE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                return cls.normalize_subject(match.group(1)), True
        return normalized, False

    def classify(self, subject: str) -> Classification | None:
        meeting_title, was_quoted = self._classification_target(subject)
        for rule in self.rules:
            match = (
                rule.pattern.fullmatch(meeting_title)
                if was_quoted
                else rule.pattern.search(meeting_title)
            )
            if not match:
                continue

            if rule.preserve_match:
                meeting_name = match.group(0).strip(" \t\r\n:–—-«»\"'")
                meeting_name = re.sub(r"\s+", " ", meeting_name)
            else:
                meeting_name = rule.canonical_name

            return Classification(meeting_name=meeting_name, folder=rule.folder)
        return None
