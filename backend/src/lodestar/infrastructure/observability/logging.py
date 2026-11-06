"""Structured logging: JSON in deployed environments, readable console locally.

Request ids are bound through contextvars so every log line of a request correlates.
Secret-looking keys are redacted defensively, even though settings use SecretStr.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_SENSITIVE = ("password", "secret", "token", "api_key", "authorization", "cookie")


def _redact(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict):
        if any(s in key.lower() for s in _SENSITIVE) and key not in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
        ):
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging(level: str, *, json_logs: bool) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")
