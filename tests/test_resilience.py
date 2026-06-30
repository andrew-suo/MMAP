from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def test_runner_restore_keeps_checkpoint_iteration_and_stage(tmp_path):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_checkpoint")
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
    first._save_checkpoint(
        current_phase="prompt_optimization",
        current_step_id="prompt_iter_002",
        current_iteration=2,
        current_stage="iteration_completed",
        event="prompt_iteration_completed",
    )

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    resumed._restore_from_checkpoint()

    assert resumed.checkpoint.current_iteration == 2
    assert resumed.checkpoint.current_stage == "iteration_completed"

    checkpoint = json.loads((Path(config.run.output_dir) / "checkpoint.json").read_text())
    assert checkpoint["current_iteration"] == 2
    assert checkpoint["current_stage"] == "iteration_completed"


def test_runner_resume_duration_uses_original_start_time(tmp_path, monkeypatch):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_duration")
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

    run_start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    run_end = run_start + timedelta(seconds=5)
    first.run_summary.start_time = run_start.isoformat()
    first.run_summary.status = "running"
    first._save_final_artifacts()

    time_values = iter([run_end.timestamp() - 1, run_end.timestamp()])
    iso_values = iter([(run_end - timedelta(seconds=1)).isoformat(), run_end.isoformat()])

    monkeypatch.setattr(MMAPRunner, "_time_seconds", lambda self: next(time_values))
    monkeypatch.setattr(MMAPRunner, "_now_utc_isoformat", lambda self: next(iso_values))

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    summary = resumed.run(resume=True)

    assert summary.status == "completed"
    assert summary.start_time == run_start.isoformat()
    assert summary.end_time == run_end.isoformat()
    assert summary.duration_seconds == 5.0


def test_runner_persists_failed_status_and_can_resume(tmp_path, monkeypatch):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_failed")
    config.run.use_mock = True
    config.prompt_optimization.rounds = 0
    config.fewshot_optimization.rounds = 0

    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fail_end = start + timedelta(seconds=3)
    fail_times = iter([start.timestamp(), fail_end.timestamp()])
    fail_isos = iter([start.isoformat(), fail_end.isoformat()])

    monkeypatch.setattr(MMAPRunner, "_time_seconds", lambda self: next(fail_times))
    monkeypatch.setattr(MMAPRunner, "_now_utc_isoformat", lambda self: next(fail_isos))
    monkeypatch.setattr(
        MMAPRunner,
        "_run_prompt_structuring",
        lambda self: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    with pytest.raises(RuntimeError, match="boom"):
        runner.run()

    output_dir = Path(config.run.output_dir)
    checkpoint = json.loads((output_dir / "checkpoint.json").read_text())
    summary_data = json.loads((output_dir / "run_summary.json").read_text())
    assert checkpoint["run_status"] == "failed"
    assert checkpoint["last_error"] == "boom"
    assert summary_data["status"] == "failed"
    assert summary_data["duration_seconds"] == 3.0
    run_plan = json.loads((output_dir / "run_plan.json").read_text())
    assert run_plan["current_step_index"] == 0
    assert run_plan["steps"][0]["status"] == "pending"

    monkeypatch.undo()

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    summary = resumed.run(resume=True)

    assert summary.status == "completed"


def test_runner_resume_records_run_resumed_event_without_erasing_checkpoint_fields(tmp_path):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_events_restore")
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
    first._save_checkpoint(
        current_phase="prompt_optimization",
        current_step_id="prompt_iter_002",
        current_iteration=2,
        current_stage="iteration_completed",
        event="prompt_iteration_completed",
    )

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    resumed._restore_from_checkpoint()

    events_path = Path(config.run.output_dir) / "resume_events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events[-1]["event"] == "run_resumed"
    assert events[-1]["checkpoint"]["current_iteration"] == 2
    assert events[-1]["checkpoint"]["current_stage"] == "iteration_completed"


def test_runner_resume_keeps_run_plan_progress_and_emits_expected_events(tmp_path, monkeypatch):
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.run.output_dir = str(tmp_path / "resume_events_full")
    config.run.use_mock = True
    config.prompt_optimization.rounds = 0
    config.fewshot_optimization.rounds = 0

    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    fail_end = start + timedelta(seconds=2)
    fail_times = iter([start.timestamp(), fail_end.timestamp()])
    fail_isos = iter([start.isoformat(), fail_end.isoformat()])
    with monkeypatch.context() as m:
        m.setattr(MMAPRunner, "_time_seconds", lambda self: next(fail_times))
        m.setattr(MMAPRunner, "_now_utc_isoformat", lambda self: next(fail_isos))
        m.setattr(
            MMAPRunner,
            "_run_prompt_structuring",
            lambda self: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        runner = MMAPRunner(
            config=config,
            extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
            analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
            use_mock=True,
        )
        with pytest.raises(RuntimeError, match="boom"):
            runner.run()

    resumed = MMAPRunner(
        config=config,
        extraction_prompt_path=REPO_ROOT / "prompts" / "extraction.txt",
        analysis_prompt_path=REPO_ROOT / "prompts" / "analysis.txt",
        use_mock=True,
    )
    summary = resumed.run(resume=True)

    assert summary.status == "completed"
    assert resumed.run_plan.current_step_index == len(resumed.run_plan.steps)

    run_plan = json.loads((Path(config.run.output_dir) / "run_plan.json").read_text(encoding="utf-8"))
    assert run_plan["current_step_index"] == len(run_plan["steps"])
    assert run_plan["steps"][0]["status"] == "completed"

    events_path = Path(config.run.output_dir) / "resume_events.jsonl"
    events = [
        json.loads(line)["event"]
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "run_started" in events
    assert "run_failed" in events
    assert "run_resumed" in events
    assert events[-1] == "run_completed"


def test_refactored_config_round_trips_full_fewshot_sampler_fields():
    config = load_config(REPO_ROOT / "configs" / "smoke.yaml")
    config.fewshot_optimization.sampler.type = "difficulty_frequency"
    config.fewshot_optimization.sampler.difficulty_weight = 0.11
    config.fewshot_optimization.sampler.frequency_weight = 0.22
    config.fewshot_optimization.sampler.random_noise_scale = 0.33
    config.fewshot_optimization.sampler.error_ratio = 0.44
    config.fewshot_optimization.sampler.success_ratio = 0.55
    config.fewshot_optimization.sampler.low_frequency_ratio = 0.66
    config.fewshot_optimization.sampler.fallback_to_difficulty_frequency = False
    config.fewshot_optimization.sampler.lookback_window = 7
    config.fewshot_optimization.sampler.mixed_fail_ratio = 0.12
    config.fewshot_optimization.sampler.hard_fail_ratio = 0.13
    config.fewshot_optimization.sampler.unknown_ratio = 0.14
    config.fewshot_optimization.sampler.easy_ratio = 0.15
    config.fewshot_optimization.sampler.trajectory_weight = 0.16
    config.fewshot_optimization.sampler.apex_prompt_type = "analysis"

    restored = type(config).from_dict(config.to_dict())
    sampler = restored.fewshot_optimization.sampler

    assert sampler.type == "difficulty_frequency"
    assert sampler.difficulty_weight == 0.11
    assert sampler.frequency_weight == 0.22
    assert sampler.random_noise_scale == 0.33
    assert sampler.error_ratio == 0.44
    assert sampler.success_ratio == 0.55
    assert sampler.low_frequency_ratio == 0.66
    assert sampler.fallback_to_difficulty_frequency is False
    assert sampler.lookback_window == 7
    assert sampler.mixed_fail_ratio == 0.12
    assert sampler.hard_fail_ratio == 0.13
    assert sampler.unknown_ratio == 0.14
    assert sampler.easy_ratio == 0.15
    assert sampler.trajectory_weight == 0.16
    assert sampler.apex_prompt_type == "analysis"
