from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mmap_optimizer.core.config import load_config
from mmap_optimizer.core.runner import MMAPRunner
from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState
from mmap_optimizer.executors.extraction_executor import ExtractionExecutor
from mmap_optimizer.model.client import ModelResponse
from mmap_optimizer.model.retry import (
    ConsecutiveModelFailureError,
    FailurePolicyConfig,
    RetryConfig,
    RetryingModelClient,
    SampleFailureTracker,
)
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt


REPO_ROOT = Path(__file__).resolve().parent.parent


class FlakyClient:
    def __init__(self, failures_before_success: int):
        self.failures_before_success = failures_before_success
        self.calls = 0

    def complete(self, messages, model_config=None, response_format=None):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise TimeoutError("temporary failure")
        return ModelResponse(raw_output='{"ok": true}')

    def complete_multimodal(self, messages, assets, model_config=None, response_format=None):
        return self.complete(messages, model_config, response_format)


class SampleAwareClient:
    def __init__(self, failing_sample_ids: set[str]):
        self.failing_sample_ids = failing_sample_ids

    def complete(self, messages, model_config=None, response_format=None):
        return ModelResponse(raw_output='{"result": "OK"}')

    def complete_multimodal(self, messages, assets, model_config=None, response_format=None):
        content = "\n".join(str(m.get("content", "")) for m in messages)
        for sample_id in self.failing_sample_ids:
            if sample_id in content:
                raise RuntimeError(f"failed {sample_id}")
        return ModelResponse(raw_output='{"result": "OK"}')


def _prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="s1",
                title="Task",
                level=1,
                content="Extract result.",
            )
        ],
        raw_markdown="# Task\nExtract result.",
    )


def _sample_set(sample_ids: list[str]) -> tuple[SampleSet, SampleBatch]:
    specs = {
        sid: SampleSpec(id=sid, input={}, ground_truth={"result": "OK"})
        for sid in sample_ids
    }
    states = {sid: SampleState(sample_id=sid) for sid in sample_ids}
    batch = SampleBatch(
        id="b1",
        phase="prompt_optimization",
        iteration=1,
        sample_ids=sample_ids,
        sampler_name="test",
    )
    return SampleSet(specs=specs, states=states), batch


def test_retrying_model_client_retries_then_succeeds(tmp_path):
    client = FlakyClient(failures_before_success=2)
    wrapped = RetryingModelClient(
        client,
        retry_config=RetryConfig(
            max_attempts=3,
            initial_backoff_seconds=0,
            jitter_seconds=0,
        ),
        failure_log_path=tmp_path / "failures.jsonl",
    )

    response = wrapped.complete([{"role": "user", "content": "hi"}])

    assert json.loads(response.raw_output) == {"ok": True}
    assert client.calls == 3
    assert len((tmp_path / "failures.jsonl").read_text().splitlines()) == 2


def test_retrying_model_client_raises_after_three_failures(tmp_path):
    client = FlakyClient(failures_before_success=10)
    wrapped = RetryingModelClient(
        client,
        retry_config=RetryConfig(
            max_attempts=3,
            initial_backoff_seconds=0,
            jitter_seconds=0,
        ),
        failure_log_path=tmp_path / "failures.jsonl",
    )

    with pytest.raises(TimeoutError):
        wrapped.complete([{"role": "user", "content": "hi"}])

    assert client.calls == 3
    assert len((tmp_path / "failures.jsonl").read_text().splitlines()) == 3


def test_extraction_skips_single_sample_failure():
    sample_set, batch = _sample_set(["sample_1", "sample_2"])
    executor = ExtractionExecutor(
        SampleAwareClient({"sample_1"}),
        failure_policy=FailurePolicyConfig(max_consecutive_sample_failures=3),
        sample_failure_tracker=SampleFailureTracker(3),
    )

    results = executor.execute(_prompt(), batch, sample_set)

    assert [r.sample_id for r in results] == ["sample_1", "sample_2"]
    assert results[0].status == "invalid"
    assert results[0].error_details
    assert results[1].status == "correct"


def test_extraction_aborts_after_three_consecutive_sample_failures():
    sample_set, batch = _sample_set(["sample_1", "sample_2", "sample_3"])
    executor = ExtractionExecutor(
        SampleAwareClient({"sample_1", "sample_2", "sample_3"}),
        failure_policy=FailurePolicyConfig(max_consecutive_sample_failures=3),
        sample_failure_tracker=SampleFailureTracker(3),
    )

    with pytest.raises(ConsecutiveModelFailureError):
        executor.execute(_prompt(), batch, sample_set)


def test_runner_resume_skips_completed_prompt_structuring(tmp_path, monkeypatch):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_run")
    config.run.use_mock = True
    config.prompt_optimization.rounds = 0
    config.fewshot_optimization.rounds = 0

    first = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    first._save_initial_artifacts()
    first._run_prompt_structuring()

    def fail_if_called(*args: Any, **kwargs: Any):
        raise AssertionError("prompt structuring should not run during resume")

    monkeypatch.setattr("mmap_optimizer.phases.prompt_structuring.PromptStructuringPhase.run", fail_if_called)

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    summary = resumed.run(resume=True)

    assert summary.status == "completed"
    assert resumed.run_plan.current_step_index >= 1
    checkpoint = json.loads((Path(config.run.output_dir) / "checkpoint.json").read_text())
    assert checkpoint["run_status"] == "completed"
