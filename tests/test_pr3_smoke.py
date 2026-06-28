"""PR3 smoke/acceptance 测试。

验证 PR3 的端到端链路：
- factory.py 返回真实 MergeExecutor / ToxicityTestExecutor（非 mock）
- PromptOptimizationPhase 能以真实 merge + greedy 测毒流程跑完至少 1 轮
- PR3 artifact（toxicity_report / safe_patches / toxic_patches /
  final_merge_report / final_prompt / patch_test_records）正确落盘
- toxicity_report 含 PR3 新增字段
- patch_test_records 可追溯
- extraction prompt 最终推进仅基于 safe patches（toxic patch 不进入 final_prompt）
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mmap_optimizer.stages.extraction_prompt_optimization import (
    AnalysisResult,
    EvalRecord,
    ExtractionResult,
)
from mmap_optimizer.executors.factory import create_executors
from mmap_optimizer.executors.merge_executor import MergeExecutor
from mmap_optimizer.executors.toxicity_executor import ToxicityTestExecutor
from mmap_optimizer.phases.prompt_optimization import (
    PromptOptimizationConfig,
    PromptOptimizationPhase,
)
from mmap_optimizer.data.sample import (
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# Content-aware mock executors（复用 test_pr3_integration.py 的模式）
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
    """Mock analysis executor，根据 analysis_prompt 内容返回不同 analysis_correct。"""

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
        from mmap_optimizer.stages.analysis_prompt_optimization import (
            ReflectionResult,
        )

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

# tree_merge 后保留的 patch ID
PATCH_S1_ID = "patch_extraction_s1"
PATCH_S2_ID = "patch_extraction_s2"


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


def _run_phase_with_effects(
    patch_effects: dict[str, dict[str, str]],
    output_dir: Path,
) -> PromptOptimizationPhase:
    """以真实 merge + toxicity executor 运行 1 轮 PromptOptimizationPhase。

    Args:
        patch_effects: ContentAwareMockExtractionExecutor 的 patch_effects，
            控制 patched prompt 下各 sample 的 status。
        output_dir: 输出目录。

    Returns:
        运行完成后的 PromptOptimizationPhase 实例。
    """
    # create_executors({}) 返回真实 merge / toxicity_test / patch_generation /
    # patch_apply / patch_validator，以及 mock extraction / evaluation / analysis
    executors = create_executors({})

    # 用 content-aware mock 覆盖 extraction / evaluation / analysis
    executors["extraction"] = ContentAwareMockExtractionExecutor(
        base_status_map={"s1": "wrong", "s2": "wrong", "s3": "correct"},
        patch_effects=patch_effects,
    )
    executors["evaluation"] = MockEvaluationExecutor()
    executors["analysis"] = ContentAwareMockAnalysisExecutor(
        base_correct_map={"s1": True, "s2": True, "s3": False},
        patch_effects={},
        sample_suggestions=make_sample_suggestions(),
    )

    config = PromptOptimizationConfig(rounds=1)
    phase = PromptOptimizationPhase(
        config=config,
        extraction_prompt=make_extraction_prompt(),
        analysis_prompt=make_analysis_prompt(),
        sample_set=make_sample_set(),
        output_dir=output_dir,
        seed=42,
        executors=executors,
    )
    phase.run()
    return phase


def _read_jsonl(path: Path) -> list[dict]:
    """读取 JSONL 文件，返回 dict 列表。"""
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _read_json(path: Path) -> dict:
    """读取 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test 1: factory 返回真实 MergeExecutor
# ---------------------------------------------------------------------------


def test_factory_returns_real_merge_executor():
    """验证 factory.py 不再为 merge 返回 mock executor。"""
    from mmap_optimizer.executors.factory import create_executors
    from mmap_optimizer.executors.merge_executor import MergeExecutor

    executors = create_executors({})
    merge = executors["merge"]
    assert isinstance(merge, MergeExecutor), (
        f"merge should be MergeExecutor, got {type(merge).__name__}"
    )
    assert not type(merge).__name__.startswith("_Mock"), "merge should not be a mock"


# ---------------------------------------------------------------------------
# Test 2: factory 返回真实 ToxicityTestExecutor
# ---------------------------------------------------------------------------


def test_factory_returns_real_toxicity_test_executor():
    """验证 factory.py 不再为 toxicity_test 返回 mock executor。"""
    from mmap_optimizer.executors.factory import create_executors
    from mmap_optimizer.executors.toxicity_executor import (
        ToxicityTestExecutor,
    )

    executors = create_executors({})
    toxicity = executors["toxicity_test"]
    assert isinstance(toxicity, ToxicityTestExecutor), (
        f"toxicity_test should be ToxicityTestExecutor, got {type(toxicity).__name__}"
    )
    assert not type(toxicity).__name__.startswith("_Mock"), (
        "toxicity_test should not be a mock"
    )


# ---------------------------------------------------------------------------
# Test 3: PromptOptimizationPhase 以真实 merge + toxicity 跑 1 轮
# ---------------------------------------------------------------------------


def test_phase_runs_one_round_real_merge_and_toxicity():
    """验证 PromptOptimizationPhase 能以真实 merge + toxicity 流程跑完 1 轮。

    场景：s1/s2 wrong, s3 correct；两条 patch 均 safe（无 toxic 样本），
    safe patches 进入 final_prompt。
    """
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 两条 patch 均 safe：修复 s1/s2，不影响 s3
        patch_effects = {
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct"},
        }
        phase = _run_phase_with_effects(patch_effects, output_dir)

        # iteration_results 有 1 条结果
        assert len(phase.iteration_results) == 1, (
            f"iteration_results 应有 1 条，实际 {len(phase.iteration_results)}"
        )

        # extraction_prompt 被更新（version 增加或内容变化）
        assert phase.extraction_prompt is not None
        assert phase.extraction_prompt.version > 1, (
            f"extraction_prompt.version 应 > 1，实际 {phase.extraction_prompt.version}"
        )

        # 验证 artifact 文件
        extraction_dir = output_dir / "prompt_optimization" / "iteration_1" / "extraction"

        toxicity_report_path = extraction_dir / "toxicity_report.json"
        assert toxicity_report_path.exists(), "toxicity_report.json 应存在"

        safe_patches_path = extraction_dir / "safe_patches.jsonl"
        assert safe_patches_path.exists(), "safe_patches.jsonl 应存在"
        safe_patches = _read_jsonl(safe_patches_path)
        assert len(safe_patches) > 0, "safe_patches.jsonl 不应为空"

        final_merge_report_path = extraction_dir / "final_merge_report.json"
        assert final_merge_report_path.exists(), "final_merge_report.json 应存在"

        final_prompt_path = extraction_dir / "final_prompt.json"
        assert final_prompt_path.exists(), "final_prompt.json 应存在"


# ---------------------------------------------------------------------------
# Test 4: toxicity_report 含 PR3 必需字段
# ---------------------------------------------------------------------------


def test_toxicity_report_contains_required_fields():
    """验证 toxicity_report.json 含 tested/toxic/safe/broken 等必需字段。

    使用含 toxic 样本的场景（P2 break s3），验证 patch_test_records 中
    toxic 记录的 broken_sample_ids 非空。
    """
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # P1 修复 s1（safe），P2 修复 s2 但 break s3（toxic）
        patch_effects = {
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct", "s3": "wrong"},
        }
        phase = _run_phase_with_effects(patch_effects, output_dir)

        extraction_dir = output_dir / "prompt_optimization" / "iteration_1" / "extraction"
        report = _read_json(extraction_dir / "toxicity_report.json")

        # 必需字段
        assert "tested_patch_count" in report, "缺少 tested_patch_count"
        assert "toxic_patch_count" in report, "缺少 toxic_patch_count"
        assert "safe_patch_count" in report, "缺少 safe_patch_count"
        assert "toxic_sample_ids" in report, "缺少 toxic_sample_ids"
        assert isinstance(report["toxic_sample_ids"], list), "toxic_sample_ids 应为 list"
        assert "safe_patch_ids" in report, "缺少 safe_patch_ids"
        assert isinstance(report["safe_patch_ids"], list), "safe_patch_ids 应为 list"
        assert "toxic_patch_ids" in report, "缺少 toxic_patch_ids"
        assert isinstance(report["toxic_patch_ids"], list), "toxic_patch_ids 应为 list"
        assert "patch_test_records" in report, "缺少 patch_test_records"
        assert isinstance(report["patch_test_records"], list), "patch_test_records 应为 list"
        assert "early_stop_enabled" in report, "缺少 early_stop_enabled"

        # 本场景有 toxic 样本 s3
        assert "s3" in report["toxic_sample_ids"], (
            f"toxic_sample_ids 应包含 s3，实际 {report['toxic_sample_ids']}"
        )
        assert report["toxic_patch_count"] >= 1, (
            f"toxic_patch_count 应 >= 1，实际 {report['toxic_patch_count']}"
        )
        assert report["safe_patch_count"] >= 1, (
            f"safe_patch_count 应 >= 1，实际 {report['safe_patch_count']}"
        )

        # patch_test_records 中 toxic 记录的 broken_sample_ids 非空
        toxic_records = [
            r for r in report["patch_test_records"] if r["status"] == "toxic"
        ]
        assert len(toxic_records) >= 1, "应至少有 1 条 toxic 记录"
        for record in toxic_records:
            assert len(record["broken_sample_ids"]) > 0, (
                f"toxic 记录 {record['patch_id']} 的 broken_sample_ids 不应为空"
            )
            assert "s3" in record["broken_sample_ids"], (
                f"broken_sample_ids 应包含 s3，实际 {record['broken_sample_ids']}"
            )


# ---------------------------------------------------------------------------
# Test 5: patch_test_records 可追溯
# ---------------------------------------------------------------------------


def test_patch_test_records_traceable():
    """验证 patch_test_records.jsonl 可追溯。

    每条记录含 patch_id / status / tested_sample_ids / broken_sample_ids /
    stop_reason，且 patch_id 能在 safe_patches.jsonl 或 toxic_patches.jsonl 中找到。
    """
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # 使用含 toxic 样本的场景，使 patch_test_records 同时含 safe / toxic 记录
        patch_effects = {
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct", "s3": "wrong"},
        }
        _run_phase_with_effects(patch_effects, output_dir)

        extraction_dir = output_dir / "prompt_optimization" / "iteration_1" / "extraction"

        records_path = extraction_dir / "patch_test_records.jsonl"
        assert records_path.exists(), "patch_test_records.jsonl 应存在"

        records = _read_jsonl(records_path)
        assert len(records) > 0, "patch_test_records.jsonl 不应为空"

        # 收集 safe_patches / toxic_patches 的 patch_id
        safe_patches = _read_jsonl(extraction_dir / "safe_patches.jsonl")
        toxic_patches = _read_jsonl(extraction_dir / "toxic_patches.jsonl")
        known_patch_ids = {p["id"] for p in safe_patches} | {
            p["id"] for p in toxic_patches
        }

        required_fields = {
            "patch_id",
            "status",
            "tested_sample_ids",
            "broken_sample_ids",
            "stop_reason",
        }

        for record in records:
            # 必需字段存在
            missing = required_fields - set(record.keys())
            assert not missing, f"记录缺少字段: {missing}, record={record}"

            # patch_id 可追溯到 safe / toxic patches
            assert record["patch_id"] in known_patch_ids, (
                f"patch_id {record['patch_id']} 未在 safe/toxic patches 中找到"
            )

            # status 合法
            assert record["status"] in ("safe", "toxic", "skipped"), (
                f"status 应为 safe/toxic/skipped，实际 {record['status']}"
            )

            # tested_sample_ids / broken_sample_ids 为 list
            assert isinstance(record["tested_sample_ids"], list)
            assert isinstance(record["broken_sample_ids"], list)

            # toxic 记录应有 broken_sample_ids
            if record["status"] == "toxic":
                assert len(record["broken_sample_ids"]) > 0, (
                    f"toxic 记录 {record['patch_id']} 的 broken_sample_ids 不应为空"
                )


# ---------------------------------------------------------------------------
# Test 6: extraction prompt 最终推进仅基于 safe patches
# ---------------------------------------------------------------------------


def test_extraction_prompt_advancement_based_only_on_safe_patches():
    """验证 extraction prompt 的最终推进仅基于 safe patches。

    场景：
    - base: s1=wrong, s2=wrong, s3=correct
    - 初始 merge + apply（全部 patch）: s1=correct, s2=correct, s3=wrong（BROKEN）
    - toxic_sample_ids = ["s3"]
    - 测毒: P1（来源 s1）safe，P2（来源 s2）toxic（break s3）

    验证：
    - safe_patches.jsonl 只含 P1
    - toxic_patches.jsonl 含 P2
    - final_merged_patches.jsonl 只含 P1（不含 P2）
    - final_prompt.json 内容反映 P1 的变更，不含 P2 的 patch 内容
    """
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # P1 修复 s1（safe），P2 修复 s2 但 break s3（toxic）
        patch_effects = {
            PATCH_S1_CONTENT: {"s1": "correct"},
            PATCH_S2_CONTENT: {"s2": "correct", "s3": "wrong"},
        }
        phase = _run_phase_with_effects(patch_effects, output_dir)

        extraction_dir = output_dir / "prompt_optimization" / "iteration_1" / "extraction"

        # safe_patches 只含 P1
        safe_patches = _read_jsonl(extraction_dir / "safe_patches.jsonl")
        assert len(safe_patches) == 1, (
            f"safe_patches 应只有 1 条，实际 {len(safe_patches)}"
        )
        safe_patch = safe_patches[0]
        assert "s1" in safe_patch["source_sample_ids"], (
            f"safe patch 来源应含 s1，实际 {safe_patch['source_sample_ids']}"
        )
        assert safe_patch["content"] == PATCH_S1_CONTENT, (
            f"safe patch content 应为 {PATCH_S1_CONTENT}，实际 {safe_patch['content']}"
        )

        # toxic_patches 含 P2
        toxic_patches = _read_jsonl(extraction_dir / "toxic_patches.jsonl")
        assert len(toxic_patches) == 1, (
            f"toxic_patches 应有 1 条，实际 {len(toxic_patches)}"
        )
        toxic_patch = toxic_patches[0]
        assert "s2" in toxic_patch["source_sample_ids"], (
            f"toxic patch 来源应含 s2，实际 {toxic_patch['source_sample_ids']}"
        )
        assert toxic_patch["content"] == PATCH_S2_CONTENT, (
            f"toxic patch content 应为 {PATCH_S2_CONTENT}，实际 {toxic_patch['content']}"
        )

        # final_merged_patches 只含 P1（不含 P2）
        final_merged = _read_jsonl(extraction_dir / "final_merged_patches.jsonl")
        final_ids = {p["id"] for p in final_merged}
        toxic_ids = {p["id"] for p in toxic_patches}
        assert final_ids.isdisjoint(toxic_ids), (
            "final_merged_patches 不应包含 toxic patch"
        )
        assert len(final_merged) == 1, (
            f"final_merged_patches 应只有 1 条，实际 {len(final_merged)}"
        )
        assert "s1" in final_merged[0]["source_sample_ids"], (
            f"final_merged patch 来源应含 s1，实际 {final_merged[0]['source_sample_ids']}"
        )

        # final_prompt.json 存在，内容反映 P1 的变更，不含 P2 的 patch 内容
        final_prompt = _read_json(extraction_dir / "final_prompt.json")
        section_contents = [s["content"] for s in final_prompt["sections"]]
        full_content = "\n".join(section_contents)

        assert PATCH_S1_CONTENT in full_content, (
            "final_prompt 应包含 P1 的 patch 内容"
        )
        assert PATCH_S2_CONTENT not in full_content, (
            "final_prompt 不应包含 P2 的 patch 内容"
        )

        # section_1 内容应为 P1 的 patch 内容（P1 target=section_1, replace）
        section_map = {s["id"]: s["content"] for s in final_prompt["sections"]}
        assert section_map.get("section_1") == PATCH_S1_CONTENT, (
            f"section_1 内容应为 {PATCH_S1_CONTENT}，实际 {section_map.get('section_1')}"
        )
        # section_2 内容应保持 base（P2 被拒绝，未应用）
        assert section_map.get("section_2") == "base_content_s2", (
            f"section_2 内容应保持 base_content_s2，实际 {section_map.get('section_2')}"
        )
