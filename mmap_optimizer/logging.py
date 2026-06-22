"""Runtime logging utilities for MMAP optimizer."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

DEFAULT_LOG_LEVEL = os.environ.get("MMAP_LOG_LEVEL", "INFO").upper()

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """Get or create a logger with the given name.

    Args:
        name: Logger name, typically __name__ from the calling module

    Returns:
        Configured logger instance
    """
    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name)
    if not logger.handlers and not logging.getLogger().handlers:
        _setup_handler(logger)
    _loggers[name] = logger
    return logger


def _setup_handler(logger: logging.Logger) -> None:
    """Set up console handler with standard format."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO))


def set_log_level(level: str | int) -> None:
    """Set log level for all cached loggers.

    Args:
        level: Log level as string ('DEBUG', 'INFO', 'WARNING', 'ERROR') or int
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    for logger in _loggers.values():
        logger.setLevel(level)


def _safe_log_dict(data: dict[str, Any], *, max_value_len: int = 200) -> str:
    """Safely format a dict for logging, redacting sensitive keys.

    Args:
        data: Dictionary to format
        max_value_len: Maximum length for any single value

    Returns:
        Grep-friendly string representation
    """
    parts = []
    for key, value in data.items():
        # Redact sensitive keys
        if key.lower() in ("api_key", "authorization", "auth", "token", "secret", "password"):
            parts.append(f"{key}=<REDACTED>")
            continue

        str_value = str(value)
        original_len = len(str_value)

        # Redact base64 image data or very long content
        if "data:image" in str_value or original_len > 5000:
            parts.append(f"{key}=<BINARY_DATA>")
            continue

        # Truncate long values
        if original_len > max_value_len:
            str_value = str_value[:max_value_len] + "..."

        parts.append(f"{key}={str_value}")
    return " ".join(parts)


def log_stage(logger: logging.Logger, stage: str, message: str = "", **kwargs: Any) -> None:
    """Log a structured stage marker with optional Chinese message.

    Format: [stage=<name>] <message> key=value key=value

    Args:
        logger: Logger instance
        stage: Stage name (e.g., 'round_start', 'model_request')
        message: Human-readable message (Chinese supported)
        **kwargs: Additional key-value pairs to log
    """
    parts: list[str] = []
    if message:
        parts.append(message)
    if kwargs:
        parts.append(_safe_log_dict(kwargs))
    body = " ".join(parts)
    if body:
        logger.info(f"[stage={stage}] {body}")
    else:
        logger.info(f"[stage={stage}]")


def log_progress(logger: logging.Logger, message: str, **kwargs: Any) -> None:
    """Log a progress message with structured extras.

    Uses _safe_log_dict for consistent redaction.

    Args:
        logger: Logger instance
        message: Progress message
        **kwargs: Additional structured data
    """
    if kwargs:
        extra = _safe_log_dict(kwargs)
        logger.info(f"{message} {extra}")
    else:
        logger.info(message)
