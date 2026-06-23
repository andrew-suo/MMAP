"""PR3 单元测试：MergeExecutor。

覆盖 MergeExecutor 的核心行为：
1. passthrough fallback（异常 / 老系统不可用）
2. tree_merge 成功合并
3. 合并后通过 PatchValidator 校验
4. 合并后校验失败的 patch 被标记 MERGED_PATCH_VALIDATION_FAILED
5. MergeReport 字段完整性
6. 空 patch 输入
7. hierarchical_merge 回退到 tree_merge
"""

from __future__ import annotations

import pytest

from mmap_optimizer.executors import MergeExecutor
from mmap_optimizer.executors.merge_executor import _OLD_SYSTEM_AVAILABLE
from mmap_optimizer.patch_types import (
    AnalysisPatch,
    ExtractionPatch,
    PatchMergeReport,
)
from mmap_optimizer.sample import SampleSet, SampleSpec, SampleState
from mmap_optimizer.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


def make_prompt(
    prompt_id: str = "p1",
    section_id: str = "section_1",
    prompt_type: str = "extraction",
) -> StructuredPrompt:
    """构造含单个 mutable section 的 StructuredPrompt。"""
    section = PromptSection(
        id=section_id,
        title="Task",
        level=1,
        content="Original content",
        mutable=True,
    )
    return StructuredPrompt(
        id=prompt_id,
        prompt_type=prompt_type,
        sections=[section],
        raw_markdown="# Task\nOriginal content",
        version=1,
    )


def make_sample_set(sample_ids: list[str] | None = None) -> SampleSet:
    """构造含指定样本的 SampleSet。"""
    sample_ids = sample_ids or ["s1", "s2"]
    specs = {sid: SampleSpec(id=sid, input={}, ground_truth={}) for sid in sample_ids}
    states = {sid: SampleState(sample_id=sid) for sid in sample_ids}
    return SampleSet(specs=specs, states=states)


def make_extraction_patches() -> list[ExtractionPatch]:
    """构造两条 targeting 同一 section 的 ExtractionPatch（可被合并）。"""
    return [
        ExtractionPatch(
            id="p1",
            target_section_id="section_1",
            operation_type="replace",
            content="Check label missing carefully.",
            rationale="fix label issue",
            source_sample_ids=["s1"],
        ),
        ExtractionPatch(
            id="p2",
            target_section_id="section_1",
            operation_type="replace",
            content="Check install direction carefully.",
            rationale="fix direction issue",
            source_sample_ids=["s2"],
        ),
    ]


def make_analysis_patches() -> list[AnalysisPatch]:
    """构造两条 targeting 同一 section 的 AnalysisPatch。"""
    return [
        AnalysisPatch(
            id="ap1",
            target_section_id="section_1",
            operation_type="replace",
            content="Improve analysis step one.",
            rationale="analysis fix 1",
            source_sample_ids=["s1"],
        ),
        AnalysisPatch(
            id="ap2",
            target_section_id="section_1",
            operation_type="replace",
            content="Improve analysis step two.",
            rationale="analysis fix 2",
            source_sample_ids=["s2"],
        ),
    ]


# ---------------------------------------------------------------------------
# Test 1: passthrough fallback（异常路径）
# ---------------------------------------------------------------------------


def test_passthrough_fallback_on_exception(monkeypatch):
    """tree_merge 抛异常时回退到 passthrough，fallback_used=True。"""
    import mmap_optimizer.executors.merge_executor as mod

    class BoomMerger:
        def merge(self, **kwargs):
            raise RuntimeError("tree_merge boom")

    monkeypatch.setattr(mod, "_TreeReducePatchMerger", BoomMerger)

    prompt = make_prompt()
    patches = make_extraction_patches()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt)

    assert report.fallback_used is True, "异常时应回退到 passthrough"
    assert len(merged) == len(patches), "passthrough 应原样返回输入 patch"
    assert report.merged_patch_count == len(patches)
    assert report.dropped_patch_count == 0
    assert report.merged_patch_ids == ["p1", "p2"]
    assert any("tree_merge failed" in w for w in report.warnings), (
        "warnings 应包含异常信息"
    )


def test_passthrough_fallback_on_import_unavailable(monkeypatch):
    """老系统不可用时回退到 passthrough，fallback_used=True。"""
    import mmap_optimizer.executors.merge_executor as mod

    monkeypatch.setattr(mod, "_OLD_SYSTEM_AVAILABLE", False)

    prompt = make_prompt()
    patches = make_extraction_patches()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt)

    assert report.fallback_used is True, "老系统不可用时应回退"
    assert len(merged) == len(patches)
    assert any("unavailable" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Test 2: tree_merge 成功合并
# ---------------------------------------------------------------------------


def test_tree_merge_success():
    """多条 patch targeting 同一 section 被合并为更少的 patch。"""
    prompt = make_prompt()
    patches = make_extraction_patches()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt)

    assert report.fallback_used is False, "正常合并不应使用 fallback"
    assert len(merged) < len(patches), "合并后 patch 数应减少"
    assert len(merged) == 1, f"两条同 section patch 应合并为 1 条，实际 {len(merged)}"
    assert report.merged_patch_count == 1
    assert report.input_patch_count == 2
    # 合并后的 patch 应包含两条原始 patch 的内容
    merged_content = merged[0].content
    assert "Check label missing" in merged_content
    assert "Check install direction" in merged_content
    # 合并后 source_sample_ids 应聚合
    assert set(merged[0].source_sample_ids) == {"s1", "s2"}
    # 合并后 status 应为 merged（未做 post-merge validation）
    assert merged[0].status == "merged"


def test_tree_merge_success_analysis_patches():
    """AnalysisPatch 也能通过 tree_merge 合并。"""
    prompt = make_prompt(prompt_type="analysis")
    patches = make_analysis_patches()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt)

    assert report.fallback_used is False
    assert len(merged) == 1
    assert isinstance(merged[0], AnalysisPatch)
    assert "Improve analysis step one" in merged[0].content
    assert "Improve analysis step two" in merged[0].content


# ---------------------------------------------------------------------------
# Test 3: 合并后通过 PatchValidator 校验
# ---------------------------------------------------------------------------


def test_post_merge_validation_passes():
    """合并后的 patch 通过 PatchValidator 校验，status=candidate。"""
    prompt = make_prompt()
    patches = make_extraction_patches()
    sample_set = make_sample_set()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt, sample_set=sample_set)

    assert len(merged) == 1
    patch = merged[0]
    assert patch.status == "candidate", (
        f"校验通过的 patch status 应为 candidate，实际 {patch.status}"
    )
    assert patch.rejection_reason is None, (
        f"校验通过的 patch rejection_reason 应为 None，实际 {patch.rejection_reason}"
    )


# ---------------------------------------------------------------------------
# Test 4: 合并后校验失败的 patch 被标记
# ---------------------------------------------------------------------------


def test_invalid_merged_patch_rejected():
    """合并后 target_section_id 无效的 patch 被标记 MERGED_PATCH_VALIDATION_FAILED。"""
    prompt = make_prompt(section_id="section_1")
    # patch targeting 不存在的 section
    patches = [
        ExtractionPatch(
            id="p1",
            target_section_id="nonexistent_section",
            operation_type="replace",
            content="Check label missing carefully.",
            rationale="fix",
            source_sample_ids=["s1"],
        ),
        ExtractionPatch(
            id="p2",
            target_section_id="nonexistent_section",
            operation_type="replace",
            content="Check install direction carefully.",
            rationale="fix",
            source_sample_ids=["s2"],
        ),
    ]
    sample_set = make_sample_set()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt, sample_set=sample_set)

    assert len(merged) == 1, "tree_merge 仍应合并"
    patch = merged[0]
    assert patch.status == "rejected", (
        f"校验失败的 patch status 应为 rejected，实际 {patch.status}"
    )
    assert patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED", (
        f"rejection_reason 应为 MERGED_PATCH_VALIDATION_FAILED，"
        f"实际 {patch.rejection_reason}"
    )
    assert any("failed post-merge validation" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Test 5: MergeReport 字段完整性
# ---------------------------------------------------------------------------


def test_merge_report_fields_complete():
    """所有 MergeReport 字段都被正确填充。"""
    prompt = make_prompt()
    patches = make_extraction_patches()
    sample_set = make_sample_set()
    executor = MergeExecutor()
    merged, report = executor.merge(patches, prompt, sample_set=sample_set)

    # 基础字段
    assert report.id == f"merge_report_{prompt.id}"
    assert report.input_patch_count == 2
    assert report.merged_patch_count == 1
    assert isinstance(report.conflict_count, int)

    # 新增字段
    assert report.strategy == "tree_merge"
    assert report.dropped_patch_count == 0
    assert report.input_patch_ids == ["p1", "p2"]
    assert len(report.merged_patch_ids) == 1
    assert report.dropped_patch_ids == []
    assert isinstance(report.conflict_patch_ids, list)
    assert isinstance(report.merge_reason, str) and report.merge_reason != ""
    assert report.fallback_used is False
    assert isinstance(report.warnings, list)

    # merged_patches 应为 dict 列表
    assert isinstance(report.merged_patches, list)
    assert len(report.merged_patches) == 1
    assert isinstance(report.merged_patches[0], dict)
    assert "id" in report.merged_patches[0]

    # to_dict / from_dict 往返
    data = report.to_dict()
    assert "strategy" in data
    assert "dropped_patch_count" in data
    assert "input_patch_ids" in data
    assert "merged_patch_ids" in data
    assert "dropped_patch_ids" in data
    assert "conflict_patch_ids" in data
    assert "merge_reason" in data
    assert "fallback_used" in data
    assert "warnings" in data

    restored = PatchMergeReport.from_dict(data)
    assert restored.id == report.id
    assert restored.input_patch_count == report.input_patch_count
    assert restored.merged_patch_count == report.merged_patch_count
    assert restored.strategy == report.strategy
    assert restored.dropped_patch_count == report.dropped_patch_count
    assert restored.input_patch_ids == report.input_patch_ids
    assert restored.merged_patch_ids == report.merged_patch_ids
    assert restored.dropped_patch_ids == report.dropped_patch_ids
    assert restored.conflict_patch_ids == report.conflict_patch_ids
    assert restored.merge_reason == report.merge_reason
    assert restored.fallback_used == report.fallback_used
    assert restored.warnings == report.warnings


# ---------------------------------------------------------------------------
# Test 6: 空 patch 输入
# ---------------------------------------------------------------------------


def test_empty_patches():
    """空 patch 输入返回空输出，report 字段正确。"""
    prompt = make_prompt()
    executor = MergeExecutor()
    merged, report = executor.merge([], prompt)

    assert merged == [], "空输入应返回空列表"
    assert report.input_patch_count == 0
    assert report.merged_patch_count == 0
    assert report.dropped_patch_count == 0
    assert report.input_patch_ids == []
    assert report.merged_patch_ids == []
    assert report.dropped_patch_ids == []
    assert report.fallback_used is False
    assert any("empty" in w.lower() for w in report.warnings)


def test_empty_patches_with_sample_set():
    """空 patch 输入 + sample_set 也应正常返回。"""
    prompt = make_prompt()
    sample_set = make_sample_set()
    executor = MergeExecutor()
    merged, report = executor.merge([], prompt, sample_set=sample_set)

    assert merged == []
    assert report.input_patch_count == 0
    assert report.merged_patch_count == 0


# ---------------------------------------------------------------------------
# Test 7: hierarchical_merge 回退到 tree_merge
# ---------------------------------------------------------------------------


def test_hierarchical_merge_falls_back_to_tree_merge():
    """hierarchical_merge 策略等价于 tree_merge。"""
    prompt = make_prompt()
    patches = make_extraction_patches()
    executor = MergeExecutor()
    merged, report = executor.merge(
        patches, prompt, merge_strategy="hierarchical_merge"
    )

    # 应成功合并（与 tree_merge 行为一致）
    assert report.fallback_used is False, (
        "hierarchical_merge 不应触发 passthrough fallback"
    )
    assert len(merged) == 1, "hierarchical_merge 应与 tree_merge 行为一致"
    assert report.strategy == "hierarchical_merge"
    assert any("hierarchical_merge falls back to tree_merge" in w for w in report.warnings), (
        "warnings 应提示 hierarchical_merge 回退到 tree_merge"
    )


def test_hierarchical_merge_with_validation():
    """hierarchical_merge + sample_set 也能正常校验。"""
    prompt = make_prompt()
    patches = make_extraction_patches()
    sample_set = make_sample_set()
    executor = MergeExecutor()
    merged, report = executor.merge(
        patches, prompt, merge_strategy="hierarchical_merge", sample_set=sample_set
    )

    assert len(merged) == 1
    assert merged[0].status == "candidate"
    assert merged[0].rejection_reason is None
