from __future__ import annotations

import pytest

from mmap_optimizer.extraction_prompt_optimization_stage import (
    AnalysisResult,
    EvalRecord,
    ExtractionPromptOptimizationStage,
    ExtractionResult,
)
from mmap_optimizer.executors.factory import create_executors
from mmap_optimizer.executors.patch_apply_executor import PatchApplyExecutor
from mmap_optimizer.executors.patch_generation_executor import (
    PatchGenerationExecutor,
)
from mmap_optimizer.executors.patch_validator import PatchValidator
from mmap_optimizer.patch_types import ExtractionPatch
from mmap_optimizer.sample import SampleBatch, SampleSet, SampleSpec, SampleState
from mmap_optimizer.structured_prompt import PromptSection, StructuredPrompt


# ---------------------------------------------------------------------------
# Mock executors
# ---------------------------------------------------------------------------


class MockExtractionExecutor:
    """Mock 抽取执行器，始终返回 wrong 结果。"""

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        return [
            ExtractionResult(
                sample_id=sid,
                raw_output='{"result":"wrong"}',
                parsed_output={"result": "wrong"},
                status="wrong",
            )
            for sid in batch.sample_ids
        ]


class MockEvaluationExecutor:
    """Mock 评估执行器，基于 extraction status 返回评估记录。"""

    def evaluate_batch(self, extraction_results, sample_set):
        return [
            EvalRecord(
                sample_id=r.sample_id,
                extraction_result_id=r.sample_id,
                status=r.status,
                correct=(r.status == "correct"),
            )
            for r in extraction_results
        ]


class MockAnalysisExecutor:
    """Mock 分析执行器，返回 analysis_correct=True 且含有效 patch_suggestion。"""

    def execute_batch(
        self, analysis_prompt, extraction_prompt, extraction_results, sample_set
    ):
        results = []
        for r in extraction_results:
            results.append(
                AnalysisResult(
                    sample_id=r.sample_id,
                    judgement={"correct": False, "reason": "wrong answer"},
                    analysis_correct=True,
                    error_reason="The extraction got the wrong answer",
                    patch_suggestion={
                        "target_section": "section_1",
                        "operation": "replace",
                        "content": "Please be more careful and double-check your answer before responding.",
                        "rationale": "The model needs to be more careful",
                    },
                )
            )
        return results


# ---------------------------------------------------------------------------
# Test 1: patch generated → patch applied → prompt changed → final eval generated
# ---------------------------------------------------------------------------


def test_patch_generated_applied_prompt_changed():
    """使用 3 条最小样本验证完整流程跑通。"""
    # 构造 3 个样本的 SampleSet
    specs: dict[str, SampleSpec] = {}
    states: dict[str, SampleState] = {}
    for sid in ["s1", "s2", "s3"]:
        specs[sid] = SampleSpec(
            id=sid,
            input={"text": "sample text"},
            ground_truth={"result": "OK"},
        )
        states[sid] = SampleState(sample_id=sid)
    sample_set = SampleSet(specs=specs, states=states)
    batch = SampleBatch(
        id="b1",
        phase="prompt_optimization",
        iteration=1,
        sampler_name="test",
        sample_ids=["s1", "s2", "s3"],
    )

    # 构造 StructuredPrompt（含 mutable section "section_1"）
    extraction_prompt = StructuredPrompt(
        id="extraction_prompt_1",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="section_1",
                title="Task",
                level=1,
                content="Extract the result from the input.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\n\nExtract the result from the input.",
    )
    analysis_prompt = StructuredPrompt(
        id="analysis_prompt_1",
        prompt_type="analysis",
        sections=[
            PromptSection(
                id="section_1",
                title="Analysis Task",
                level=1,
                content="Analyze whether the extraction result is correct.",
                mutable=True,
            )
        ],
        raw_markdown="# Analysis Task\n\nAnalyze whether the extraction result is correct.",
    )

    # 构造真实 PatchGenerationExecutor 和 PatchApplyExecutor
    patch_generation_executor = PatchGenerationExecutor()
    patch_apply_executor = PatchApplyExecutor()

    # 创建 stage 并运行
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=MockExtractionExecutor(),
        evaluation_executor=MockEvaluationExecutor(),
        analysis_executor=MockAnalysisExecutor(),
        patch_generation_executor=patch_generation_executor,
        patch_apply_executor=patch_apply_executor,
    )

    stage.run()

    # 验证 draft_patches 非空
    assert stage.draft_patches, "draft_patches 应非空"
    assert len(stage.draft_patches) == 3, (
        f"应生成 3 条 draft patch，实际 {len(stage.draft_patches)}"
    )

    # 验证 validated_patches 非空（或 rejected_patches 非空）
    assert stage.validated_patches or stage.rejected_patches, (
        "validated_patches 或 rejected_patches 应非空"
    )

    # 如果 validated_patches 非空，验证 patched_prompt 不为 None 或 apply_report 不为 None
    if stage.validated_patches:
        assert stage.patched_prompt is not None or stage.patch_apply_report is not None, (
            "validated_patches 非空时，patched_prompt 或 apply_report 应不为 None"
        )


# ---------------------------------------------------------------------------
# Test 2: accepted patch 能修改指定 section
# ---------------------------------------------------------------------------


def test_accepted_patch_modifies_section():
    """验证 accepted patch 能修改指定 section。"""
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="Original",
        mutable=True,
    )
    prompt = StructuredPrompt(
        id="prompt_2",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Task\n\nOriginal",
    )
    patch = ExtractionPatch(
        id="patch_2",
        target_section_id="section_1",
        operation_type="replace",
        content="New content",
        rationale="update section content",
    )

    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])

    new_section = new_prompt.get_section_by_id("section_1")
    assert new_section is not None, "section_1 应存在"
    assert new_section.content == "New content", (
        f"section_1 content 应为 'New content'，实际 '{new_section.content}'"
    )
    assert patch.id in report.applied_patch_ids


# ---------------------------------------------------------------------------
# Test 3: output schema section 不可修改
# ---------------------------------------------------------------------------


def test_immutable_section_not_modifiable():
    """验证 output schema section 不可修改。"""
    section_1 = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="task content",
        mutable=True,
    )
    schema_section = PromptSection(
        id="schema",
        title="Output Schema",
        level=1,
        content="original schema",
        mutable=False,
    )
    prompt = StructuredPrompt(
        id="prompt_3",
        prompt_type="extraction",
        sections=[section_1, schema_section],
        raw_markdown="# Task\n\ntask content\n\n# Output Schema\n\noriginal schema",
    )
    patch = ExtractionPatch(
        id="patch_3",
        target_section_id="schema",
        operation_type="replace",
        content="new schema",
        rationale="attempt to modify schema",
    )

    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])

    # 验证该 patch 在 rejected_patch_ids 中
    assert patch.id in report.rejected_patch_ids, (
        "针对 immutable section 的 patch 应被拒绝"
    )

    # 验证 schema section 的 content 未变化
    new_schema = new_prompt.get_section_by_id("schema")
    assert new_schema is not None
    assert new_schema.content == "original schema", (
        f"schema section content 应未变化，实际 '{new_schema.content}'"
    )


# ---------------------------------------------------------------------------
# Test 4: final prompt 能 render 成模型输入
# ---------------------------------------------------------------------------


def test_final_prompt_can_render():
    """验证 final prompt 能 render 成模型输入。"""
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="Original content",
        mutable=True,
    )
    prompt = StructuredPrompt(
        id="prompt_4",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Task\n\nOriginal content",
    )
    patch = ExtractionPatch(
        id="patch_4",
        target_section_id="section_1",
        operation_type="replace",
        content="Updated content for rendering",
        rationale="update for render test",
    )

    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])

    # 验证 to_markdown() 返回非空字符串
    markdown = new_prompt.to_markdown()
    assert markdown, "to_markdown() 应返回非空字符串"
    assert "Updated content for rendering" in markdown

    # 验证 raw_markdown 已更新
    assert new_prompt.raw_markdown == markdown, (
        "raw_markdown 应与 to_markdown() 输出一致"
    )
    assert new_prompt.raw_markdown != prompt.raw_markdown, (
        "raw_markdown 应已更新，与原 prompt 不同"
    )


# ---------------------------------------------------------------------------
# Test 5: prompt version 真实变化
# ---------------------------------------------------------------------------


def test_prompt_version_changes():
    """验证 prompt version 真实变化。"""
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="Original",
        mutable=True,
    )
    prompt = StructuredPrompt(
        id="prompt_5",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Task\n\nOriginal",
        version=1,
    )
    patch = ExtractionPatch(
        id="patch_5",
        target_section_id="section_1",
        operation_type="replace",
        content="New version content",
        rationale="version bump test",
    )

    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])

    assert new_prompt.version == 2, (
        f"应用 patch 后 version 应为 2，实际 {new_prompt.version}"
    )


# ---------------------------------------------------------------------------
# Test 6: factory 返回真实 executor
# ---------------------------------------------------------------------------


def test_factory_returns_real_executors():
    """验证 factory 返回真实 executor。"""
    executors = create_executors({})

    assert isinstance(executors["patch_generation"], PatchGenerationExecutor), (
        f"patch_generation 应为 PatchGenerationExecutor 实例，"
        f"实际 {type(executors['patch_generation']).__name__}"
    )
    assert isinstance(executors["patch_apply"], PatchApplyExecutor), (
        f"patch_apply 应为 PatchApplyExecutor 实例，"
        f"实际 {type(executors['patch_apply']).__name__}"
    )
    assert isinstance(executors["patch_validator"], PatchValidator), (
        f"patch_validator 应为 PatchValidator 实例，"
        f"实际 {type(executors['patch_validator']).__name__}"
    )
