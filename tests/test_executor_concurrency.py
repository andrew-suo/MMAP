from __future__ import annotations

from tests._compat import candidate_modules, find_symbol

EXECUTOR_MODULES = candidate_modules(
    "mmap.executor",
    "mmap.concurrent_executor",
    "mmap.runtime.executor",
    "mmap_engine.executor",
    "src.executor",
)


def test_concurrent_executor_returns_results_in_stable_input_order() -> None:
    run_concurrent = find_symbol(EXECUTOR_MODULES, "run_concurrent", "execute_concurrently", "stable_concurrent_map")

    def task(value: int) -> str:
        return f"done-{value}"

    results = run_concurrent([3, 1, 2], task, max_workers=3)

    assert [item["input"] for item in results] == [3, 1, 2]
    assert [item["result"] for item in results] == ["done-3", "done-1", "done-2"]


def test_concurrent_executor_isolates_task_exceptions() -> None:
    run_concurrent = find_symbol(EXECUTOR_MODULES, "run_concurrent", "execute_concurrently", "stable_concurrent_map")

    def task(value: int) -> str:
        if value == 2:
            raise RuntimeError("boom")
        return f"ok-{value}"

    results = run_concurrent([1, 2, 3], task, max_workers=3, return_exceptions=True)

    assert [item["input"] for item in results] == [1, 2, 3]
    assert results[0]["result"] == "ok-1"
    assert results[1]["error"]["type"] == "RuntimeError"
    assert "boom" in results[1]["error"]["message"]
    assert results[2]["result"] == "ok-3"
