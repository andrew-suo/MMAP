"""Configuration helpers for MMAP optimizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ExecutionConfig:
    """Controls sample-level execution.

    Attributes:
        mode: ``"serial"`` runs work in-process in input order. ``"thread_pool"``
            runs samples concurrently using ``max_workers`` threads.
        max_workers: Maximum worker count for thread-pool execution. A value of
            ``1`` is treated as serial-equivalent by the executor.
        timeout_seconds: Optional per-batch timeout. Unfinished tasks are marked
            as timed out while completed tasks keep their results.
    """

    mode: str = "serial"
    max_workers: int = 1
    timeout_seconds: float | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "ExecutionConfig":
        """Build an execution config from a nested config mapping.

        Both of the following shapes are accepted::

            {"execution": {"mode": "thread_pool", "max_workers": 4}}
            {"mode": "thread_pool", "max_workers": 4}
        """

        if data is None:
            return cls()
        execution = data.get("execution", data) if isinstance(data, Mapping) else {}
        if not isinstance(execution, Mapping):
            return cls()
        timeout = execution.get("timeout_seconds", execution.get("timeout", None))
        return cls(
            mode=str(execution.get("mode", cls.mode)),
            max_workers=int(execution.get("max_workers", cls.max_workers)),
            timeout_seconds=None if timeout is None else float(timeout),
        )


@dataclass(frozen=True)
class OptimizerConfig:
    """Top-level optimizer configuration."""

    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "OptimizerConfig":
        return cls(execution=ExecutionConfig.from_mapping(data))
