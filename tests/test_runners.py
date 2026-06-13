from __future__ import annotations

from mmap_optimizer.config import ExecutionConfig
from mmap_optimizer.orchestration.runners import AnalysisRunner, PatchTester, PromptTestRunner


def test_prompt_test_runner_uses_executor_and_keeps_stable_order() -> None:
    runner = PromptTestRunner(
        model=lambda prompt: prompt.upper(),
        execution_config=ExecutionConfig(mode="thread_pool", max_workers=2),
    )

    results = runner.run([
        {"sample_id": "b", "prompt": "bee"},
        {"sample_id": "a", "prompt": "ant"},
    ])

    assert [result["sample_id"] for result in results] == ["a", "b"]
    assert [result["response"] for result in results] == ["ANT", "BEE"]


def test_analysis_runner_isolates_sample_errors() -> None:
    def analyzer(sample: dict[str, str], model):
        if sample["sample_id"] == "bad":
            raise ValueError("cannot analyze")
        return model(sample["text"])

    runner = AnalysisRunner(
        model=lambda text: f"analysis:{text}",
        analyzer=analyzer,
        execution_config=ExecutionConfig(mode="thread_pool", max_workers=2),
    )

    results = runner.run([
        {"sample_id": "ok", "text": "x"},
        {"sample_id": "bad", "text": "y"},
    ])

    assert results[0]["sample_id"] == "bad"
    assert results[0]["exception_type"] == "ValueError"
    assert results[1]["analysis"] == "analysis:x"


def test_patch_tester_accepts_custom_tester() -> None:
    runner = PatchTester(
        model=lambda prompt: prompt,
        tester=lambda sample, model: model(sample["patch"]),
        execution_config={"execution": {"mode": "thread_pool", "max_workers": 1}},
    )

    assert runner.run([{"sample_id": "p1", "patch": "diff"}])[0]["test_result"] == "diff"
