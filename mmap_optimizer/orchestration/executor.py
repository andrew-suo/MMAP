from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, TypeVar
import time

from mmap_optimizer.config import ExecutionConfig, execution_config_from_mapping

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class TaskOutcome:
    sample_id: str
    ok: bool
    value: Any = None
    error: str | None = None
    exception_type: str | None = None
    timed_out: bool = False
    attempt_count: int = 1


def get_sample_id(sample: Any) -> str:
    if isinstance(sample, Mapping):
        for key in ("sample_id", "id", "uid"):
            if key in sample:
                return str(sample[key])
    return str(sample)


class SampleExecutor:
    """Execute sample-level tasks serially or with a thread pool."""

    def __init__(self, config: ExecutionConfig | Mapping[str, object] | None = None):
        if isinstance(config, ExecutionConfig):
            self.config = config
        else:
            self.config = execution_config_from_mapping(dict(config or {}))

    def map(
        self,
        samples: Iterable[T],
        fn: Callable[[T], R],
        *,
        sample_id_getter: Callable[[T], str] = get_sample_id,
        sort_by_sample_id: bool = False,
    ) -> list[TaskOutcome]:
        values = list(samples)
        if self.config.mode == "serial" or self.config.max_workers <= 1:
            outcomes = [self._run_one(sample, fn, sample_id_getter) for sample in values]
        else:
            outcomes = self._run_thread_pool(values, fn, sample_id_getter)
        if sort_by_sample_id:
            outcomes.sort(key=lambda outcome: outcome.sample_id)
        return outcomes

    def _run_thread_pool(self, samples: list[T], fn: Callable[[T], R], sample_id_getter: Callable[[T], str]) -> list[TaskOutcome]:
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures = [(sample, pool.submit(self._run_one, sample, fn, sample_id_getter)) for sample in samples]
            outcomes: list[TaskOutcome] = []
            for sample, future in futures:
                sample_id = sample_id_getter(sample)
                try:
                    outcomes.append(future.result(timeout=self.config.timeout_seconds))
                except FutureTimeout:
                    outcomes.append(TaskOutcome(sample_id=sample_id, ok=False, error="TIMEOUT", exception_type="TimeoutError", timed_out=True))
            return outcomes

    def _run_one(self, sample: T, fn: Callable[[T], R], sample_id_getter: Callable[[T], str]) -> TaskOutcome:
        sample_id = sample_id_getter(sample)
        attempts = self.config.retry_attempts + 1
        for attempt in range(1, attempts + 1):
            try:
                return TaskOutcome(sample_id=sample_id, ok=True, value=fn(sample), attempt_count=attempt)
            except Exception as exc:  # executor boundary converts per-sample failures to data
                if attempt >= attempts:
                    return TaskOutcome(sample_id=sample_id, ok=False, error=str(exc), exception_type=type(exc).__name__, attempt_count=attempt)
                if self.config.retry_backoff_seconds:
                    time.sleep(self.config.retry_backoff_seconds)
        raise AssertionError("unreachable")


def create_executor(config: ExecutionConfig | Mapping[str, object] | None = None) -> SampleExecutor:
    return SampleExecutor(config)


def map_ordered(items: Iterable[T], fn: Callable[[T], R], *, max_workers: int = 1) -> list[R]:
    config = ExecutionConfig(mode="thread_pool" if max_workers > 1 else "serial", max_workers=max_workers)
    outcomes = SampleExecutor(config).map(list(items), fn)
    results: list[R] = []
    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(outcome.error or outcome.exception_type or "executor task failed")
        results.append(outcome.value)
    return results
