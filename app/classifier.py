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

    def classify(self, subject: str) -> Classification | None:
        normalized = self.normalize_subject(subject)
        for rule in self.rules:
            match = rule.pattern.search(normalized)
            if not match:
                continue

            if rule.preserve_match:
                meeting_name = match.group(0).strip(" \t\r\n:–—-«»\"'")
                meeting_name = re.sub(r"\s+", " ", meeting_name)
            else:
                meeting_name = rule.canonical_name

            return Classification(meeting_name=meeting_name, folder=rule.folder)
        return None
