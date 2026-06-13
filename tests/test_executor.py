from __future__ import annotations

import time

from mmap_optimizer.config import ExecutionConfig
from mmap_optimizer.orchestration.executor import SampleExecutor


def test_thread_pool_output_order_is_stable_by_sample_id() -> None:
    samples = [
        {"sample_id": "c", "delay": 0.01},
        {"sample_id": "a", "delay": 0.03},
        {"sample_id": "b", "delay": 0.02},
    ]
    executor = SampleExecutor(ExecutionConfig(mode="thread_pool", max_workers=3))

    outcomes = executor.map(
        samples,
        lambda sample: (time.sleep(sample["delay"]), sample["sample_id"])[1],
    )

    assert [outcome.sample_id for outcome in outcomes] == ["a", "b", "c"]
    assert [outcome.value for outcome in outcomes] == ["a", "b", "c"]


def test_single_task_failure_does_not_affect_other_tasks() -> None:
    samples = [{"sample_id": "a"}, {"sample_id": "bad"}, {"sample_id": "c"}]
    executor = SampleExecutor(ExecutionConfig(mode="thread_pool", max_workers=2))

    def task(sample: dict[str, str]) -> str:
        if sample["sample_id"] == "bad":
            raise RuntimeError("boom")
        return sample["sample_id"].upper()

    outcomes = executor.map(samples, task)

    assert [(outcome.sample_id, outcome.ok, outcome.value) for outcome in outcomes if outcome.ok] == [
        ("a", True, "A"),
        ("c", True, "C"),
    ]
    failed = [outcome for outcome in outcomes if not outcome.ok]
    assert len(failed) == 1
    assert failed[0].sample_id == "bad"
    assert failed[0].exception_type == "RuntimeError"
    assert "boom" in (failed[0].error or "")


def test_max_workers_one_is_equivalent_to_serial() -> None:
    samples = [{"sample_id": "b"}, {"sample_id": "a"}, {"sample_id": "c"}]

    serial = SampleExecutor(ExecutionConfig(mode="serial", max_workers=1)).map(
        samples,
        lambda sample: sample["sample_id"] * 2,
    )
    one_worker = SampleExecutor(ExecutionConfig(mode="thread_pool", max_workers=1)).map(
        samples,
        lambda sample: sample["sample_id"] * 2,
    )

    assert one_worker == serial


def test_falls_back_to_input_order_when_samples_have_no_id() -> None:
    executor = SampleExecutor(ExecutionConfig(mode="thread_pool", max_workers=3))

    outcomes = executor.map([3, 1, 2], lambda value: value)

    assert [outcome.value for outcome in outcomes] == [3, 1, 2]


def test_thread_pool_timeout_is_reported_per_sample() -> None:
    samples = [{"sample_id": "slow", "delay": 0.05}, {"sample_id": "fast", "delay": 0.001}]
    executor = SampleExecutor(
        ExecutionConfig(mode="thread-pool", max_workers=2, timeout_seconds=0.01)
    )

    outcomes = executor.map(
        samples,
        lambda sample: (time.sleep(sample["delay"]), sample["sample_id"])[1],
    )

    by_id = {outcome.sample_id: outcome for outcome in outcomes}
    assert by_id["fast"].ok
    assert by_id["slow"].timed_out
    assert by_id["slow"].exception_type == "TimeoutError"
