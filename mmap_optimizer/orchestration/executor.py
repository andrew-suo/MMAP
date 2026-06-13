"""Sample-level execution utilities.

The executor centralizes the behavior required by runners that make one model
call per sample: serial/thread-pool execution, deterministic output ordering,
per-sample exception isolation, and optional timeout reporting.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from time import monotonic
from traceback import format_exception_only
from typing import Callable, Generic, Iterable, Literal, Mapping, Sequence, TypeVar

from mmap_optimizer.config import ExecutionConfig

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
SampleId = str | int
ExecutionMode = Literal["serial", "thread_pool"]


@dataclass(frozen=True)
class TaskOutcome(Generic[OutputT]):
    """Result of running one sample-level task."""

    sample_id: SampleId | None
    index: int
    ok: bool
    value: OutputT | None = None
    error: str | None = None
    exception_type: str | None = None
    timed_out: bool = False


def get_sample_id(sample: object) -> SampleId | None:
    """Best-effort extraction of a stable sample identifier."""

    if isinstance(sample, Mapping):
        for key in ("sample_id", "id"):
            value = sample.get(key)
            if value is not None:
                return value if isinstance(value, (str, int)) else str(value)
    for attr in ("sample_id", "id"):
        value = getattr(sample, attr, None)
        if value is not None:
            return value if isinstance(value, (str, int)) else str(value)
    return None


def _sort_key(outcome: TaskOutcome[OutputT]) -> tuple[int, str, int]:
    if outcome.sample_id is None:
        return (1, "", outcome.index)
    return (0, str(outcome.sample_id), outcome.index)


class SampleExecutor:
    """Run independent sample tasks with deterministic, isolated outcomes."""

    def __init__(self, config: ExecutionConfig | Mapping[str, object] | None = None):
        raw_config = (
            config
            if isinstance(config, ExecutionConfig)
            else ExecutionConfig.from_mapping(config)
        )
        mode = raw_config.mode.replace("-", "_")
        if mode in {"threads", "parallel"}:
            mode = "thread_pool"
        self.config = ExecutionConfig(
            mode=mode,
            max_workers=raw_config.max_workers,
            timeout_seconds=raw_config.timeout_seconds,
        )
        if self.config.mode not in {"serial", "thread_pool"}:
            raise ValueError("execution.mode must be 'serial' or 'thread_pool'")
        if self.config.max_workers < 1:
            raise ValueError("execution.max_workers must be >= 1")

    def map(
        self,
        items: Iterable[InputT],
        fn: Callable[[InputT], OutputT],
        *,
        sample_id_getter: Callable[[InputT], SampleId | None] | None = None,
        sort_by_sample_id: bool = True,
    ) -> list[TaskOutcome[OutputT]]:
        """Run ``fn`` for each item and return deterministic outcomes.

        Exceptions raised by one item are captured in that item's outcome and do
        not stop other items. Results are sorted by ``sample_id`` when every item
        has an id; otherwise input order is preserved.
        """

        sequence = list(items)
        id_getter = sample_id_getter or get_sample_id
        if self.config.mode == "thread_pool" and self.config.max_workers > 1:
            outcomes = self._thread_pool_map(sequence, fn, id_getter)
        else:
            outcomes = self._serial_map(sequence, fn, id_getter)
        if sort_by_sample_id and outcomes and all(outcome.sample_id is not None for outcome in outcomes):
            return sorted(outcomes, key=_sort_key)
        return sorted(outcomes, key=lambda outcome: outcome.index)

    def _serial_map(
        self,
        items: Sequence[InputT],
        fn: Callable[[InputT], OutputT],
        sample_id_getter: Callable[[InputT], SampleId | None],
    ) -> list[TaskOutcome[OutputT]]:
        outcomes: list[TaskOutcome[OutputT]] = []
        for index, item in enumerate(items):
            sample_id = sample_id_getter(item)
            started = monotonic()
            try:
                value = fn(item)
                if self.config.timeout_seconds is not None and monotonic() - started > self.config.timeout_seconds:
                    outcomes.append(self._timeout_outcome(sample_id, index))
                else:
                    outcomes.append(TaskOutcome(sample_id=sample_id, index=index, ok=True, value=value))
            except Exception as exc:  # noqa: BLE001 - isolate task failures intentionally.
                outcomes.append(self._exception_outcome(sample_id, index, exc))
        return outcomes

    def _thread_pool_map(
        self,
        items: Sequence[InputT],
        fn: Callable[[InputT], OutputT],
        sample_id_getter: Callable[[InputT], SampleId | None],
    ) -> list[TaskOutcome[OutputT]]:
        outcomes: dict[int, TaskOutcome[OutputT]] = {}
        starts: dict[Future[OutputT], float] = {}
        future_meta: dict[Future[OutputT], tuple[int, SampleId | None]] = {}
        pending: set[Future[OutputT]] = set()

        executor = ThreadPoolExecutor(max_workers=self.config.max_workers)
        try:
            for index, item in enumerate(items):
                future = executor.submit(fn, item)
                future_meta[future] = (index, sample_id_getter(item))
                starts[future] = monotonic()
                pending.add(future)

            while pending:
                timeout = self._next_wait_timeout(pending, starts)
                done, pending = wait(pending, timeout=timeout, return_when=FIRST_COMPLETED)
                for future in done:
                    index, sample_id = future_meta[future]
                    outcomes[index] = self._future_outcome(future, sample_id, index)

                if self.config.timeout_seconds is not None:
                    now = monotonic()
                    expired = {
                        future
                        for future in pending
                        if now - starts[future] >= self.config.timeout_seconds
                    }
                    for future in expired:
                        index, sample_id = future_meta[future]
                        future.cancel()
                        outcomes[index] = self._timeout_outcome(sample_id, index)
                    pending -= expired
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return [outcomes[index] for index in range(len(items))]

    def _next_wait_timeout(self, pending: set[Future[OutputT]], starts: dict[Future[OutputT], float]) -> float | None:
        if self.config.timeout_seconds is None:
            return None
        now = monotonic()
        return max(0.0, min(self.config.timeout_seconds - (now - starts[future]) for future in pending))

    @staticmethod
    def _future_outcome(future: Future[OutputT], sample_id: SampleId | None, index: int) -> TaskOutcome[OutputT]:
        try:
            return TaskOutcome(sample_id=sample_id, index=index, ok=True, value=future.result())
        except Exception as exc:  # noqa: BLE001 - isolate task failures intentionally.
            return SampleExecutor._exception_outcome(sample_id, index, exc)

    @staticmethod
    def _exception_outcome(sample_id: SampleId | None, index: int, exc: Exception) -> TaskOutcome[OutputT]:
        message = "".join(format_exception_only(type(exc), exc)).strip()
        return TaskOutcome(
            sample_id=sample_id,
            index=index,
            ok=False,
            error=message,
            exception_type=type(exc).__name__,
        )

    @staticmethod
    def _timeout_outcome(sample_id: SampleId | None, index: int) -> TaskOutcome[OutputT]:
        return TaskOutcome(
            sample_id=sample_id,
            index=index,
            ok=False,
            error="Task timed out",
            exception_type="TimeoutError",
            timed_out=True,
        )


def create_executor(config: ExecutionConfig | Mapping[str, object] | None = None) -> SampleExecutor:
    """Factory used by runners and tests."""

    return SampleExecutor(config)
