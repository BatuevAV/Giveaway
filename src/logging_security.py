"""Secure logging helpers with token redaction."""

import logging
import re


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts Telegram bot tokens in log output."""

    _PATTERNS = (
        re.compile(r"(https?://api\.telegram\.org/bot)([^/\s]+)", re.IGNORECASE),
        re.compile(r"\bbot\d{6,}:[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    )

    def _redact(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        redacted = self._PATTERNS[0].sub(r"\1<REDACTED>", redacted)
        redacted = self._PATTERNS[1].sub("bot<REDACTED>", redacted)
        redacted = self._PATTERNS[2].sub("<REDACTED>", redacted)
        return redacted

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        try:
            return self._redact(rendered)
        except Exception:
            # Defensive fallback during interpreter shutdown.
            return rendered


def setup_secure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with token-safe formatter."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(
        RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.addHandler(handler)

    # Avoid verbose request logs with full URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
