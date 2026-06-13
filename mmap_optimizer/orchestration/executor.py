"""Deterministic batch execution utilities for MMAP orchestration.

The executor centralizes concurrency, retry, timeout, and error capture for
sample/run based orchestration components.  Results are always returned in the
same order as the input items so downstream artifact writers can remain
reproducible even when work is performed concurrently.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Iterable, Mapping, MutableMapping, Sequence, TypeVar
import time

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration shared by all batch orchestration calls."""

    max_workers: int = 1
    timeout_seconds: float | None = None
    retry_count: int = 0
    rate_limit_qps: float | None = None
    fail_fast: bool = False

    def __post_init__(self) -> None:
        if self.max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0 when provided")
        if self.retry_count < 0:
            raise ValueError("retry_count must be >= 0")
        if self.rate_limit_qps is not None and self.rate_limit_qps <= 0:
            raise ValueError("rate_limit_qps must be > 0 when provided")


@dataclass
class RunRecord(Generic[R]):
    """Per-sample execution record emitted by the executor."""

    index: int
    sample: Any
    success: bool
    output: R | None = None
    error_type: str | None = None
    error: str | None = None
    retry_count: int = 0
    metadata: MutableMapping[str, Any] = field(default_factory=dict)


class BatchExecutionError(RuntimeError):
    """Raised when fail-fast execution stops after a sample failure."""

    def __init__(self, record: RunRecord[Any]) -> None:
        super().__init__(record.error or record.error_type or "batch execution failed")
        self.record = record


class BatchExecutor:
    """Execute sample batches with deterministic result ordering."""

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self.config = config or ExecutionConfig()

    def run(
        self,
        samples: Sequence[T] | Iterable[T],
        worker: Callable[[T], R],
        *,
        metadata_factory: Callable[[int, T], Mapping[str, Any]] | None = None,
    ) -> list[RunRecord[R]]:
        """Run ``worker`` for every sample and return records in input order.

        Exceptions are isolated to the failing sample and converted into a
        ``RunRecord`` with ``success=False`` unless ``fail_fast`` is enabled, in
        which case a ``BatchExecutionError`` is raised after the failed record is
        created.
        """

        sample_list = list(samples)
        records: list[RunRecord[R] | None] = [None] * len(sample_list)
        if not sample_list:
            return []

        if self.config.max_workers == 1:
            for index, sample in enumerate(sample_list):
                record = self._run_one(index, sample, worker, metadata_factory)
                records[index] = record
                if self.config.fail_fast and not record.success:
                    raise BatchExecutionError(record)
            return [record for record in records if record is not None]

        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            futures: dict[Future[RunRecord[R]], int] = {}
            next_index = 0

            def submit_available() -> None:
                nonlocal next_index
                while next_index < len(sample_list) and len(futures) < self.config.max_workers:
                    index = next_index
                    sample = sample_list[index]
                    futures[pool.submit(self._run_one, index, sample, worker, metadata_factory)] = index
                    next_index += 1

            submit_available()
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    index = futures.pop(future)
                    record = future.result()
                    records[index] = record
                    if self.config.fail_fast and not record.success:
                        for pending in futures:
                            pending.cancel()
                        raise BatchExecutionError(record)
                submit_available()

        return [record for record in records if record is not None]

    def _run_one(
        self,
        index: int,
        sample: T,
        worker: Callable[[T], R],
        metadata_factory: Callable[[int, T], Mapping[str, Any]] | None,
    ) -> RunRecord[R]:
        metadata = dict(metadata_factory(index, sample)) if metadata_factory else {}
        attempts = self.config.retry_count + 1
        last_error: BaseException | None = None
        retries_used = 0

        for attempt in range(attempts):
            if attempt > 0:
                retries_used = attempt
            self._apply_rate_limit(attempt)
            try:
                return RunRecord(
                    index=index,
                    sample=sample,
                    success=True,
                    output=self._call_with_timeout(worker, sample),
                    retry_count=retries_used,
                    metadata=metadata,
                )
            except BaseException as exc:  # noqa: BLE001 - exceptions are stored per sample by design.
                last_error = exc

        assert last_error is not None
        return RunRecord(
            index=index,
            sample=sample,
            success=False,
            error_type=type(last_error).__name__,
            error=str(last_error),
            retry_count=retries_used,
            metadata=metadata,
        )

    def _call_with_timeout(self, worker: Callable[[T], R], sample: T) -> R:
        if self.config.timeout_seconds is None:
            return worker(sample)

        attempt_pool = ThreadPoolExecutor(max_workers=1)
        future = attempt_pool.submit(worker, sample)
        try:
            return future.result(timeout=self.config.timeout_seconds)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"sample timed out after {self.config.timeout_seconds} seconds") from exc
        finally:
            attempt_pool.shutdown(wait=False, cancel_futures=True)

    def _apply_rate_limit(self, attempt: int) -> None:
        if self.config.rate_limit_qps is None:
            return
        # The first attempt can start immediately; subsequent attempts are paced.
        if attempt > 0:
            time.sleep(1.0 / self.config.rate_limit_qps)


class _ExecutorBackedBatchMixin:
    """Mixin for orchestration components that expose batch calls."""

    def __init__(self, execution_config: ExecutionConfig | None = None, executor: BatchExecutor | None = None) -> None:
        self.executor = executor or BatchExecutor(execution_config)

    def _run_batch(self, samples: Sequence[T] | Iterable[T], worker: Callable[[T], R]) -> list[RunRecord[R]]:
        return self.executor.run(samples, worker)


class PromptTestRunner(_ExecutorBackedBatchMixin):
    """Prompt test batch runner backed by :class:`BatchExecutor`."""

    def run_batch(self, samples: Sequence[T] | Iterable[T], run_sample: Callable[[T], R]) -> list[RunRecord[R]]:
        return self._run_batch(samples, run_sample)


class AnalysisRunner(_ExecutorBackedBatchMixin):
    """Analysis batch runner backed by :class:`BatchExecutor`."""

    def run_batch(self, samples: Sequence[T] | Iterable[T], analyze_sample: Callable[[T], R]) -> list[RunRecord[R]]:
        return self._run_batch(samples, analyze_sample)


class PatchTester(_ExecutorBackedBatchMixin):
    """Patch test batch runner backed by :class:`BatchExecutor`."""

    def test_batch(self, patches: Sequence[T] | Iterable[T], test_patch: Callable[[T], R]) -> list[RunRecord[R]]:
        return self._run_batch(patches, test_patch)


class CompressionEngine(_ExecutorBackedBatchMixin):
    """Compression batch engine backed by :class:`BatchExecutor`."""

    def compress_batch(self, samples: Sequence[T] | Iterable[T], compress_sample: Callable[[T], R]) -> list[RunRecord[R]]:
        return self._run_batch(samples, compress_sample)


class FewShotOptimizationEngine(_ExecutorBackedBatchMixin):
    """Few-shot optimization batch engine backed by :class:`BatchExecutor`."""

    def optimize_batch(self, samples: Sequence[T] | Iterable[T], optimize_sample: Callable[[T], R]) -> list[RunRecord[R]]:
        return self._run_batch(samples, optimize_sample)
