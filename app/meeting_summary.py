from __future__ import annotations

import re
from email.message import Message
from html.parser import HTMLParser


SUMMARY_MARKER_RE = re.compile(
    r"В\s+конспекте\s+могут\s+быть\s+неточности\s*[—–-]\s*"
    r"проверяйте\s+важное\.?",
    flags=re.IGNORECASE,
)

_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "dl",
        "dt",
        "dd",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "ul",
    }
)

_IGNORED_TAGS = frozenset({"head", "script", "style", "svg"})


class _HTMLBodyTextExtractor(HTMLParser):
    """Convert the useful part of a simple HTML email into readable text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.casefold()
        if self._ignored_depth:
            self._ignored_depth += 1
            return
        if tag in _IGNORED_TAGS:
            self._ignored_depth = 1
            return
        if tag == "br":
            self._newline()
        elif tag == "li":
            self._newline()
            self._chunks.append("- ")
        elif tag in _BLOCK_TAGS:
            self._newline()

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag.casefold() == "br" and not self._ignored_depth:
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if self._ignored_depth:
            self._ignored_depth -= 1
            return
        tag = tag.casefold()
        if tag == "li" or tag in _BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if data.strip():
            self._chunks.append(data)
        elif "\n" not in data and "\r" not in data:
            # Preserve an inline separator between neighboring tags, but ignore
            # indentation/newlines used only to format the HTML source.
            self._chunks.append(" ")

    def text(self) -> str:
        return "".join(self._chunks)

    def _newline(self) -> None:
        if not self._chunks or not self._chunks[-1].endswith("\n"):
            self._chunks.append("\n")


def extract_meeting_summary(message: Message) -> str | None:
    """
    Return the Yandex-generated meeting summary from the email body.

    The MIME Content-Transfer-Encoding (including quoted-printable) is decoded
    by ``get_payload(decode=True)``. The preamble is removed through the marker
    sentence, and only the text after that sentence is returned.
    """

    plain_parts: list[str] = []
    html_parts: list[str] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        if part.get_filename():
            continue
        if part.get_content_disposition() == "attachment":
            continue

        content_type = part.get_content_type().casefold()
        if content_type not in {"text/plain", "text/html"}:
            continue

        decoded = _decode_text_part(part)
        if not decoded:
            continue

        if content_type == "text/html":
            decoded = _html_to_text(decoded)
            html_parts.append(decoded)
        else:
            plain_parts.append(decoded)

    # Prefer text/plain because it usually has less email-layout noise. If the
    # marker is absent there, fall back to the HTML alternative.
    for body in [*plain_parts, *html_parts]:
        summary = _extract_after_marker(body)
        if summary:
            return summary

    return None


def _decode_text_part(part: Message) -> str:
    payload = part.get_payload(decode=True)

    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""

    charset = part.get_content_charset()
    encodings: list[str] = []
    for candidate in (charset, "utf-8-sig", "utf-8", "utf-16", "cp1251"):
        if candidate and candidate.casefold() not in {
            item.casefold() for item in encodings
        }:
            encodings.append(candidate)

    for encoding in encodings:
        try:
            return payload.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    # Preserve visible text rather than dropping the whole summary. Replacement
    # characters are preferable to silently deleting undecodable bytes.
    return payload.decode("utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    parser = _HTMLBodyTextExtractor()
    parser.feed(value)
    parser.close()
    return parser.text()


def _extract_after_marker(value: str) -> str | None:
    cleaned = _normalize_text(value)
    match = SUMMARY_MARKER_RE.search(cleaned)
    if match is None:
        return None

    summary = _normalize_text(cleaned[match.end() :])
    return summary or None


def _normalize_text(value: str) -> str:
    value = (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\xa0", " ")
        .replace("\u200b", "")
    )

    normalized_lines: list[str] = []
    previous_blank = True

    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if line:
            normalized_lines.append(line)
            previous_blank = False
        elif not previous_blank:
            normalized_lines.append("")
            previous_blank = True

    return "\n".join(normalized_lines).strip()
