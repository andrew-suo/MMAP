from __future__ import annotations

import time
from collections import defaultdict

from mmap_optimizer.orchestration.executor import (
    BatchExecutor,
    CompressionEngine,
    ExecutionConfig,
    PromptTestRunner,
)


def test_concurrent_exception_isolated_to_single_sample() -> None:
    executor = BatchExecutor(ExecutionConfig(max_workers=3))

    def worker(sample: int) -> int:
        if sample == 2:
            raise ValueError("bad sample")
        return sample * 10

    records = executor.run([1, 2, 3], worker)

    assert [record.success for record in records] == [True, False, True]
    assert [record.output for record in records] == [10, None, 30]
    assert records[1].error_type == "ValueError"
    assert records[1].retry_count == 0


def test_output_order_is_stable_despite_concurrent_completion_order() -> None:
    executor = BatchExecutor(ExecutionConfig(max_workers=3))

    def worker(sample: int) -> int:
        time.sleep({1: 0.03, 2: 0.01, 3: 0.02}[sample])
        return sample

    records = executor.run([1, 2, 3], worker)

    assert [record.index for record in records] == [0, 1, 2]
    assert [record.output for record in records] == [1, 2, 3]


def test_retry_count_is_honored_and_recorded() -> None:
    executor = BatchExecutor(ExecutionConfig(max_workers=2, retry_count=2))
    attempts: defaultdict[int, int] = defaultdict(int)

    def worker(sample: int) -> int:
        attempts[sample] += 1
        if sample == 1 and attempts[sample] < 3:
            raise RuntimeError("try again")
        return sample

    records = executor.run([1, 2], worker)

    assert [record.success for record in records] == [True, True]
    assert records[0].retry_count == 2
    assert records[0].output == 1
    assert attempts[1] == 3
    assert attempts[2] == 1


def test_timeout_is_recorded_as_sample_failure() -> None:
    executor = BatchExecutor(ExecutionConfig(max_workers=2, timeout_seconds=0.01))

    def worker(sample: int) -> int:
        if sample == 1:
            time.sleep(0.05)
        return sample

    records = executor.run([1, 2], worker)

    assert [record.success for record in records] == [False, True]
    assert records[0].error_type == "TimeoutError"
    assert records[0].retry_count == 0
    assert records[1].output == 2


def test_named_batch_components_delegate_to_executor() -> None:
    prompt_records = PromptTestRunner(ExecutionConfig(max_workers=2)).run_batch(["a", "b"], str.upper)
    compression_records = CompressionEngine(ExecutionConfig(max_workers=2)).compress_batch(["aa"], len)

    assert [record.output for record in prompt_records] == ["A", "B"]
    assert compression_records[0].output == 2
