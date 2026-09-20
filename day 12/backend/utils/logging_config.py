"""Logging setup for the application.

The API key must never reach the logs, so this module installs a filter that
redacts anything that looks like a bearer token or an ``sk-`` style key.
"""

from __future__ import annotations

import logging
import re
import sys

_SECRET_PATTERNS = (
    re.compile(r"(sk-[A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)([^\s\"']+)"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)([^\s\"',}]+)"),
)


def redact(text: str) -> str:
    """Mask anything that looks like a secret inside ``text``."""
    result = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            result = pattern.sub(lambda m: m.group(1) + "***", result)
        else:
            result = pattern.sub(lambda m: m.group(1) + "***", result)
    return result


class RedactingFilter(logging.Filter):
    """Logging filter that masks secrets in the rendered message."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once."""
    root = logging.getLogger()
    if getattr(root, "_aichat_configured", False):
        root.setLevel(level.upper())
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())

    root.handlers = [handler]
    root.setLevel(level.upper())
    root._aichat_configured = True  # type: ignore[attr-defined]

    # httpx logs full request URLs; keep them at WARNING to avoid noise.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)