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


def test_semantic_patch_translation_failure_is_recorded_for_sample_trajectory():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )
    stage.patch_generation_executor = PatchGenerationExecutor()
    stage.patch_generation_executor.translation_failed_attempts = [
        {
            "attempt_id": "semantic::s1",
            "patch_id": "",
            "source_sample_ids": ["s1"],
            "target_section_id": "unknown",
            "operation_type": "append_to_section",
            "direction": "bad section hint",
            "content": "Some patch",
            "rationale": "reason",
            "generation_status": "generated",
            "validation_status": "translation_failed",
            "merge_status": "not_merged",
            "final_decision": "rejected",
            "rejection_reason": "TRANSLATION_FAILED:UNKNOWN_SECTION",
            "metadata": {"translation_status": "failed"},
        }
    ]

    stage._record_generated_patch_attempts()

    attempt = sample_set.states["s1"].get_optimization_trajectory("extraction")[0].patch_attempts[0]
    assert attempt.attempt_id == "semantic::s1"
    assert attempt.stage == "translated"
    assert attempt.stage_status == "failed"
    assert attempt.validation_status == "translation_failed"
    assert attempt.rejection_reason == "TRANSLATION_FAILED:UNKNOWN_SECTION"


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


def test_sample_optimization_trajectory_keeps_event_sequence_and_latest_rendering():
    from mmap_optimizer.data.sample import SampleOptimizationTrajectory, SamplePatchAttempt
    from mmap_optimizer.prompt.sample_trajectory import SampleTrajectoryRenderer

    trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="extraction",
        iteration=2,
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p1",
            prompt_type="extraction",
            iteration=2,
            attempt_id="s1::p1",
            stage="validation",
            stage_status="validated",
            final_decision="unknown",
        )
    )
    trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p1",
            prompt_type="extraction",
            iteration=2,
            attempt_id="s1::p1",
            stage="finalized",
            stage_status="accepted",
            final_decision="accepted",
            regression_effect="fixed",
        )
    )

    assert len(trajectory.patch_attempts) == 2
    latest = trajectory.latest_patch_attempts()[0]
    assert latest.stage == "finalized"
    assert latest.final_decision == "accepted"
    rendered = SampleTrajectoryRenderer()._render_trajectory(trajectory)
    assert any("stage=finalized" in line for line in rendered)


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


def test_patch_generation_extraction_message_includes_related_analysis_context():
    from mmap_optimizer.data.sample import (
        SampleOptimizationTrajectory,
        SampleSet,
        SampleSpec,
    )
    from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    analysis_trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="analysis",
        iteration=3,
        base_status="fail",
        final_status="fail",
        sample_transition="unchanged_wrong",
        analysis_summary={"error_reason": "missing visible value"},
    )
    sample_set.states["s1"].add_optimization_trajectory(analysis_trajectory)
    executor = PatchGenerationExecutor()

    message = executor._build_patch_generation_user_message(
        prompt_type="extraction",
        extraction_result=ExtractionResult("s1", "{}", {}, "wrong"),
        current_prompt=_prompt(),
        sample_set=sample_set,
    )

    assert "# Sample Optimization Trajectory" in message
    assert "related_analysis=" in message
    assert "missing visible value" in message


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

    def evaluate(self, extraction_result, ground_truth):
        return EvalRecord(
            sample_id=extraction_result.sample_id,
            extraction_result_id=extraction_result.sample_id,
            status=extraction_result.status,
            correct=extraction_result.status == "correct",
        )


class _StatusExtractionExecutor:
    def __init__(self, statuses):
        self.statuses = dict(statuses)

    def execute(self, prompt, batch, sample_set):
        return [
            ExtractionResult(
                sample_id=sample_id,
                raw_output="{}",
                parsed_output={},
                status=self.statuses.get(sample_id, "correct"),
            )
            for sample_id in batch.sample_ids
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


def test_extraction_base_metrics_do_not_double_update_evaluation_state():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec
    from mmap_optimizer.executors.evaluation_executor import EvaluationExecutor

    sample_set = SampleSet()
    sample_set.add_spec(
        SampleSpec(id="s1", input={}, ground_truth={"result": "EXPECTED"})
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
        evaluation_executor=EvaluationExecutor(),
    )
    stage.base_extraction_results = [
        ExtractionResult("s1", '{"result":"ACTUAL"}', {"result": "ACTUAL"}, "correct")
    ]

    stage._step2_compute_base_metrics()

    state = sample_set.states["s1"]
    assert state.error_count == 1
    assert state.error_ema == 0.3
    assert state.difficulty_score == 0.3
    assert state.last_extraction_status == "wrong"


def test_extraction_base_metrics_updates_state_for_non_mutating_evaluator():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
        evaluation_executor=_EvaluationExecutor(),
    )
    stage.base_extraction_results = [
        ExtractionResult("s1", "{}", {}, "wrong")
    ]

    stage._step2_compute_base_metrics()

    state = sample_set.states["s1"]
    assert state.error_count == 1
    assert state.error_ema == 0.3
    assert state.difficulty_score == 0.3
    assert state.last_extraction_status == "wrong"


def test_extraction_final_transition_ignores_rejected_toxic_trial_patch():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace
    from mmap_optimizer.executors.toxicity_executor import ToxicityTestExecutor

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
        traces=[
            SampleTrace("s1", "prompt_optimization", 7, selected=True),
            SampleTrace("s2", "prompt_optimization", 7, selected=True),
        ],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 7, ["s1", "s2"], "test"),
        iteration=7,
        patch_apply_executor=_ApplyExecutor(),
        extraction_executor=_StatusExtractionExecutor({"s2": "wrong"}),
        evaluation_executor=_EvaluationExecutor(),
        toxicity_test_executor=ToxicityTestExecutor(),
    )
    stage.base_eval_records = [
        EvalRecord("s1", "s1", "wrong", False),
        EvalRecord("s2", "s2", "correct", True),
    ]
    stage.patched_eval_records = [
        EvalRecord("s1", "s1", "correct", True),
        EvalRecord("s2", "s2", "wrong", False),
    ]
    stage.base_extraction_results = [
        ExtractionResult("s1", "{}", {}, "wrong"),
        ExtractionResult("s2", "{}", {}, "correct"),
    ]
    stage.initial_merged_patches = [
        ExtractionPatch("p-toxic", "task", "append_to_section", "A", "r", ["s1"])
    ]

    stage._step7_regression_and_toxicity_test()
    stage._step9_final_test_and_metrics()

    s1_outcome = sample_set.states["s1"].get_outcome_history("extraction")[0]
    s2_outcome = sample_set.states["s2"].get_outcome_history("extraction")[0]
    assert stage.accepted_prompt is None
    assert s1_outcome.transition == "unchanged_wrong"
    assert s1_outcome.status == "fail"
    assert s2_outcome.transition == "unchanged_correct"
    assert s2_outcome.status == "pass"
    assert sample_set.states["s2"].historical_broken_count == 0
    attempt = sample_set.states["s1"].get_optimization_trajectory("extraction")[0].latest_patch_attempts()[0]
    assert attempt.regression_effect == "fixed"
    assert attempt.final_decision == "toxic"


def test_extraction_historical_fixed_count_uses_final_accepted_result_only():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )
    stage.base_eval_records = [EvalRecord("s1", "s1", "wrong", False)]
    stage.base_extraction_results = [ExtractionResult("s1", "{}", {}, "wrong")]
    stage.patched_eval_records = [EvalRecord("s1", "s1", "correct", True)]
    stage.initial_merged_patches = [
        ExtractionPatch("p1", "task", "append_to_section", "A", "r", ["s1"])
    ]
    stage.toxic_patches = stage.initial_merged_patches.copy()

    stage._set_extraction_trace_transition(
        trace=stage._get_or_create_iteration_trace("s1"),
        fixed_sample_ids=["s1"],
        broken_sample_ids=[],
        unchanged_wrong_ids=[],
    )
    assert sample_set.states["s1"].historical_fixed_count == 0

    stage._record_extraction_outcome_history()

    assert sample_set.states["s1"].historical_fixed_count == 0


def test_sample_trace_keeps_extraction_and_analysis_transitions_separate():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
        traces=[SampleTrace(sample_id="s1", phase="prompt_optimization", iteration=1, selected=True)],
    )
    batch = SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test")

    extraction_stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=batch,
        iteration=1,
    )
    extraction_stage._set_extraction_trace_transition(
        trace=sample_set.traces[0],
        fixed_sample_ids=["s1"],
        broken_sample_ids=[],
        unchanged_wrong_ids=[],
    )

    analysis_stage = AnalysisPromptOptimizationStage(
        analysis_prompt=_prompt(),
        extraction_results=[],
        base_analysis_results=[],
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_prompt=_prompt(),
    )
    analysis_stage._set_analysis_trace_transition(
        trace=sample_set.traces[0],
        fixed_sample_ids=[],
        broken_sample_ids=["s1"],
        unchanged_wrong_ids=[],
    )

    assert sample_set.traces[0].extraction_transition == "fixed"
    assert sample_set.traces[0].analysis_transition == "broken"


def test_extraction_analysis_results_are_recorded_on_analysis_trajectory_only():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )
    stage.base_extraction_results = [ExtractionResult("s1", "{}", {}, "wrong")]

    stage._step3_analyze_results()

    extraction_trajectories = sample_set.states["s1"].get_optimization_trajectory("extraction")
    analysis_trajectory = sample_set.states["s1"].get_optimization_trajectory("analysis")[0]
    assert extraction_trajectories == []
    assert analysis_trajectory.analysis_summary["analysis_correct"] is True


def test_analysis_base_metrics_populate_analysis_trajectory_for_all_samples():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    stage = AnalysisPromptOptimizationStage(
        analysis_prompt=_prompt(),
        extraction_results=[ExtractionResult("s1", "{}", {}, "wrong")],
        base_analysis_results=[
            AnalysisResult(
                sample_id="s1",
                judgement={},
                analysis_correct=False,
                error_reason="missing value",
            )
        ],
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
        extraction_prompt=_prompt(),
    )

    stage._step1_compute_base_metrics()

    trajectory = sample_set.states["s1"].get_optimization_trajectory("analysis")[0]
    assert trajectory.base_status == "fail"
    assert trajectory.base_raw_status == "wrong"
    assert trajectory.analysis_summary["error_reason"] == "missing value"


def test_extraction_outcome_history_normalizes_status_and_preserves_raw_status():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
        traces=[
            SampleTrace(
                sample_id="s1",
                phase="prompt_optimization",
                iteration=1,
                selected=True,
                participated_in_extraction=True,
                extraction_transition="unchanged_wrong",
            )
        ],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )
    stage.base_extraction_results = [ExtractionResult("s1", "{}", {}, "invalid")]
    stage._record_extraction_outcome_history()

    trajectory = sample_set.states["s1"].get_optimization_trajectory("extraction")[0]
    outcome = sample_set.states["s1"].get_outcome_history("extraction")[0]
    assert trajectory.base_status == "fail"
    assert trajectory.base_raw_status == "invalid"
    assert trajectory.final_status == "fail"
    assert trajectory.final_raw_status == "invalid"
    assert outcome.status == "fail"
    assert outcome.metadata["raw_status"] == "invalid"


def test_extraction_outcome_history_leaves_missing_final_samples_unknown():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace

    sample_set = SampleSet(
        specs={
            "s1": SampleSpec(id="s1", input={}, ground_truth={}),
            "s2": SampleSpec(id="s2", input={}, ground_truth={}),
        },
        states={
            "s1": SampleState(sample_id="s1"),
            "s2": SampleState(sample_id="s2"),
        },
        traces=[
            SampleTrace(sample_id="s1", phase="prompt_optimization", iteration=1, selected=True),
            SampleTrace(sample_id="s2", phase="prompt_optimization", iteration=1, selected=True),
        ],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1", "s2"], "test"),
        iteration=1,
    )
    stage.base_eval_records = [
        EvalRecord("s1", "s1", "wrong", False),
        EvalRecord("s2", "s2", "correct", True),
    ]
    stage.final_eval_records = [
        EvalRecord("s1", "s1", "correct", True),
    ]
    stage.base_extraction_results = [
        ExtractionResult("s1", "{}", {}, "wrong"),
        ExtractionResult("s2", "{}", {}, "correct"),
    ]
    stage.final_extraction_results = [
        ExtractionResult("s1", "{}", {}, "correct"),
    ]

    stage._record_extraction_outcome_history()

    s1_trace = sample_set.get_traces_for_iteration("prompt_optimization", 1)[0]
    s2_trace = sample_set.get_traces_for_iteration("prompt_optimization", 1)[1]
    s2_outcome = sample_set.states["s2"].get_outcome_history("extraction")[0]

    assert s1_trace.final_extraction_status == "correct"
    assert s1_trace.final_extraction_result_id == "s1"
    assert s2_trace.final_extraction_status is None
    assert s2_trace.final_extraction_result_id is None
    assert s2_outcome.status == "unknown"
    assert s2_outcome.transition == "unknown"


def test_extraction_outcome_history_uses_specific_rejected_patch_decision():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )
    stage.base_extraction_results = [ExtractionResult("s1", "{}", {}, "wrong")]
    stage.ineffective_patches = [
        ExtractionPatch("p1", "task", "append_to_section", "A", "r", ["s1"])
    ]

    stage._record_extraction_outcome_history()

    outcome = sample_set.states["s1"].get_outcome_history("extraction")[0]
    assert outcome.patch_decision == "ineffective"


def test_extraction_stage_updates_existing_trace_instead_of_duplicating():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace

    sample_set = SampleSet(
        specs={"s1": SampleSpec(id="s1", input={}, ground_truth={})},
        states={"s1": SampleState(sample_id="s1")},
        traces=[SampleTrace(sample_id="s1", phase="prompt_optimization", iteration=1, selected=True)],
    )
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=sample_set,
        batch=SampleBatch("b1", "prompt_optimization", 1, ["s1"], "test"),
        iteration=1,
    )

    stage._step1_execute_extraction()

    traces = sample_set.get_traces_for_iteration("prompt_optimization", 1)
    assert len(traces) == 1
    assert traces[0].participated_in_extraction is True
    assert traces[0].base_extraction_status == "correct"


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


def test_merge_executor_rejects_invalid_provenance_output(monkeypatch):
    from mmap_optimizer.patch.tree_reduce import ParallelPatchMerger

    def _invalid_merge(self, patches, prompt_structure):
        return [
            {
                "id": "merged_new",
                "source_patch_ids": ["unknown"],
                "target_section": "task",
                "op": "append_to_section",
                "content": "x",
                "rationale": "y",
                "source_sample_ids": ["s1"],
            }
        ]

    monkeypatch.setattr(ParallelPatchMerger, "merge", _invalid_merge)
    patch = ExtractionPatch("p1", "task", "append_to_section", "A", "r", ["s1"])
    merged, report = MergeExecutor(model_client=object()).merge(
        patches=[patch],
        prompt=_prompt(),
        sample_set=None,
    )

    assert merged == []
    assert patch.rejection_reason == "MERGE_PROVENANCE_INVALID"
    assert report.invalid_provenance_patch_ids == ["unknown"]


def test_merge_executor_repairs_missing_provenance_for_single_group_output(monkeypatch):
    from mmap_optimizer.model.client import ModelResponse

    class _MissingProvenanceClient:
        def complete(self, messages, model_config=None, response_format=None):
            return ModelResponse(
                raw_output='[{"target_section":"task","op":"append_to_section","content":"merged content","rationale":"merged rationale"}]'
            )

    patch = ExtractionPatch("p1", "task", "append_to_section", "A", "r", ["s1"])
    merged, report = MergeExecutor(model_client=_MissingProvenanceClient()).merge(
        patches=[patch],
        prompt=_prompt(),
        sample_set=None,
    )

    assert len(merged) == 1
    assert merged[0].metadata["source_patch_ids"] == ["p1"]
    assert merged[0].source_sample_ids == ["s1"]
    assert report.invalid_provenance_patch_ids == []
    assert report.merged_patch_count == 1


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


def test_analysis_final_transition_ignores_rejected_trial_patch():
    from mmap_optimizer.data.sample import SampleBatch, SampleSet, SampleSpec, SampleState, SampleTrace
    from mmap_optimizer.patch.types import AnalysisPatch

    sample_set = SampleSet(
        specs={sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in ("s1", "s2")},
        states={sid: SampleState(sample_id=sid) for sid in ("s1", "s2")},
        traces=[
            SampleTrace("s1", "prompt_optimization", 8, selected=True),
            SampleTrace("s2", "prompt_optimization", 8, selected=True),
        ],
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
        batch=SampleBatch("b1", "prompt_optimization", 8, ["s1", "s2"], "test"),
        iteration=8,
        patch_apply_executor=_ApplyExecutor(),
        analysis_executor=None,
    )
    stage.patched_analysis_results = [
        AnalysisResult("s1", {}, True),
        AnalysisResult("s2", {}, False),
    ]
    stage.trial_prompt = _prompt()
    stage.initial_merged_patches = [
        AnalysisPatch("a-toxic", "task", "append_to_section", "A", "r", ["s1"])
    ]

    stage._step6_regression_and_toxicity_test()
    stage._step8_final_test_and_metrics()

    s1_outcome = sample_set.states["s1"].get_outcome_history("analysis")[0]
    s2_outcome = sample_set.states["s2"].get_outcome_history("analysis")[0]
    assert stage.accepted_prompt is None
    assert s1_outcome.transition == "unchanged_wrong"
    assert s1_outcome.status == "fail"
    assert s2_outcome.transition == "unchanged_correct"
    assert s2_outcome.status == "pass"
    attempt = sample_set.states["s1"].get_optimization_trajectory("analysis")[0].latest_patch_attempts()[0]
    assert attempt.regression_effect == "fixed"
    assert attempt.final_decision == "toxic"


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
