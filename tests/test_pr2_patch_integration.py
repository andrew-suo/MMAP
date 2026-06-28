"""PR2 集成测试：Patch 生成 → 校验 → 应用 → 渲染 链路。

验证 PatchGenerationExecutor + PatchValidator + PatchApplyExecutor 在
ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage
中的端到端集成行为，覆盖 patch 生成、应用、重新抽取/分析、
broken 样本回滚以及 fixed 样本接受等关键路径。
"""

from __future__ import annotations

import pytest

from mmap_optimizer.stages.analysis_prompt_optimization import (
    AnalysisPromptOptimizationStage,
    ReflectionResult,
)
from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionPromptOptimizationStage,
    ExtractionResult,
)
from mmap_optimizer.executors.patch_apply_executor import PatchApplyExecutor
from mmap_optimizer.executors.analysis_executor import AnalysisExecutor
from mmap_optimizer.executors.patch_generation_executor import (
    PatchGenerationExecutor,
)
from mmap_optimizer.executors.patch_validator import PatchValidator
from mmap_optimizer.model.client import MockModelClient, ModelResponse
from mmap_optimizer.patch.types import AnalysisPatch, ExtractionPatch
from mmap_optimizer.data.sample import (
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# Mock executors（用于 test 3-6）
# ---------------------------------------------------------------------------


class MockExtractionExecutor:
    """Mock extraction executor，返回指定 status 的抽取结果。"""

    def __init__(self, status: str = "wrong") -> None:
        self.status = status

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        results = []
        for sample_id in batch.sample_ids:
            results.append(
                ExtractionResult(
                    sample_id=sample_id,
                    raw_output='{"result":"wrong"}',
                    parsed_output={"result": "wrong"},
                    status=self.status,
                )
            )
        return results


class MockEvaluationExecutor:
    """Mock evaluation executor，返回指定 status 的评估记录。"""

    def __init__(self, status: str = "wrong") -> None:
        self.status = status

    def evaluate_batch(self, extraction_results, sample_set):
        records = []
        for result in extraction_results:
            records.append(
                EvalRecord(
                    sample_id=result.sample_id,
                    extraction_result_id=result.sample_id,
                    status=self.status,
                    correct=(self.status == "correct"),
                )
            )
        return records


class MockAnalysisExecutor:
    """Mock analysis executor。

    - execute_batch: 返回 analysis_correct=True 且含有效 patch_suggestion 的 AnalysisResult。
    - reflect: 返回 reflection_success=True 且含有效 patch_suggestion 的 ReflectionResult。
    """

    def __init__(self, patch_suggestion=None):
        self.patch_suggestion = patch_suggestion or {
            "target_section": "section_1",
            "operation": "replace",
            "content": "Be more careful about the answer",
            "rationale": "fix wrong answer",
        }

    def execute_batch(self, analysis_prompt, extraction_prompt, extraction_results, sample_set):
        results = []
        for result in extraction_results:
            results.append(
                AnalysisResult(
                    sample_id=result.sample_id,
                    judgement={"correct": False},
                    analysis_correct=True,
                    error_reason="wrong answer",
                    patch_suggestion=dict(self.patch_suggestion),
                )
            )
        return results

    def execute(self, analysis_prompt, extraction_prompt, extraction_result, sample_spec):
        return AnalysisResult(
            sample_id=extraction_result.sample_id,
            judgement={"correct": False},
            analysis_correct=True,
            error_reason="wrong answer",
            patch_suggestion=dict(self.patch_suggestion),
        )

    def reflect(self, analysis_prompt, extraction_result, analysis_result, sample_spec):
        return ReflectionResult(
            sample_id=extraction_result.sample_id,
            reflection_success=True,
            error_reason="analysis misjudged",
            patch_suggestion={
                "target_section": "section_1",
                "operation": "replace",
                "content": "Improve analysis instructions",
                "rationale": "fix analysis",
            },
        )


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


def make_extraction_prompt() -> StructuredPrompt:
    """构造含 mutable section_1 的 extraction StructuredPrompt。"""
    section = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="Extract the answer",
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section],
        raw_markdown="# Task\nExtract the answer",
        version=1,
    )


def make_analysis_prompt() -> StructuredPrompt:
    """构造含 mutable section_1 的 analysis StructuredPrompt。"""
    section = PromptSection(
        id="section_1",
        title="Analysis Task",
        level=1,
        content="Analyze the extraction",
        mutable=True,
    )
    return StructuredPrompt(
        id="pa1",
        prompt_type="analysis",
        sections=[section],
        raw_markdown="# Analysis Task\nAnalyze the extraction",
        version=1,
    )


def make_sample_set() -> SampleSet:
    """构造含单个样本 s1 的 SampleSet。"""
    spec = SampleSpec(id="s1", input={}, ground_truth={"result": "A"})
    state = SampleState(sample_id="s1")
    return SampleSet(specs={"s1": spec}, states={"s1": state})


def make_batch() -> SampleBatch:
    """构造含样本 s1 的 SampleBatch。"""
    return SampleBatch(
        id="batch_1",
        phase="prompt_optimization",
        iteration=1,
        sampler_name="test",
        sample_ids=["s1"],
    )


def test_patch_generation_uses_evaluation_status_for_wrong_but_parseable_outputs():
    prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    executor = PatchGenerationExecutor(model_client=None)

    extraction_results = [
        ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"wrong"}',
            parsed_output={"result": "wrong"},
            status="correct",
            evaluation_status="wrong",
        )
    ]
    analysis_results = [
        AnalysisResult(
            sample_id="s1",
            judgement={"judgement": {"is_correct": False}},
            analysis_correct=True,
            error_reason="result field mismatched",
            confirmed_facts=["ground truth expects A"],
            hypothesized_error_causes=["prompt lacks label distinction"],
        )
    ]

    draft_patches, validated_patches, rejected_patches = executor.generate_extraction_patches(
        analysis_results=analysis_results,
        extraction_results=extraction_results,
        extraction_prompt=prompt,
        sample_set=sample_set,
    )

    assert len(draft_patches) == 1
    assert len(validated_patches) == 1
    assert len(rejected_patches) == 0


def test_analysis_executor_prefers_evaluation_status_when_checking_actual_correctness():
    executor = AnalysisExecutor(model_client=MockModelClient())

    extraction_result = ExtractionResult(
        sample_id="s1",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
        evaluation_status="wrong",
    )

    assert executor._compute_actual_correct(
        extraction_result,
        ground_truth={"result": "OK"},
    ) is False


def test_patch_generation_assigns_unique_ids_for_multiple_suggestions_from_same_sample():
    executor = PatchGenerationExecutor(model_client=None)

    patch1 = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion={
            "target_section": "section_1",
            "op": "append_to_section",
            "content": "first patch",
            "reasoning": "first rationale",
        },
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )
    patch2 = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion={
            "target_section": "section_1",
            "op": "append_to_section",
            "content": "second patch",
            "reasoning": "second rationale",
        },
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )

    assert patch1.id == "patch_extraction_s1_1"
    assert patch2.id == "patch_extraction_s1_2"
    assert patch1.id != patch2.id


def test_patch_generation_uses_semantic_draft_id_in_patch_id_when_available():
    executor = PatchGenerationExecutor(model_client=None)

    patch = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion={
            "target_section": "section_1",
            "op": "append_to_section",
            "content": "translated patch",
            "reasoning": "translated rationale",
            "semantic_draft_id": "semantic_7",
        },
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )

    assert patch.id == "patch_extraction_s1_semantic_7"


def test_patch_generation_resets_per_run_counters():
    executor = PatchGenerationExecutor(model_client=None)

    first = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion={
            "target_section": "section_1",
            "op": "append_to_section",
            "content": "first patch",
            "reasoning": "first rationale",
        },
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )

    executor._reset_run_artifacts()

    second = executor._build_patch_from_suggestion(
        sample_id="s1",
        suggestion={
            "target_section": "section_1",
            "op": "append_to_section",
            "content": "second patch",
            "reasoning": "second rationale",
        },
        patch_class=ExtractionPatch,
        patch_id_prefix="patch_extraction",
    )

    assert first.id == "patch_extraction_s1_1"
    assert second.id == "patch_extraction_s1_1"


class RecordingCalibrationClient:
    """记录校准调用次数的模型替身。"""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls = 0

    def complete(self, messages, model_config=None, response_format=None):
        self.calls += 1
        return ModelResponse(raw_output=self.output)


class FailingPatchGenerationClient(MockModelClient):
    """如果 patch 生成被错误触发，就直接失败的模型替身。"""

    def __init__(self) -> None:
        super().__init__(default_output='{"patches":[],"cited_sections":[]}')
        self.calls = 0

    def complete(self, messages, model_config=None, response_format=None):
        self.calls += 1
        raise AssertionError("patch generation should not be called for correct extraction results")


def test_patch_validator_calibrates_unknown_section_once_successfully(tmp_path):
    """UNKNOWN_SECTION 可通过一次校准修复，并记录 repair 元数据。"""
    calibration_prompt = tmp_path / "patch_calibration.txt"
    calibration_prompt.write_text("Calibrate patch locations only.", encoding="utf-8")
    client = MockModelClient(
        default_output='[{"id":"patch1","target_section":"section_1"}]'
    )
    validator = PatchValidator(
        model_client=client,
        calibration_prompt_path=str(calibration_prompt),
    )
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="missing_section",
        operation_type="append_to_section",
        content="Add a concrete instruction.",
        rationale="Valid content, invalid section.",
        source_sample_ids=["s1"],
    )

    validated, rejected = validator.validate_batch_with_calibration(
        [patch],
        make_extraction_prompt(),
        make_sample_set(),
    )

    assert validated == [patch]
    assert rejected == []
    assert patch.target_section_id == "section_1"
    assert patch.status == "candidate_safe"
    assert patch.metadata["repair_attempted"] is True
    assert patch.metadata["repair_reason"] == "UNKNOWN_SECTION"
    assert patch.metadata["original_rejection_reason"] == "VALIDATION_FAILED:UNKNOWN_SECTION"
    assert patch.metadata["repair_success"] is True


def test_patch_validator_runs_single_failed_calibration_pass(tmp_path):
    """校准失败时只调用一次模型，并保留失败 repair 元数据。"""
    calibration_prompt = tmp_path / "patch_calibration.txt"
    calibration_prompt.write_text("Calibrate patch locations only.", encoding="utf-8")
    client = RecordingCalibrationClient(
        '[{"id":"patch1","target_section":"still_missing"}]'
    )
    validator = PatchValidator(
        model_client=client,
        calibration_prompt_path=str(calibration_prompt),
    )
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="missing_section",
        operation_type="append_to_section",
        content="Add a concrete instruction.",
        rationale="Valid content, invalid section.",
        source_sample_ids=["s1"],
    )

    validated, rejected = validator.validate_batch_with_calibration(
        [patch],
        make_extraction_prompt(),
        make_sample_set(),
    )

    assert validated == []
    assert rejected == [patch]
    assert client.calls == 1
    assert patch.status == "rejected"
    assert patch.rejection_reason == "VALIDATION_FAILED:UNKNOWN_SECTION"
    assert patch.metadata["repair_attempted"] is True
    assert patch.metadata["repair_reason"] == "UNKNOWN_SECTION"
    assert patch.metadata["repair_success"] is False


# ---------------------------------------------------------------------------
# Test 1: extraction patch generate → validate → apply → render
# ---------------------------------------------------------------------------


def test_extraction_patch_generate_validate_apply_render():
    """测试链路：analysis result → extraction patch → validate → apply → render。

    构造 StructuredPrompt（含 mutable section_1）、AnalysisResult（analysis_correct=True，
    patch_suggestion 含 target_section/operation/content/rationale）、ExtractionResult、
    SampleSet，使用 PatchGenerationExecutor 生成 patch，验证 validated_patches 非空；
    使用 PatchApplyExecutor.apply 应用 patch，验证 apply_report.changed=True、
    new_prompt.sections[0].content 已变化、new_prompt.version > base_prompt.version。
    """
    # 构造 StructuredPrompt（含 mutable section "section_1"）
    prompt = make_extraction_prompt()

    # 构造 SampleSet（含对应 SampleSpec）
    sample_set = make_sample_set()

    # 构造 ExtractionResult
    extraction_result = ExtractionResult(
        sample_id="s1",
        raw_output='{"result":"wrong"}',
        parsed_output={"result": "wrong"},
        status="wrong",
    )

    # 构造 AnalysisResult（analysis_correct=True, patch_suggestion 含完整字段）
    analysis_result = AnalysisResult(
        sample_id="s1",
        judgement={"correct": False},
        analysis_correct=True,
        error_reason="wrong answer",
        patch_suggestion={
            "target_section": "section_1",
            "operation": "replace",
            "content": "Be more careful about the answer",
            "rationale": "fix wrong answer",
        },
    )

    # 使用 PatchGenerationExecutor.generate_extraction_patches() 生成 patch
    executor = PatchGenerationExecutor()
    draft_patches, validated_patches, rejected_patches = executor.generate_extraction_patches(
        analysis_results=[analysis_result],
        extraction_results=[extraction_result],
        extraction_prompt=prompt,
        sample_set=sample_set,
    )

    # 验证 validated_patches 非空
    assert len(validated_patches) > 0, "validated_patches 不应为空"
    assert len(draft_patches) == 1

    # 使用 PatchApplyExecutor.apply() 应用 patch
    apply_executor = PatchApplyExecutor()
    new_prompt, apply_report = apply_executor.apply(prompt, validated_patches)

    # 验证 apply_report.changed=True
    assert apply_report.changed is True, "apply_report.changed 应为 True"

    # 验证 new_prompt.sections[0].content 已变化
    assert new_prompt.sections[0].content != prompt.sections[0].content, (
        "new_prompt.sections[0].content 应与 base prompt 不同"
    )
    assert new_prompt.sections[0].content == "Be more careful about the answer"

    # 验证 new_prompt.version > base_prompt.version
    assert new_prompt.version > prompt.version, (
        f"new_prompt.version({new_prompt.version}) 应 > base_prompt.version({prompt.version})"
    )

    # 验证 render：渲染后的 markdown 包含新内容
    rendered = new_prompt.to_markdown()
    assert "Be more careful about the answer" in rendered


# ---------------------------------------------------------------------------
# Test 2: analysis patch generate → validate → apply → render
# ---------------------------------------------------------------------------


def test_analysis_patch_generate_validate_apply_render():
    """测试链路：reflection result → analysis patch → validate → apply → render。

    构造 StructuredPrompt（analysis 类型，含 mutable section）、ReflectionResult
    （reflection_success=True, patch_suggestion 非空），使用
    PatchGenerationExecutor.generate_analysis_patches() 生成 patch，验证
    validated_patches 非空；使用 PatchApplyExecutor.apply() 应用 patch，
    验证 apply_report.changed=True。
    """
    # 构造 StructuredPrompt（analysis 类型，含 mutable section）
    prompt = make_analysis_prompt()

    # 构造 SampleSet
    sample_set = make_sample_set()

    # 构造 ReflectionResult（reflection_success=True, patch_suggestion 非空）
    reflection = ReflectionResult(
        sample_id="s1",
        reflection_success=True,
        error_reason="analysis wrong",
        patch_suggestion={
            "target_section": "section_1",
            "operation": "replace",
            "content": "Improve analysis instructions",
            "rationale": "fix analysis",
        },
    )

    # 使用 PatchGenerationExecutor.generate_analysis_patches() 生成 patch
    executor = PatchGenerationExecutor()
    draft_patches, validated_patches, rejected_patches = executor.generate_analysis_patches(
        reflection_results=[reflection],
        analysis_prompt=prompt,
        sample_set=sample_set,
    )

    # 验证 validated_patches 非空
    assert len(validated_patches) > 0, "validated_patches 不应为空"
    assert len(draft_patches) == 1

    # 使用 PatchApplyExecutor.apply() 应用 patch
    apply_executor = PatchApplyExecutor()
    new_prompt, apply_report = apply_executor.apply(prompt, validated_patches)

    # 验证 apply_report.changed=True
    assert apply_report.changed is True, "apply_report.changed 应为 True"

    # 验证 new_prompt.sections[0].content 已变化
    assert new_prompt.sections[0].content != prompt.sections[0].content, (
        "new_prompt.sections[0].content 应与 base prompt 不同"
    )
    assert new_prompt.sections[0].content == "Improve analysis instructions"

    # 验证 new_prompt.version > base_prompt.version
    assert new_prompt.version > prompt.version

    # 验证 render
    rendered = new_prompt.to_markdown()
    assert "Improve analysis instructions" in rendered


def test_patch_generation_skips_correct_extraction_results_in_code_path():
    """抽取结果本身正确时，不应生成 extraction patch。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    extraction_result = ExtractionResult(
        sample_id="s1",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )
    analysis_result = AnalysisResult(
        sample_id="s1",
        judgement={"is_correct": True},
        analysis_correct=True,
        error_reason="",
        patch_suggestion={"target_section": "section_1", "operation": "replace", "content": "unused"},
    )

    executor = PatchGenerationExecutor()
    draft_patches, validated_patches, rejected_patches = executor.generate_extraction_patches(
        analysis_results=[analysis_result],
        extraction_results=[extraction_result],
        extraction_prompt=prompt,
        sample_set=sample_set,
    )

    assert draft_patches == []
    assert validated_patches == []
    assert rejected_patches == []


def test_patch_generation_skips_correct_extraction_results_in_model_path():
    """模型路径下，抽取结果本身正确时也不应触发 patch 生成。"""
    prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    extraction_result = ExtractionResult(
        sample_id="s1",
        raw_output='{"result":"OK"}',
        parsed_output={"result": "OK"},
        status="correct",
    )
    analysis_result = AnalysisResult(
        sample_id="s1",
        judgement={"is_correct": True},
        analysis_correct=True,
        error_reason="",
        patch_suggestion={"target_section": "section_1", "operation": "replace", "content": "unused"},
    )

    client = FailingPatchGenerationClient()
    executor = PatchGenerationExecutor(model_client=client)
    draft_patches, validated_patches, rejected_patches = executor.generate_extraction_patches(
        analysis_results=[analysis_result],
        extraction_results=[extraction_result],
        extraction_prompt=prompt,
        sample_set=sample_set,
    )

    assert client.calls == 0
    assert draft_patches == []
    assert validated_patches == []
    assert rejected_patches == []


# ---------------------------------------------------------------------------
# Test 3: patched prompt 重新执行 extraction
# ---------------------------------------------------------------------------


def test_patched_prompt_re_extraction():
    """测试 patched prompt 重新执行 extraction。

    构造完整的 ExtractionPromptOptimizationStage（含 patch_generation_executor
    和 patch_apply_executor），使用 mock extraction_executor（返回 wrong 结果）
    和 mock evaluation_executor，构造 analysis_results 使其 analysis_correct=True
    且有有效 patch_suggestion。运行 stage.run()，验证 patched_extraction_results
    非空（如果 apply_report.changed=True）。
    """
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    # mock extraction_executor（返回 wrong 结果）和 mock evaluation_executor
    extraction_executor = MockExtractionExecutor(status="wrong")
    evaluation_executor = MockEvaluationExecutor(status="wrong")
    # mock analysis_executor：返回 analysis_correct=True 且有有效 patch_suggestion
    analysis_executor = MockAnalysisExecutor()

    # 真实 patch_generation_executor 和 patch_apply_executor
    patch_generation_executor = PatchGenerationExecutor()
    patch_apply_executor = PatchApplyExecutor()

    # 构造完整的 ExtractionPromptOptimizationStage
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=patch_generation_executor,
        patch_apply_executor=patch_apply_executor,
    )

    # 运行 stage.run()
    stage.run()

    # 验证 apply_report.changed=True 时 patched_extraction_results 非空
    assert stage.patch_apply_report is not None
    if stage.patch_apply_report.changed:
        assert len(stage.patched_extraction_results) > 0, (
            "apply_report.changed=True 时 patched_extraction_results 不应为空"
        )
        # 验证 patched_extraction_results 的 sample_id 与 batch 一致
        patched_ids = {r.sample_id for r in stage.patched_extraction_results}
        assert patched_ids == set(batch.sample_ids)


# ---------------------------------------------------------------------------
# Test 4: patched analysis prompt 重新执行 analysis
# ---------------------------------------------------------------------------


def test_patched_analysis_prompt_re_analysis():
    """测试 patched analysis prompt 重新执行 analysis。

    构造完整的 AnalysisPromptOptimizationStage（含 patch_generation_executor
    和 patch_apply_executor），构造 reflection_results 使其 reflection_success=True
    且有有效 patch_suggestion。运行 stage.run()，验证 patched_analysis_results
    非空（如果 apply_report.changed=True）。
    """
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    # 构造 extraction_results
    extraction_results = [
        ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"wrong"}',
            parsed_output={"result": "wrong"},
            status="wrong",
        )
    ]

    # 构造 base_analysis_results（含 analysis_correct=False 的样本以触发反思）
    base_analysis_results = [
        AnalysisResult(
            sample_id="s1",
            judgement={"correct": False},
            analysis_correct=False,
            error_reason="analysis wrong",
        )
    ]

    # mock analysis_executor：reflect 返回有效 patch_suggestion，
    # execute_batch 返回 analysis_correct=True 的结果
    analysis_executor = MockAnalysisExecutor()

    # 真实 patch_generation_executor 和 patch_apply_executor
    patch_generation_executor = PatchGenerationExecutor()
    patch_apply_executor = PatchApplyExecutor()

    # 构造完整的 AnalysisPromptOptimizationStage
    stage = AnalysisPromptOptimizationStage(
        analysis_prompt=analysis_prompt,
        extraction_results=extraction_results,
        base_analysis_results=base_analysis_results,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        analysis_executor=analysis_executor,
        patch_generation_executor=patch_generation_executor,
        patch_apply_executor=patch_apply_executor,
        extraction_prompt=extraction_prompt,
    )

    # 运行 stage.run()
    stage.run()

    # 验证 apply_report.changed=True 时 patched_analysis_results 非空
    assert stage.patch_apply_report is not None
    if stage.patch_apply_report.changed:
        assert len(stage.patched_analysis_results) > 0, (
            "apply_report.changed=True 时 patched_analysis_results 不应为空"
        )
        # 验证 patched_analysis_results 的 sample_id 与 batch 一致
        patched_ids = {r.sample_id for r in stage.patched_analysis_results}
        assert patched_ids == set(batch.sample_ids)


# ---------------------------------------------------------------------------
# Test 5: broken sample 出现时回滚
# ---------------------------------------------------------------------------


def test_broken_sample_rollback():
    """测试 broken sample 出现时回滚。

    构造 ExtractionPromptOptimizationStage，使 base_eval 全部 correct，
    patched_eval 全部 wrong（模拟 broken），验证 accepted_prompt is None（回滚），
    metrics.rollback=True 或 no_progress=True。
    """
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    # 真实 patch_apply_executor（触发 step7 真实分支）
    patch_apply_executor = PatchApplyExecutor()

    # 构造 ExtractionPromptOptimizationStage
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        patch_apply_executor=patch_apply_executor,
    )

    # 手动设置 base_eval_records（全部 correct）
    stage.base_eval_records = [
        EvalRecord(
            sample_id="s1",
            extraction_result_id="s1",
            status="correct",
            correct=True,
        )
    ]

    # 手动设置 patched_eval_records（全部 wrong → 模拟 broken）
    stage.patched_eval_records = [
        EvalRecord(
            sample_id="s1",
            extraction_result_id="s1",
            status="wrong",
            correct=False,
        )
    ]

    # 手动设置 initial_merged_patches 和 trial_prompt
    stage.initial_merged_patches = [
        ExtractionPatch(
            id="patch_1",
            target_section_id="section_1",
            operation_type="replace_section",
            content="new content for broken test",
            rationale="test broken rollback",
            source_sample_ids=["s1"],
            status="candidate_safe",
        )
    ]
    stage.trial_prompt = extraction_prompt

    # 调用 _step7_regression_and_toxicity_test()
    stage._step7_regression_and_toxicity_test()

    # 验证 accepted_prompt is None（回滚）
    assert stage.accepted_prompt is None, "broken 样本出现时应回滚，accepted_prompt 应为 None"

    # 验证 metrics.rollback=True 或 no_progress=True
    assert stage.metrics.rollback is True or stage.metrics.no_progress is True, (
        f"broken 回滚时 metrics.rollback={stage.metrics.rollback}, "
        f"no_progress={stage.metrics.no_progress}，至少一个应为 True"
    )
    assert stage.metrics.rollback is True, "broken 场景应设置 rollback=True"


# ---------------------------------------------------------------------------
# Test 6: fixed 样本出现且无 broken 时接受
# ---------------------------------------------------------------------------


def test_fixed_sample_accepted():
    """测试 fixed 样本出现且无 broken 时接受。

    构造 ExtractionPromptOptimizationStage，使 base_eval 有 wrong，
    patched_eval 有 correct（模拟 fixed），验证 accepted_prompt is not None，
    metrics.accepted_patch_count > 0。
    """
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    # 真实 patch_apply_executor（触发 step7 真实分支）
    patch_apply_executor = PatchApplyExecutor()

    # 构造 ExtractionPromptOptimizationStage
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        patch_apply_executor=patch_apply_executor,
    )

    # 手动设置 base_eval_records（有 wrong → 将被 fixed）
    stage.base_eval_records = [
        EvalRecord(
            sample_id="s1",
            extraction_result_id="s1",
            status="wrong",
            correct=False,
        )
    ]

    # 手动设置 patched_eval_records（有 correct → 模拟 fixed）
    stage.patched_eval_records = [
        EvalRecord(
            sample_id="s1",
            extraction_result_id="s1",
            status="correct",
            correct=True,
        )
    ]

    # 手动设置 initial_merged_patches 和 trial_prompt
    stage.initial_merged_patches = [
        ExtractionPatch(
            id="patch_1",
            target_section_id="section_1",
            operation_type="replace_section",
            content="new content for fixed test",
            rationale="test fixed acceptance",
            source_sample_ids=["s1"],
            status="candidate_safe",
        )
    ]
    stage.trial_prompt = extraction_prompt

    # 调用 _step7_regression_and_toxicity_test()
    stage._step7_regression_and_toxicity_test()

    # 验证 accepted_prompt is not None
    assert stage.accepted_prompt is not None, "fixed 样本出现且无 broken 时应接受 patch"

    # 验证 metrics.accepted_patch_count > 0
    assert stage.metrics.accepted_patch_count > 0, (
        f"接受 patch 后 accepted_patch_count 应 > 0, "
        f"got {stage.metrics.accepted_patch_count}"
    )
    assert stage.metrics.accepted_patch_count == len(stage.initial_merged_patches)
