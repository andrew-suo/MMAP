"""PR3 集成测试：真实 merge + greedy 测毒 链路。

验证 ExtractionPromptOptimizationStage 和 AnalysisPromptOptimizationStage
在 PR3 流程中的端到端集成行为，覆盖 patch 生成、合并、应用、测毒、
二次合并、最终应用等关键路径。

关键设计：
- 使用真实 MergeExecutor / ToxicityTestExecutor / PatchGenerationExecutor /
  PatchApplyExecutor / PatchValidator 实例。
- 使用 content-aware mock executor 根据 prompt 内容返回不同结果，
  以模拟 base / patched / toxicity test 各阶段的行为。
- extraction / analysis prompt 均含 2 个 mutable section（section_1, section_2），
  使来自不同样本的 patch target 不同 section，避免被 tree_merge 合并为 1 条，
  从而能在 greedy 测毒中独立测试每条 patch。
"""

from __future__ import annotations

from mmap_optimizer.refactored.analysis_prompt_optimization_stage import (
    AnalysisPromptOptimizationStage,
    ReflectionResult,
)
from mmap_optimizer.refactored.extraction_prompt_optimization_stage import (
    AnalysisResult,
    EvalRecord,
    ExtractionPromptOptimizationStage,
    ExtractionResult,
)
from mmap_optimizer.refactored.executors.merge_executor import MergeExecutor
from mmap_optimizer.refactored.executors.patch_apply_executor import PatchApplyExecutor
from mmap_optimizer.refactored.executors.patch_generation_executor import (
    PatchGenerationExecutor,
)
from mmap_optimizer.refactored.executors.patch_validator import PatchValidator
from mmap_optimizer.refactored.executors.toxicity_executor import ToxicityTestExecutor
from mmap_optimizer.refactored.sample import (
    SampleBatch,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.refactored.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# Mock executors
# ---------------------------------------------------------------------------


class ContentAwareMockExtractionExecutor:
    """Mock extraction executor，根据 prompt 内容返回不同 status。

    - base_status_map: base prompt 下每个 sample 的 status。
    - patch_effects: {content_substring: {sample_id: status}}，
      当 prompt 内容包含 substring 时，对应 sample 的 status 被覆盖。
    """

    def __init__(
        self,
        base_status_map: dict[str, str],
        patch_effects: dict[str, dict[str, str]] | None = None,
        default_status: str = "wrong",
    ) -> None:
        self.base_status_map = base_status_map
        self.patch_effects = patch_effects or {}
        self.default_status = default_status

    def execute(self, prompt, batch, sample_set, fewshot_examples=None):
        full_content = "\n".join(s.content for s in prompt.sections)
        status_map = dict(self.base_status_map)
        for substring, effects in self.patch_effects.items():
            if substring in full_content:
                status_map.update(effects)
        results = []
        for sample_id in batch.sample_ids:
            status = status_map.get(sample_id, self.default_status)
            results.append(
                ExtractionResult(
                    sample_id=sample_id,
                    raw_output=f'{{"result":"{status}"}}',
                    parsed_output={"result": status},
                    status=status,
                )
            )
        return results


class MockEvaluationExecutor:
    """Mock evaluation executor，根据 extraction_result.status 判断 correct。"""

    def evaluate(self, extraction_result, ground_truth, sample_state=None):
        correct = extraction_result.status == "correct"
        return EvalRecord(
            sample_id=extraction_result.sample_id,
            extraction_result_id=extraction_result.sample_id,
            status=extraction_result.status,
            correct=correct,
        )

    def evaluate_batch(self, extraction_results, sample_set):
        return [self.evaluate(r, {}) for r in extraction_results]


class ContentAwareMockAnalysisExecutor:
    """Mock analysis executor，根据 analysis_prompt 内容返回不同 analysis_correct。

    - base_correct_map: base analysis prompt 下每个 sample 的 analysis_correct。
    - patch_effects: {content_substring: {sample_id: analysis_correct}}，
      当 analysis_prompt 内容包含 substring 时，对应 sample 的 analysis_correct 被覆盖。
    - sample_suggestions: {sample_id: patch_suggestion}，用于 reflect 和 execute_batch
      返回 patch_suggestion 以驱动 patch 生成。
    """

    def __init__(
        self,
        base_correct_map: dict[str, bool],
        patch_effects: dict[str, dict[str, bool]] | None = None,
        sample_suggestions: dict[str, dict] | None = None,
    ) -> None:
        self.base_correct_map = base_correct_map
        self.patch_effects = patch_effects or {}
        self.sample_suggestions = sample_suggestions or {}

    def _compute_correct(self, analysis_prompt, sample_id) -> bool:
        full_content = "\n".join(s.content for s in analysis_prompt.sections)
        correct = self.base_correct_map.get(sample_id, False)
        for substring, effects in self.patch_effects.items():
            if substring in full_content and sample_id in effects:
                correct = effects[sample_id]
        return correct

    def execute_batch(self, analysis_prompt, extraction_prompt, extraction_results, sample_set):
        results = []
        for result in extraction_results:
            correct = self._compute_correct(analysis_prompt, result.sample_id)
            suggestion = self.sample_suggestions.get(result.sample_id) if correct else None
            results.append(
                AnalysisResult(
                    sample_id=result.sample_id,
                    judgement={"correct": correct},
                    analysis_correct=correct,
                    patch_suggestion=dict(suggestion) if suggestion else None,
                )
            )
        return results

    def execute(self, analysis_prompt, extraction_prompt, extraction_result, sample_spec):
        correct = self._compute_correct(analysis_prompt, extraction_result.sample_id)
        return AnalysisResult(
            sample_id=extraction_result.sample_id,
            judgement={"correct": correct},
            analysis_correct=correct,
        )

    def reflect(self, analysis_prompt, extraction_result, analysis_result, sample_spec):
        sample_id = extraction_result.sample_id
        suggestion = self.sample_suggestions.get(sample_id)
        if suggestion is None:
            return ReflectionResult(
                sample_id=sample_id,
                reflection_success=False,
                error_reason="no suggestion",
                patch_suggestion=None,
            )
        return ReflectionResult(
            sample_id=sample_id,
            reflection_success=True,
            error_reason="analysis misjudged",
            patch_suggestion=dict(suggestion),
        )


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------

SAMPLE_IDS = ["s1", "s2", "s3"]

# patch content 标识符（用于 mock 识别哪条 patch 已应用）
PATCH_S1_CONTENT = "patch_s1_content"
PATCH_S2_CONTENT = "patch_s2_content"


def make_extraction_prompt() -> StructuredPrompt:
    """构造含 2 个 mutable section 的 extraction StructuredPrompt。

    section_1 / section_2 分别作为 patch_s1 / patch_s2 的 target，
    使两条 patch 进入不同 cluster，不被 tree_merge 合并。
    """
    section_1 = PromptSection(
        id="section_1",
        title="Task",
        level=1,
        content="base_content_s1",
        mutable=True,
    )
    section_2 = PromptSection(
        id="section_2",
        title="Guidelines",
        level=1,
        content="base_content_s2",
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section_1, section_2],
        raw_markdown="# Task\nbase_content_s1\n\n# Guidelines\nbase_content_s2",
        version=1,
    )


def make_analysis_prompt() -> StructuredPrompt:
    """构造含 2 个 mutable section 的 analysis StructuredPrompt。"""
    section_1 = PromptSection(
        id="section_1",
        title="Analysis Task",
        level=1,
        content="base_analysis_s1",
        mutable=True,
    )
    section_2 = PromptSection(
        id="section_2",
        title="Analysis Guidelines",
        level=1,
        content="base_analysis_s2",
        mutable=True,
    )
    return StructuredPrompt(
        id="pa1",
        prompt_type="analysis",
        sections=[section_1, section_2],
        raw_markdown="# Analysis Task\nbase_analysis_s1\n\n# Analysis Guidelines\nbase_analysis_s2",
        version=1,
    )


def make_sample_set() -> SampleSet:
    """构造含 s1, s2, s3 的 SampleSet。"""
    specs = {
        sid: SampleSpec(id=sid, input={}, ground_truth={"result": "A"})
        for sid in SAMPLE_IDS
    }
    states = {sid: SampleState(sample_id=sid) for sid in SAMPLE_IDS}
    return SampleSet(specs=specs, states=states)


def make_batch() -> SampleBatch:
    """构造含 s1, s2, s3 的 SampleBatch。"""
    return SampleBatch(
        id="batch_1",
        phase="prompt_optimization",
        iteration=1,
        sampler_name="test",
        sample_ids=list(SAMPLE_IDS),
    )


def make_extraction_results() -> list[ExtractionResult]:
    """构造 extraction_results（analysis stage 需要）。"""
    return [
        ExtractionResult(
            sample_id="s1",
            raw_output='{"result":"wrong"}',
            parsed_output={"result": "wrong"},
            status="wrong",
        ),
        ExtractionResult(
            sample_id="s2",
            raw_output='{"result":"wrong"}',
            parsed_output={"result": "wrong"},
            status="wrong",
        ),
        ExtractionResult(
            sample_id="s3",
            raw_output='{"result":"correct"}',
            parsed_output={"result": "correct"},
            status="correct",
        ),
    ]


def make_base_analysis_results() -> list[AnalysisResult]:
    """构造 base_analysis_results（analysis stage 需要）。

    s1, s2 分析错误（analysis_correct=False），s3 分析正确。
    """
    return [
        AnalysisResult(
            sample_id="s1",
            judgement={"correct": False},
            analysis_correct=False,
            error_reason="s1 analysis wrong",
        ),
        AnalysisResult(
            sample_id="s2",
            judgement={"correct": False},
            analysis_correct=False,
            error_reason="s2 analysis wrong",
        ),
        AnalysisResult(
            sample_id="s3",
            judgement={"correct": True},
            analysis_correct=True,
            error_reason=None,
        ),
    ]


def make_sample_suggestions() -> dict[str, dict]:
    """构造 sample_suggestions：s1 -> section_1 patch, s2 -> section_2 patch。"""
    return {
        "s1": {
            "target_section": "section_1",
            "operation": "replace",
            "content": PATCH_S1_CONTENT,
            "rationale": "fix s1",
        },
        "s2": {
            "target_section": "section_2",
            "operation": "replace",
            "content": PATCH_S2_CONTENT,
            "rationale": "fix s2",
        },
    }


def make_real_executors():
    """构造真实 executor 实例集合。"""
    return {
        "patch_generation_executor": PatchGenerationExecutor(),
        "patch_apply_executor": PatchApplyExecutor(),
        "merge_executor": MergeExecutor(),
        "toxicity_test_executor": ToxicityTestExecutor(),
    }


# ---------------------------------------------------------------------------
# Test 1: extraction safe patch enters final prompt
# ---------------------------------------------------------------------------


def test_extraction_safe_patch_enters_final_prompt():
    """safe patch 进入 final prompt：2 条 patch 均 safe，进入 final_merged_patches。"""
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    extraction_executor = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        patch_effects={
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct"},
        },
    )
    evaluation_executor = MockEvaluationExecutor()
    # extraction stage 的 analysis_executor 只在 Step3 调用 execute_batch，
    # 使用 base analysis prompt（无 patch），故 patch_effects 不生效。
    # base_correct_map: s1/s2 analysis_correct=True（生成 patch），s3=False（不生成）。
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    metrics = stage.run()

    # 2 条 patch 均 safe（无 toxic 样本）
    assert len(stage.safe_patches) == 2, (
        f"safe_patches 应有 2 条，实际 {len(stage.safe_patches)}"
    )
    assert len(stage.toxic_patches) == 0
    assert len(stage.final_merged_patches) > 0, "final_merged_patches 不应为空"
    assert stage.accepted_prompt is not None, "accepted_prompt 不应为 None"
    assert stage.final_prompt is not None, "final_prompt 不应为 None"
    assert metrics.accepted_patch_count > 0, "accepted_patch_count 应 > 0"


# ---------------------------------------------------------------------------
# Test 2: extraction ineffective patch filtered
# ---------------------------------------------------------------------------


def test_extraction_ineffective_patch_filtered():
    """ineffective patch 被剔除：P1 来源 s1 全部属于 unchanged_wrong。"""
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    extraction_executor = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        # 只有 P2 修复 s2，P1 不修复 s1
        patch_effects={
            PATCH_S2_CONTENT: {"s2": "correct"},
        },
    )
    evaluation_executor = MockEvaluationExecutor()
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    stage.run()

    # ineffective_patches 非空，rejection_reason=INEFFECTIVE
    assert len(stage.ineffective_patches) > 0, "ineffective_patches 不应为空"
    for patch in stage.ineffective_patches:
        assert patch.rejection_reason == "INEFFECTIVE", (
            f"ineffective patch rejection_reason 应为 INEFFECTIVE，"
            f"实际 {patch.rejection_reason}"
        )

    # safe_patches 不包含 ineffective patch
    safe_ids = {p.id for p in stage.safe_patches}
    ineffective_ids = {p.id for p in stage.ineffective_patches}
    assert safe_ids.isdisjoint(ineffective_ids), (
        "safe_patches 不应包含 ineffective patch"
    )


# ---------------------------------------------------------------------------
# Test 3: extraction toxic patch rejected
# ---------------------------------------------------------------------------


def test_extraction_toxic_patch_rejected():
    """toxic patch 被拒绝：P2 break 了 s3，P1 safe。"""
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    extraction_executor = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        # P1 修复 s1，P2 修复 s2 但 break s3
        patch_effects={
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct", "s3": "wrong"},
        },
    )
    evaluation_executor = MockEvaluationExecutor()
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    stage.run()

    # toxic_patches 包含 P2（来源 s2）
    toxic_ids = {p.id for p in stage.toxic_patches}
    safe_ids = {p.id for p in stage.safe_patches}
    assert len(stage.toxic_patches) == 1, (
        f"toxic_patches 应有 1 条，实际 {len(stage.toxic_patches)}"
    )
    toxic_patch = stage.toxic_patches[0]
    assert toxic_patch.rejection_reason == "TOXIC", (
        f"toxic patch rejection_reason 应为 TOXIC，实际 {toxic_patch.rejection_reason}"
    )
    # toxic patch 来源 s2
    assert "s2" in toxic_patch.source_sample_ids

    # safe_patches 包含 P1（来源 s1）
    assert len(stage.safe_patches) == 1, (
        f"safe_patches 应有 1 条，实际 {len(stage.safe_patches)}"
    )
    safe_patch = stage.safe_patches[0]
    assert "s1" in safe_patch.source_sample_ids

    # final_merged_patches 只包含 safe patch
    final_ids = {p.id for p in stage.final_merged_patches}
    assert final_ids == safe_ids, (
        "final_merged_patches 应只包含 safe_patches"
    )
    assert toxic_ids.isdisjoint(final_ids), (
        "final_merged_patches 不应包含 toxic patch"
    )


# ---------------------------------------------------------------------------
# Test 4: extraction safe patch second merge changes prompt
# ---------------------------------------------------------------------------


def test_extraction_safe_patch_second_merge_changes_prompt():
    """safe patch 二次 merge 后 final_prompt 与 base prompt 不同。"""
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    extraction_executor = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        patch_effects={
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct"},
        },
    )
    evaluation_executor = MockEvaluationExecutor()
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    stage.run()

    # final_prompt 不为 None
    assert stage.final_prompt is not None, "final_prompt 不应为 None"

    # final_prompt 内容与 base extraction_prompt 不同
    base_content = "\n".join(s.content for s in extraction_prompt.sections)
    final_content = "\n".join(s.content for s in stage.final_prompt.sections)
    assert final_content != base_content, (
        "final_prompt 内容应与 base extraction_prompt 不同"
    )
    # final_prompt 应包含 patch 内容
    assert PATCH_S1_CONTENT in final_content or PATCH_S2_CONTENT in final_content, (
        "final_prompt 应包含 patch 内容"
    )

    # final_merge_report 不为 None
    assert stage.final_merge_report is not None, "final_merge_report 不应为 None"


# ---------------------------------------------------------------------------
# Test 5: extraction final prompt metrics not below base
# ---------------------------------------------------------------------------


def test_extraction_final_prompt_metrics_not_below_base():
    """final_accuracy 不低于 base_accuracy。"""
    extraction_prompt = make_extraction_prompt()
    analysis_prompt = make_analysis_prompt()
    sample_set = make_sample_set()
    batch = make_batch()

    extraction_executor = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        patch_effects={
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct"},
        },
    )
    evaluation_executor = MockEvaluationExecutor()
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    stage = ExtractionPromptOptimizationStage(
        extraction_prompt=extraction_prompt,
        analysis_prompt=analysis_prompt,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        extraction_executor=extraction_executor,
        evaluation_executor=evaluation_executor,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    metrics = stage.run()

    # final_accuracy 不低于 base_accuracy
    assert metrics.final_accuracy is not None, "final_accuracy 不应为 None"
    assert metrics.base_accuracy is not None, "base_accuracy 不应为 None"
    assert metrics.final_accuracy >= metrics.base_accuracy, (
        f"final_accuracy({metrics.final_accuracy}) 应 >= "
        f"base_accuracy({metrics.base_accuracy})"
    )
    # final_correct_count 不低于 base_correct_count
    assert metrics.final_correct_count >= metrics.base_correct_count, (
        f"final_correct_count({metrics.final_correct_count}) 应 >= "
        f"base_correct_count({metrics.base_correct_count})"
    )


# ---------------------------------------------------------------------------
# Test 6: analysis ineffective patch filtered
# ---------------------------------------------------------------------------


def test_analysis_ineffective_patch_filtered():
    """analysis stage: ineffective patch 被剔除。"""
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    batch = make_batch()
    extraction_results = make_extraction_results()
    base_analysis_results = make_base_analysis_results()

    # base_correct_map: s1/s2 分析错误，s3 分析正确
    # patch_effects: 只有 P2 修复 s2，P1 不修复 s1
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": False, "s2": False, "s3": True},
        patch_effects={
            PATCH_S2_CONTENT: {"s2": True},
        },
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    analysis_stage = AnalysisPromptOptimizationStage(
        analysis_prompt=analysis_prompt,
        extraction_results=extraction_results,
        base_analysis_results=base_analysis_results,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        extraction_prompt=extraction_prompt,
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    analysis_stage.run()

    # ineffective_patches 非空
    assert len(analysis_stage.ineffective_patches) > 0, (
        "ineffective_patches 不应为空"
    )
    for patch in analysis_stage.ineffective_patches:
        assert patch.rejection_reason == "INEFFECTIVE", (
            f"ineffective patch rejection_reason 应为 INEFFECTIVE，"
            f"实际 {patch.rejection_reason}"
        )

    # safe_patches 不包含 ineffective patch
    safe_ids = {p.id for p in analysis_stage.safe_patches}
    ineffective_ids = {p.id for p in analysis_stage.ineffective_patches}
    assert safe_ids.isdisjoint(ineffective_ids), (
        "safe_patches 不应包含 ineffective patch"
    )


# ---------------------------------------------------------------------------
# Test 7: analysis toxic patch rejected
# ---------------------------------------------------------------------------


def test_analysis_toxic_patch_rejected():
    """analysis stage: toxic patch 被拒绝。"""
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    batch = make_batch()
    extraction_results = make_extraction_results()
    base_analysis_results = make_base_analysis_results()

    # P1 修复 s1，P2 修复 s2 但 break s3
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": False, "s2": False, "s3": True},
        patch_effects={
            PATCH_S1_CONTENT: {"s1": True},
            PATCH_S2_CONTENT: {"s2": True, "s3": False},
        },
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    analysis_stage = AnalysisPromptOptimizationStage(
        analysis_prompt=analysis_prompt,
        extraction_results=extraction_results,
        base_analysis_results=base_analysis_results,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        extraction_prompt=extraction_prompt,
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    analysis_stage.run()

    # toxic_patches 包含 P2（来源 s2）
    assert len(analysis_stage.toxic_patches) >= 1, (
        f"toxic_patches 应至少有 1 条，实际 {len(analysis_stage.toxic_patches)}"
    )
    toxic_patch = analysis_stage.toxic_patches[0]
    assert toxic_patch.rejection_reason == "TOXIC", (
        f"toxic patch rejection_reason 应为 TOXIC，实际 {toxic_patch.rejection_reason}"
    )
    assert "s2" in toxic_patch.source_sample_ids

    # safe_patches 包含 P1（来源 s1）
    assert len(analysis_stage.safe_patches) >= 1, (
        f"safe_patches 应至少有 1 条，实际 {len(analysis_stage.safe_patches)}"
    )
    safe_patch = analysis_stage.safe_patches[0]
    assert "s1" in safe_patch.source_sample_ids


# ---------------------------------------------------------------------------
# Test 8: analysis no progress does not affect extraction
# ---------------------------------------------------------------------------


def test_analysis_no_progress_does_not_affect_extraction():
    """analysis stage no_progress=True 时 accepted_prompt=None。

    所有 patch 均无效（来源样本全部 unchanged_wrong），safe_patches 为空，
    accepted_prompt=None，no_progress=True。
    此断言仅在 analysis stage 内部，不影响 extraction prompt。
    """
    analysis_prompt = make_analysis_prompt()
    extraction_prompt = make_extraction_prompt()
    sample_set = make_sample_set()
    batch = make_batch()
    extraction_results = make_extraction_results()
    base_analysis_results = make_base_analysis_results()

    # patch_effects 为空：所有 patch 都不修复任何样本
    # s1, s2 仍为 unchanged_wrong，两条 patch 均被标记 INEFFECTIVE
    analysis_executor = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": False, "s2": False, "s3": True},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    executors = make_real_executors()
    analysis_stage = AnalysisPromptOptimizationStage(
        analysis_prompt=analysis_prompt,
        extraction_results=extraction_results,
        base_analysis_results=base_analysis_results,
        sample_set=sample_set,
        batch=batch,
        iteration=1,
        analysis_executor=analysis_executor,
        patch_generation_executor=executors["patch_generation_executor"],
        patch_apply_executor=executors["patch_apply_executor"],
        extraction_prompt=extraction_prompt,
        merge_executor=executors["merge_executor"],
        toxicity_test_executor=executors["toxicity_test_executor"],
    )

    metrics = analysis_stage.run()

    # accepted_prompt 为 None
    assert analysis_stage.accepted_prompt is None, (
        "no_progress 时 accepted_prompt 应为 None"
    )
    # no_progress=True
    assert metrics.no_progress is True, (
        f"no_progress 应为 True，实际 {metrics.no_progress}"
    )
    # safe_patches 为空
    assert len(analysis_stage.safe_patches) == 0, (
        f"no_progress 时 safe_patches 应为空，实际 {len(analysis_stage.safe_patches)}"
    )
