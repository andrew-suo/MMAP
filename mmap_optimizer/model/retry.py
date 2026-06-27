"""Model call retry helpers."""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.artifacts import to_artifact_data
from .client import ModelResponse


@dataclass
class RetryConfig:
    max_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    jitter_seconds: float = 0.2

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RetryConfig":
        data = data or {}
        return cls(
            max_attempts=max(1, int(data.get("max_attempts", 3))),
            initial_backoff_seconds=float(data.get("initial_backoff_seconds", 1.0)),
            backoff_multiplier=float(data.get("backoff_multiplier", 2.0)),
            jitter_seconds=float(data.get("jitter_seconds", 0.2)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "initial_backoff_seconds": self.initial_backoff_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "jitter_seconds": self.jitter_seconds,
        }


@dataclass
class FailurePolicyConfig:
    skip_single_sample_failure: bool = True
    max_consecutive_sample_failures: int = 3

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "FailurePolicyConfig":
        data = data or {}
        return cls(
            skip_single_sample_failure=bool(data.get("skip_single_sample_failure", True)),
            max_consecutive_sample_failures=max(
                1, int(data.get("max_consecutive_sample_failures", 3))
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skip_single_sample_failure": self.skip_single_sample_failure,
            "max_consecutive_sample_failures": self.max_consecutive_sample_failures,
        }


class ConsecutiveModelFailureError(RuntimeError):
    """Raised when sample-level model calls fail too many times in a row."""


class SampleFailureTracker:
    def __init__(self, max_consecutive_failures: int = 3):
        self.max_consecutive_failures = max(1, max_consecutive_failures)
        self.consecutive_failures = 0

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self, *, sample_id: str, call_type: str, error: Exception) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            raise ConsecutiveModelFailureError(
                f"{call_type} failed for {self.consecutive_failures} consecutive samples; "
                f"last sample={sample_id}: {type(error).__name__}: {error}"
            ) from error


class RetryingModelClient:
    """Wrap a ModelClient and retry all model interactions."""

    def __init__(
        self,
        inner: Any,
        retry_config: RetryConfig | None = None,
        failure_log_path: str | Path | None = None,
        client_name: str = "model_client",
    ):
        self.inner = inner
        self.retry_config = retry_config or RetryConfig()
        self.failure_log_path = Path(failure_log_path) if failure_log_path else None
        self.client_name = client_name

    def complete(
        self,
        messages: list[dict[str, Any]],
        model_config: dict[str, Any] | None = None,
        response_format: Any | None = None,
    ) -> ModelResponse:
        return self._with_retry(
            "complete",
            lambda: self.inner.complete(messages, model_config, response_format),
            model_config=model_config,
        )

    def complete_multimodal(
        self,
        messages: list[dict[str, Any]],
        assets: list[Any],
        model_config: dict[str, Any] | None = None,
        response_format: Any | None = None,
    ) -> ModelResponse:
        return self._with_retry(
            "complete_multimodal",
            lambda: self.inner.complete_multimodal(
                messages, assets, model_config, response_format
            ),
            model_config=model_config,
            asset_count=len(assets or []),
        )

    def _with_retry(
        self,
        call_type: str,
        fn: Callable[[], ModelResponse],
        *,
        model_config: dict[str, Any] | None = None,
        asset_count: int | None = None,
    ) -> ModelResponse:
        cfg = self.retry_config
        last_error: Exception | None = None
        for attempt in range(1, cfg.max_attempts + 1):
            try:
                response = fn()
                if response.metadata is None:
                    response.metadata = {}
                response.metadata.setdefault("retry_attempts", attempt)
                return response
            except Exception as exc:
                last_error = exc
                self._record_failure(
                    call_type=call_type,
                    attempt=attempt,
                    model_config=model_config,
                    asset_count=asset_count,
                    error=exc,
                )
                if attempt >= cfg.max_attempts or not self._should_retry(exc):
                    raise
                delay = cfg.initial_backoff_seconds * (
                    cfg.backoff_multiplier ** (attempt - 1)
                )
                if cfg.jitter_seconds > 0:
                    delay += random.uniform(0, cfg.jitter_seconds)
                time.sleep(max(0.0, delay))
        assert last_error is not None
        raise last_error

    def _should_retry(self, exc: Exception) -> bool:
        code = getattr(exc, "code", None) or getattr(exc, "status", None)
        if isinstance(code, int) and 400 <= code < 500 and code != 429:
            return False
        return True

    def _record_failure(
        self,
        *,
        call_type: str,
        attempt: int,
        model_config: dict[str, Any] | None,
        asset_count: int | None,
        error: Exception,
    ) -> None:
        if self.failure_log_path is None:
            return
        self.failure_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client": self.client_name,
            "call_type": call_type,
            "attempt": attempt,
            "max_attempts": self.retry_config.max_attempts,
            "model": (model_config or {}).get("model"),
            "asset_count": asset_count,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        with open(self.failure_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(to_artifact_data(record), ensure_ascii=False) + "\n")


__all__ = [
    "ConsecutiveModelFailureError",
    "FailurePolicyConfig",
    "RetryConfig",
    "RetryingModelClient",
    "SampleFailureTracker",
]
