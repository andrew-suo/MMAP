"""Trace2Skill-inspired prompt optimization improvements."""

from __future__ import annotations

from mmap_optimizer.executors.patch_generation_executor import PatchGenerationExecutor
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.patch.types import ExtractionPatch
from mmap_optimizer.prompt.output_repair import parse_model_json_output
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt
from mmap_optimizer.stages.extraction_prompt_optimization import EvalRecord, ExtractionPromptOptimizationStage


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


class _ApplyExecutor:
    def apply(self, prompt, patches):
        changed = bool(patches)
        return prompt, type("Report", (), {"changed": changed})()


class _ExtractionExecutor:
    def __init__(self, statuses_by_patch_count):
        self.statuses_by_patch_count = statuses_by_patch_count

    def execute(self, prompt, batch, sample_set):
        statuses = self.statuses_by_patch_count.get(
            getattr(self, "current_patch_count", 0),
            ["wrong" for _ in batch.sample_ids],
        )
        from mmap_optimizer.stages.extraction_prompt_optimization import ExtractionResult

        return [
            ExtractionResult(sample_id=sid, raw_output="{}", parsed_output={}, status=status)
            for sid, status in zip(batch.sample_ids, statuses)
        ]


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


def test_candidate_selection_prefers_highest_scoring_patch_set():
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
        candidate_selection_enabled=True,
        candidate_count=2,
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

    selected = stage._select_candidate_patch_set()

    assert [p.id for p in selected] == ["p1", "p2"]
    assert stage.candidate_validation_report.selected_candidate_id == "candidate_1"
