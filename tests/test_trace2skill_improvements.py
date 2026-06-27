"""Trace2Skill-inspired prompt optimization improvements."""

from __future__ import annotations

from mmap_optimizer.executors.patch_generation_executor import PatchGenerationExecutor
from mmap_optimizer.executors.merge_executor import MergeExecutor
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.patch.types import AnalysisPatch, ExtractionPatch, PatchMergeReport
from mmap_optimizer.prompt.output_repair import parse_model_json_output
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt
from mmap_optimizer.stages.analysis_prompt_optimization import AnalysisPromptOptimizationStage
from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionPromptOptimizationStage,
    ExtractionResult,
)


def _prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="prompt1",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="task",
                title="Task",
                level=1,
                content="Extract the answer.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\nExtract the answer.",
        version=1,
    )


def test_parse_model_json_output_reports_local_repair_status():
    result = parse_model_json_output("{result: 'OK',}")

    assert result.status == "locally_repaired"
    assert result.parsed == {"result": "OK"}
    assert result.failure_reason is None


def test_parse_model_json_output_reports_failed_status_without_client():
    result = parse_model_json_output("not json", model_client=None)

    assert result.status == "failed"
    assert result.parsed is None
    assert result.failure_reason


def test_semantic_patch_draft_translates_to_strict_patch():
    executor = PatchGenerationExecutor(model_client=MockModelClient())
    draft = executor._build_semantic_draft(
        "extraction",
        {
            "id": "semantic_1",
            "target_section_hint": "task",
            "change_intent": "tighten answer extraction",
            "proposed_text": "When a value is visible, copy it exactly.",
            "rationale": "The sample missed a visible value.",
        },
    )
    suggestion = executor._translate_semantic_draft_to_suggestion(draft, _prompt())
    patch = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion=suggestion,
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )

    assert draft.status == "translated"
    assert patch.target_section_id == "task"
    assert patch.operation_type == "append_to_section"
    assert patch.metadata["semantic_draft_id"] == "semantic_1"
    assert patch.metadata["translation_status"] == "translated"


def test_sample_optimization_trajectory_round_trips_and_renders():
    from mmap_optimizer.data.sample import (
        SampleOptimizationTrajectory,
        SamplePatchAttempt,
        SampleSet,
        SampleSpec,
        SampleState,
    )
    from mmap_optimizer.prompt.sample_trajectory import SampleTrajectoryRenderer

    state = SampleState(sample_id="s1")
    trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="analysis",
        iteration=2,
        base_status="fail",
        final_status="pass",
        sample_transition="fixed",
        analysis_summary={"error_reason": "misjudged missing value"},
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="a1",
            prompt_type="analysis",
            iteration=2,
            target_section_id="task",
            operation_type="append_to_section",
            direction="tighten missing value checks",
            content="Treat missing visible values as incorrect.",
            final_decision="accepted",
            toxicity_status="tested_safe",
        )
    )
    state.add_optimization_trajectory(trajectory)
    restored = SampleState.from_dict(state.to_dict())

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    sample_set.states["s1"] = restored
    rendered = SampleTrajectoryRenderer().render(sample_set, "s1", "analysis")

    assert restored.get_optimization_trajectory("analysis")[0].sample_transition == "fixed"
    assert "tighten missing value checks" in rendered
    assert "decision=accepted" in rendered


def test_patch_generation_user_message_includes_current_sample_history_only():
    from mmap_optimizer.data.sample import (
        SampleOptimizationTrajectory,
        SamplePatchAttempt,
        SampleSet,
        SampleSpec,
    )
    from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    sample_set.add_spec(SampleSpec(id="s2", input={}, ground_truth={}))
    trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="extraction",
        iteration=1,
        sample_transition="fixed",
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p1",
            prompt_type="extraction",
            iteration=1,
            target_section_id="task",
            operation_type="append_to_section",
            direction="copy visible value exactly",
            content="Copy visible value exactly.",
            final_decision="accepted",
            regression_effect="fixed",
            toxicity_status="tested_safe",
        )
    )
    sample_set.states["s1"].add_optimization_trajectory(trajectory)
    unrelated = SampleOptimizationTrajectory(
        sample_id="s2",
        prompt_type="extraction",
        iteration=1,
        sample_transition="broken",
    )
    unrelated.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p2",
            prompt_type="extraction",
            iteration=1,
            target_section_id="task",
            operation_type="append_to_section",
            direction="unrelated direction",
            content="Do something unrelated.",
            final_decision="toxic",
            regression_effect="broken",
            toxicity_status="toxic",
        )
    )
    sample_set.states["s2"].add_optimization_trajectory(unrelated)
    executor = PatchGenerationExecutor()

    message = executor._build_patch_generation_user_message(
        prompt_type="extraction",
        extraction_result=ExtractionResult("s1", "{}", {}, "wrong"),
        current_prompt=_prompt(),
        sample_set=sample_set,
    )

    assert "# Sample Optimization Trajectory" in message
    assert "copy visible value exactly" in message
    assert "unrelated direction" not in message


def test_patch_generation_uses_sample_trajectory():
    from mmap_optimizer.data.sample import (
        SampleOptimizationTrajectory,
        SamplePatchAttempt,
        SampleSet,
        SampleSpec,
    )
    from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="extraction",
        iteration=2,
        base_status="fail",
        final_status="fail",
        sample_transition="unchanged_wrong",
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="new",
            prompt_type="extraction",
            iteration=2,
            direction="trajectory direction",
            final_decision="ineffective",
        )
    )
    sample_set.states["s1"].add_optimization_trajectory(trajectory)
    executor = PatchGenerationExecutor()

    message = executor._build_patch_generation_user_message(
        prompt_type="extraction",
        extraction_result=ExtractionResult("s1", "{}", {}, "wrong"),
        current_prompt=_prompt(),
        sample_set=sample_set,
    )

    assert "trajectory direction" in message


def test_analysis_and_reflection_messages_include_sample_trajectory():
    from mmap_optimizer.data.sample import (
        SampleOptimizationTrajectory,
        SamplePatchAttempt,
        SampleSet,
        SampleSpec,
    )
    from mmap_optimizer.executors.analysis_executor import AnalysisExecutor

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={"image": "x"}, ground_truth={"result": "OK"}))
    trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="analysis",
        iteration=1,
        base_status="fail",
        final_status="fail",
        sample_transition="unchanged_wrong",
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="a1",
            prompt_type="analysis",
            iteration=1,
            direction="avoid accepting missing values",
            final_decision="ineffective",
        )
    )
    sample_set.states["s1"].add_optimization_trajectory(trajectory)
    executor = AnalysisExecutor(model_client=MockModelClient())
    extraction_result = ExtractionResult("s1", "{}", {}, "wrong")
    analysis_result = AnalysisResult("s1", {"judgement": {"is_correct": True}}, False)

    analysis_messages, _ = executor._build_analysis_messages(
        _prompt(),
        _prompt(),
        extraction_result,
        sample_set.specs["s1"],
        sample_set,
    )
    reflection_messages, _ = executor._build_reflection_messages(
        _prompt(),
        extraction_result,
        analysis_result,
        sample_set.specs["s1"],
        sample_set,
    )

    assert "Sample Optimization Trajectory" in analysis_messages[1]["content"]
    assert "avoid accepting missing values" in analysis_messages[1]["content"]
    assert "Sample Optimization Trajectory" in reflection_messages[1]["content"]
    assert "avoid accepting missing values" in reflection_messages[1]["content"]


class _ApplyExecutor:
    def apply(self, prompt, patches):
        changed = bool(patches)
        return prompt, type("Report", (), {"changed": changed})()


class _NoChangeApplyExecutor:
    def apply(self, prompt, patches):
        return prompt, type("Report", (), {"changed": False})()


class _EvaluationExecutor:
    def evaluate_batch(self, results, sample_set):
        return [
            EvalRecord(
                sample_id=r.sample_id,
                extraction_result_id=r.sample_id,
                status=r.status,
                correct=r.status == "correct",
            )
            for r in results
        ]


def test_extraction_stage_applies_merged_patch_set_directly():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
    )
    batch = SampleBatch(
        id="b1",
        phase="prompt_optimization",
        iteration=1,
        sampler_name="test",
        sample_ids=["s1", "s2"],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        patch_apply_executor=_ApplyExecutor(),
        extraction_executor=None,
        evaluation_executor=_EvaluationExecutor(),
    )
    stage.base_eval_records = [
        EvalRecord("s1", "s1", "wrong", False),
        EvalRecord("s2", "s2", "correct", True),
    ]
    stage.initial_merged_patches = [
        ExtractionPatch("p1", "task", "append_to_section", "A", "r", ["s1"]),
        ExtractionPatch("p2", "task", "append_to_section", "B", "r", ["s2"]),
    ]

    class Executor:
        def execute(self, prompt, batch, sample_set):
            from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

            statuses = ["correct", "correct"]
            return [
                ExtractionResult(sample_id=sid, raw_output="{}", parsed_output={}, status=status)
                for sid, status in zip(batch.sample_ids, statuses)
            ]

    stage.extraction_executor = Executor()

    stage._step6_apply_and_test()

    assert [p.id for p in stage.initial_merged_patches] == ["p1", "p2"]
    assert len(stage.patched_extraction_results) == 2


def test_extraction_stage_records_patch_attempt_after_regression_test():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
    )
    batch = SampleBatch(
        id="b1",
        phase="prompt_optimization",
        iteration=2,
        sampler_name="test",
        sample_ids=["s1", "s2"],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=batch,
        iteration=2,
        patch_apply_executor=_ApplyExecutor(),
        extraction_executor=None,
        evaluation_executor=_EvaluationExecutor(),
    )
    stage.base_eval_records = [
        EvalRecord("s1", "s1", "wrong", False),
        EvalRecord("s2", "s2", "correct", True),
    ]
    stage.patched_eval_records = [
        EvalRecord("s1", "s1", "correct", True),
        EvalRecord("s2", "s2", "correct", True),
    ]
    stage.trial_prompt = _prompt()
    stage.initial_merged_patches = [
        ExtractionPatch(
            "p1",
            "task",
            "append_to_section",
            "Copy visible value exactly.",
            "copy visible value exactly",
            ["s1"],
        )
    ]

    stage._step7_regression_and_toxicity_test()

    trajectories = sample_set.states["s1"].get_optimization_trajectory("extraction")
    assert len(trajectories) == 1
    attempt = trajectories[0].patch_attempts[0]
    assert attempt.patch_id == "p1"
    assert attempt.final_decision == "accepted"
    assert attempt.regression_effect == "fixed"
    assert attempt.toxicity_status in {"not_tested", "tested_safe"}


def test_merge_executor_filters_post_merge_validation_failed_patch():
    from mmap_optimizer.data.sample import SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
    )
    invalid_patch = ExtractionPatch(
        "p-invalid",
        "missing_section",
        "append_to_section",
        "This cannot be applied.",
        "bad target",
        ["s1"],
    )

    merged, report = MergeExecutor().merge(
        patches=[invalid_patch],
        prompt=_prompt(),
        sample_set=sample_set,
    )

    assert merged == []
    assert invalid_patch.status == "rejected"
    assert invalid_patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED"
    assert report.merged_patch_ids == []
    assert report.dropped_patch_ids == ["p-invalid"]


def test_extraction_stage_records_merge_dropped_patch_attempt():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 4, ["s1", "s2"], "test"),
        iteration=4,
    )
    kept = ExtractionPatch("p-kept", "task", "append_to_section", "A", "r", ["s1"])
    dropped = ExtractionPatch("p-dropped", "task", "append_to_section", "B", "r", ["s2"])
    stage.validated_patches = [kept, dropped]
    stage.initial_merged_patches = [kept]
    stage.initial_merge_report = PatchMergeReport(
        id="merge",
        input_patch_count=2,
        merged_patch_count=1,
        conflict_count=0,
        input_patch_ids=["p-kept", "p-dropped"],
        merged_patch_ids=["p-kept"],
        dropped_patch_ids=["p-dropped"],
    )

    stage._record_initial_merge_outcomes()

    kept_attempt = sample_set.states["s1"].get_optimization_trajectory("extraction")[0].patch_attempts[0]
    dropped_attempt = sample_set.states["s2"].get_optimization_trajectory("extraction")[0].patch_attempts[0]
    assert kept_attempt.merge_status == "initial_merged"
    assert kept_attempt.final_decision == "unknown"
    assert dropped_attempt.merge_status == "not_merged"
    assert dropped_attempt.final_decision == "dropped"


def test_extraction_apply_no_change_marks_patch_ineffective_and_stops_consumption():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 5, ["s1"], "test"),
        iteration=5,
        patch_apply_executor=_NoChangeApplyExecutor(),
    )
    stage.initial_merged_patches = [
        ExtractionPatch("p-no-change", "task", "append_to_section", "", "empty", ["s1"])
    ]

    stage._step6_apply_and_test()
    stage._step7_regression_and_toxicity_test()

    patch = stage.initial_merged_patches[0]
    assert patch.status == "rejected"
    assert patch.rejection_reason == "APPLY_NO_CHANGE"
    assert stage.accepted_prompt is None
    assert stage.final_merged_patches == []
    assert stage.metrics.no_progress is True
    attempt = sample_set.states["s1"].get_optimization_trajectory("extraction")[0].patch_attempts[0]
    assert attempt.final_decision == "ineffective"
    assert attempt.merge_status == "initial_merged"
    assert attempt.toxicity_status == "not_tested"


def test_analysis_stage_records_patch_attempt_after_regression_test():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState
    from mmap_optimizer.patch.types import AnalysisPatch

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
    )
    batch = SampleBatch(
        id="b1",
        phase="prompt_optimization",
        iteration=3,
        sampler_name="test",
        sample_ids=["s1", "s2"],
    )
    stage = AnalysisPromptOptimizationStage(
        analysis_prompt=_prompt(),
        extraction_results=[
            ExtractionResult("s1", "{}", {}, "wrong"),
            ExtractionResult("s2", "{}", {}, "correct"),
        ],
        base_analysis_results=[
            AnalysisResult("s1", {}, False),
            AnalysisResult("s2", {}, True),
        ],
        sample_set=sample_set,
        batch=batch,
        iteration=3,
        patch_apply_executor=_ApplyExecutor(),
        analysis_executor=None,
    )
    stage.patched_analysis_results = [
        AnalysisResult("s1", {}, True),
        AnalysisResult("s2", {}, True),
    ]
    stage.trial_prompt = _prompt()
    stage.initial_merged_patches = [
        AnalysisPatch(
            "a1",
            "task",
            "append_to_section",
            "Judge missing visible values as incorrect.",
            "tighten analysis judgement",
            ["s1"],
        )
    ]

    stage._step6_regression_and_toxicity_test()

    trajectories = sample_set.states["s1"].get_optimization_trajectory("analysis")
    assert len(trajectories) == 1
    attempt = trajectories[0].patch_attempts[0]
    assert attempt.patch_id == "a1"
    assert attempt.final_decision == "accepted"
    assert attempt.regression_effect == "fixed"
    assert attempt.toxicity_status in {"not_tested", "tested_safe"}


def test_analysis_apply_no_change_marks_patch_ineffective_and_stops_consumption():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
    )
    stage = AnalysisPromptOptimizationStage(
        analysis_prompt=_prompt(),
        extraction_results=[ExtractionResult("s1", "{}", {}, "wrong")],
        base_analysis_results=[AnalysisResult("s1", {}, False)],
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 6, ["s1"], "test"),
        iteration=6,
        patch_apply_executor=_NoChangeApplyExecutor(),
    )
    stage.initial_merged_patches = [
        AnalysisPatch("a-no-change", "task", "append_to_section", "", "empty", ["s1"])
    ]

    stage._step5_apply_and_test()
    stage._step6_regression_and_toxicity_test()

    patch = stage.initial_merged_patches[0]
    assert patch.status == "rejected"
    assert patch.rejection_reason == "APPLY_NO_CHANGE"
    assert stage.accepted_prompt is None
    assert stage.final_merged_patches == []
    assert stage.metrics.no_progress is True
    attempt = sample_set.states["s1"].get_optimization_trajectory("analysis")[0].patch_attempts[0]
    assert attempt.final_decision == "ineffective"
    assert attempt.merge_status == "initial_merged"
    assert attempt.toxicity_status == "not_tested"
