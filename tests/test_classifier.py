from pathlib import Path

from app.classifier import MeetingClassifier


RULES = Path(__file__).parents[1] / "config" / "rules.yaml"


def test_fixed_meeting():
    classifier = MeetingClassifier(RULES)
    result = classifier.classify("Конспект встречи: Совещание по Одоо")
    assert result is not None
    assert result.meeting_name == "Совещание по Одоо"
    assert result.folder == "Совещание по Одоо"


def test_lead_number_is_preserved():
    classifier = MeetingClassifier(RULES)
    result = classifier.classify("Итоги — Совещание по Лиду 5316")
    assert result is not None
    assert result.meeting_name == "Совещание по Лиду 5316"
    assert result.folder == "Совещания по Лидам"


def test_unknown_subject():
    classifier = MeetingClassifier(RULES)
    assert classifier.classify("Обычное письмо") is None
