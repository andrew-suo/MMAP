"""Runtime logging utilities for MMAP optimizer."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

DEFAULT_LOG_LEVEL = os.environ.get("MMAP_LOG_LEVEL", "INFO").upper()

_loggers: dict[str, logging.Logger] = {}
_run_log_path: Path | None = None


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
    logger.setLevel(getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO))
    _loggers[name] = logger
    return logger


def configure_run_logging(
    output_dir: str | Path,
    *,
    level: str | int | None = None,
    log_to_console: bool = False,
) -> Path:
    """Configure runtime logs to be written under the run directory.

    The application uses stdout for user-facing progress. Runtime diagnostic
    logs are written to ``<output_dir>/logs/mmap.log`` by default.
    """
    global _run_log_path

    log_dir = Path(output_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "mmap.log"

    root_logger = logging.getLogger()
    log_level = (
        level
        if isinstance(level, int)
        else getattr(logging, str(level or DEFAULT_LOG_LEVEL).upper(), logging.INFO)
    )
    root_logger.setLevel(log_level)

    for handler in list(root_logger.handlers):
        if getattr(handler, "_mmap_run_handler", False):
            root_logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler._mmap_run_handler = True  # type: ignore[attr-defined]
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    if log_to_console:
        import sys

        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(log_level)
        console_handler._mmap_run_handler = True  # type: ignore[attr-defined]
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    _run_log_path = log_path
    return log_path


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
