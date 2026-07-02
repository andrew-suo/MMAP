from __future__ import annotations

from pathlib import Path

from mmap_optimizer.data.sample import (
    SampleBatch,
    SampleOptimizationTrajectory,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.phases.fewshot_optimization import (
    FewshotConfig,
    FewshotMetrics,
    FewshotOptimizationPhase,
)
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt
from mmap_optimizer.stages.extraction_prompt_optimization import EvalRecord, ExtractionResult


def _prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="prompt_1",
        prompt_type="extraction",
        sections=[PromptSection(id="s1", title="Task", level=1, content="Extract")],
        raw_markdown="# Task\nExtract",
    )


def _sample_set() -> SampleSet:
    sample_set = SampleSet()
    for idx in range(1, 7):
        sample_id = f"s{idx}"
        sample_set.add_spec(
            SampleSpec(
                id=sample_id,
                input={"text": sample_id},
                ground_truth={"result": f"label_{idx % 2}"},
            )
        )
        state = SampleState(sample_id=sample_id)
        state.difficulty_score = 0.1 * idx
        state.last_extraction_status = "correct"
        sample_set.states[sample_id] = state
    sample_set.states["s2"].last_extraction_status = "wrong"
    sample_set.states["s2"].error_count = 2
    sample_set.states["s3"].historical_fixed_count = 1
    sample_set.states["s4"].difficulty_score = 0.9
    sample_set.states["s5"].last_extraction_status = "invalid"
    return sample_set


def _batch(sample_ids: list[str]) -> SampleBatch:
    return SampleBatch(
        id="b1",
        phase="fewshot_optimization",
        iteration=1,
        sample_ids=sample_ids,
        sampler_name="test",
    )


def test_split_batches_prefers_disjoint_selection_and_validation(tmp_path: Path):
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=2, batch_size=6),
        extraction_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
    )

    selection_batch, validation_batch, notes = phase._split_batches(_batch(["s1", "s2", "s3", "s4", "s5", "s6"]))

    assert selection_batch.sample_ids
    assert validation_batch.sample_ids
    assert set(selection_batch.sample_ids).isdisjoint(set(validation_batch.sample_ids))
    assert "selection_validation_overlap" not in notes


def test_select_difficult_samples_uses_candidate_pool_diversity(tmp_path: Path):
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=4, batch_size=6, candidate_pool_size=6),
        extraction_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
    )

    examples = phase._select_difficult_samples(_batch(["s1", "s2", "s3", "s4", "s5", "s6"]), FewshotMetrics())

    candidate_types = {example.metadata.get("candidate_type") for example in examples}
    assert len(examples) == 4
    assert "canonical_positive" in candidate_types
    assert "boundary" in candidate_types or "historical_misclassified" in candidate_types
    assert "high_frequency_error" in candidate_types or "canonical_negative" in candidate_types


def test_selected_examples_use_history_based_rationale_when_trajectory_exists(tmp_path: Path):
    sample_set = _sample_set()
    sample_set.states["s3"].add_optimization_trajectory(
        SampleOptimizationTrajectory(
            sample_id="s3",
            prompt_type="analysis",
            iteration=1,
            analysis_summary={"error_reason": "The label depends on a narrow boundary cue."},
        )
    )
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=3, batch_size=4, candidate_pool_size=4, enable_rationale=True),
        extraction_prompt=_prompt(),
        sample_set=sample_set,
        output_dir=tmp_path,
    )

    examples = phase._select_difficult_samples(_batch(["s1", "s2", "s3", "s4"]), FewshotMetrics())
    example_by_id = {example.sample_id: example for example in examples}

    assert example_by_id["s3"].rationale_source == "prompt_optimization_history"
    assert "boundary" in example_by_id["s3"].rationale_text.lower()


def test_selected_examples_use_inline_rationale_without_history(tmp_path: Path):
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=3, batch_size=4, candidate_pool_size=4, enable_rationale=True),
        extraction_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
    )

    examples = phase._select_difficult_samples(_batch(["s1", "s2", "s4", "s5"]), FewshotMetrics())

    assert any(example.rationale_source == "fewshot_inline_generation" for example in examples)


def test_fewshot_stage_rejects_no_delta_candidate(tmp_path: Path, monkeypatch):
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=2, batch_size=4, min_accuracy_delta=0.01),
        extraction_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
    )
    batch = _batch(["s1", "s2", "s3", "s4"])

    monkeypatch.setattr(
        phase,
        "_execute_extraction",
        lambda _batch: [ExtractionResult(sample_id=sid, raw_output="", parsed_output={"result": "x"}, status="correct") for sid in _batch.sample_ids],
    )
    monkeypatch.setattr(
        phase,
        "_execute_extraction_with_fewshot",
        lambda _batch, _examples: [ExtractionResult(sample_id=sid, raw_output="", parsed_output={"result": "x"}, status="correct") for sid in _batch.sample_ids],
    )

    def fake_base_metrics(_batch, _results, metrics):
        metrics.base_accuracy = 0.5
        metrics.base_correct_count = 1
        metrics.base_wrong_count = 1
        return [
            EvalRecord(sample_id=_batch.sample_ids[0], extraction_result_id="r1", status="correct", correct=True, details={}),
            EvalRecord(sample_id=_batch.sample_ids[1], extraction_result_id="r2", status="wrong", correct=False, details={}),
        ]

    def fake_final_metrics(_batch, _results, metrics):
        metrics.final_accuracy = 0.5
        metrics.final_correct_count = 1
        metrics.final_wrong_count = 1
        return [
            EvalRecord(sample_id=_batch.sample_ids[0], extraction_result_id="r1", status="correct", correct=True, details={}),
            EvalRecord(sample_id=_batch.sample_ids[1], extraction_result_id="r2", status="wrong", correct=False, details={}),
        ]

    monkeypatch.setattr(phase, "_compute_base_metrics", fake_base_metrics)
    monkeypatch.setattr(phase, "_compute_final_metrics", fake_final_metrics)

    metrics, _, _, _, _, _, _, _, _, _, _, decision, _ = phase._fewshot_optimization_stage(1, batch)

    assert metrics.accepted is False
    assert metrics.decision_reason == "no_delta"
    assert decision["accepted"] is False


def test_fewshot_stage_rejects_regression_and_writes_audit_artifacts(tmp_path: Path, monkeypatch):
    phase = FewshotOptimizationPhase(
        config=FewshotConfig(slot_count=2, batch_size=4, min_accuracy_delta=0.0, require_no_regression=True),
        extraction_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
    )
    batch = _batch(["s1", "s2", "s3", "s4"])
    monkeypatch.setattr(phase, "_sampling_stage", lambda iteration: batch)

    monkeypatch.setattr(
        phase,
        "_execute_extraction",
        lambda _batch: [ExtractionResult(sample_id=sid, raw_output="", parsed_output={"result": "x"}, status="correct") for sid in _batch.sample_ids],
    )
    monkeypatch.setattr(
        phase,
        "_execute_extraction_with_fewshot",
        lambda _batch, _examples: [ExtractionResult(sample_id=sid, raw_output="", parsed_output={"result": "x"}, status="correct") for sid in _batch.sample_ids],
    )

    def fake_base_metrics(_batch, _results, metrics):
        metrics.base_accuracy = 1.0
        metrics.base_correct_count = 2
        return [
            EvalRecord(sample_id=_batch.sample_ids[0], extraction_result_id="r1", status="correct", correct=True, details={}),
            EvalRecord(sample_id=_batch.sample_ids[1], extraction_result_id="r2", status="correct", correct=True, details={}),
        ]

    def fake_final_metrics(_batch, _results, metrics):
        metrics.final_accuracy = 0.5
        metrics.final_correct_count = 1
        metrics.final_wrong_count = 1
        return [
            EvalRecord(sample_id=_batch.sample_ids[0], extraction_result_id="r1", status="wrong", correct=False, details={}),
            EvalRecord(sample_id=_batch.sample_ids[1], extraction_result_id="r2", status="correct", correct=True, details={}),
        ]

    monkeypatch.setattr(phase, "_compute_base_metrics", fake_base_metrics)
    monkeypatch.setattr(phase, "_compute_final_metrics", fake_final_metrics)

    result = phase._run_iteration(1)
    fewshot_dir = tmp_path / "fewshot_optimization" / "iteration_1" / "fewshot"

    assert result.metrics.accepted is False
    assert result.metrics.decision_reason == "regression_detected"
    assert (fewshot_dir / "candidate_pool.jsonl").exists()
    assert (fewshot_dir / "candidate_scores.jsonl").exists()
    assert (fewshot_dir / "fewshot_rationale_records.jsonl").exists()
    assert (fewshot_dir / "fewshot_rationale_trajectory.jsonl").exists()
    assert (fewshot_dir / "validation_report.json").exists()
    assert (fewshot_dir / "decision.json").exists()
