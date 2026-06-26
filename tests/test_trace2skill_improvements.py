"""Trace2Skill-inspired prompt optimization improvements."""

from __future__ import annotations

from mmap_optimizer.executors.patch_generation_executor import PatchGenerationExecutor
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.patch.types import ExtractionPatch
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


def test_sample_patch_memory_round_trips_and_trims_by_prompt_type():
    from mmap_optimizer.data.sample import SamplePatchMemoryItem, SampleState

    state = SampleState(sample_id="s1")
    for idx in range(25):
        state.add_patch_memory(
            SamplePatchMemoryItem(
                sample_id="s1",
                prompt_type="extraction",
                iteration=idx,
                patch_id=f"p{idx}",
                target_section_id="task",
                operation_type="append_to_section",
                final_decision="accepted",
            )
        )
    state.add_patch_memory(
        SamplePatchMemoryItem(
            sample_id="s1",
            prompt_type="analysis",
            iteration=1,
            patch_id="a1",
            target_section_id="task",
            operation_type="append_to_section",
            final_decision="toxic",
        )
    )

    restored = SampleState.from_dict(state.to_dict())

    extraction_memory = restored.get_patch_memory("extraction")
    analysis_memory = restored.get_patch_memory("analysis")
    assert len(extraction_memory) == 20
    assert extraction_memory[0].patch_id == "p5"
    assert len(analysis_memory) == 1
    assert analysis_memory[0].final_decision == "toxic"


def test_patch_generation_user_message_includes_current_sample_history_only():
    from mmap_optimizer.data.sample import SamplePatchMemoryItem, SampleSet, SampleSpec
    from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

    sample_set = SampleSet()
    sample_set.add_spec(SampleSpec(id="s1", input={}, ground_truth={}))
    sample_set.add_spec(SampleSpec(id="s2", input={}, ground_truth={}))
    sample_set.states["s1"].add_patch_memory(
        SamplePatchMemoryItem(
            sample_id="s1",
            prompt_type="extraction",
            iteration=1,
            patch_id="p1",
            target_section_id="task",
            operation_type="append_to_section",
            direction="copy visible value exactly",
            content="Copy visible value exactly.",
            final_decision="accepted",
            transition="fixed",
            toxicity="safe",
        )
    )
    sample_set.states["s2"].add_patch_memory(
        SamplePatchMemoryItem(
            sample_id="s2",
            prompt_type="extraction",
            iteration=1,
            patch_id="p2",
            target_section_id="task",
            operation_type="append_to_section",
            direction="unrelated direction",
            content="Do something unrelated.",
            final_decision="toxic",
            transition="broken",
            toxicity="toxic",
        )
    )
    executor = PatchGenerationExecutor()

    message = executor._build_patch_generation_user_message(
        prompt_type="extraction",
        extraction_result=ExtractionResult("s1", "{}", {}, "wrong"),
        current_prompt=_prompt(),
        sample_set=sample_set,
    )

    assert "# Sample Patch History" in message
    assert "copy visible value exactly" in message
    assert "unrelated direction" not in message


class _ApplyExecutor:
    def apply(self, prompt, patches):
        changed = bool(patches)
        return prompt, type("Report", (), {"changed": changed})()


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


def test_extraction_stage_records_patch_memory_after_regression_test():
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

    memory = sample_set.states["s1"].get_patch_memory("extraction")
    assert len(memory) == 1
    assert memory[0].patch_id == "p1"
    assert memory[0].final_decision == "accepted"
    assert memory[0].transition == "fixed"
    assert memory[0].toxicity == "safe"


def test_analysis_stage_records_patch_memory_after_regression_test():
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

    memory = sample_set.states["s1"].get_patch_memory("analysis")
    assert len(memory) == 1
    assert memory[0].patch_id == "a1"
    assert memory[0].final_decision == "accepted"
    assert memory[0].transition == "fixed"
    assert memory[0].toxicity == "safe"
