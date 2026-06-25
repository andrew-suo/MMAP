"""新 Patch 系统测试 - 测试 conflict 检测、clusterer 分组、text_matcher 匹配、PatchApplyExecutor 应用。"""
from __future__ import annotations

from dataclasses import asdict

from mmap_optimizer.core.config import PromptsConfig
from mmap_optimizer.executors.patch_apply_executor import PatchApplyExecutor
from mmap_optimizer.patch.clusterer import (
    categorize_by_section,
    group_by_section,
    split_oversized_group,
)
from mmap_optimizer.patch.conflict import (
    detect_add_delete_conflicts,
    detect_replace_overlaps,
    deterministic_guardrail,
    texts_overlap,
)
from mmap_optimizer.patch.text_matcher import (
    exact_match,
    fuzzy_match,
    match_text_with_fallback,
)
from mmap_optimizer.patch.tree_reduce import ParallelPatchMerger
from mmap_optimizer.patch.types import ExtractionPatch
from mmap_optimizer.prompt.structured_prompt import (
    PromptSection,
    StructuredPrompt,
)


# ===========================================================================
# 辅助构造函数
# ===========================================================================


def make_prompt(content: str = "Original content") -> StructuredPrompt:
    """构造含单个 mutable section 的 StructuredPrompt。"""
    section = PromptSection(
        id="sec1",
        title="Task",
        level=1,
        content=content,
        mutable=True,
    )
    return StructuredPrompt(
        id="p1",
        prompt_type="extraction",
        sections=[section],
        raw_markdown=f"# Task\n{content}",
        version=1,
    )


# ===========================================================================
# conflict.py 测试
# ===========================================================================


def test_texts_overlap_identical():
    """相同文本返回 True。"""
    text = "the quick brown fox jumps over the lazy dog"
    # 相同文本的 n-gram 集合完全一致，Jaccard 相似度为 1.0 > 0.5
    assert texts_overlap(text, text) is True


def test_texts_overlap_different():
    """完全不同文本返回 False。"""
    # 两段无公共字符级 8-gram 的文本
    text1 = "abcdefghijklmnopqrstuvwxyz1234567890abc"
    text2 = "0987654321zyxwvutsrqponmlkjihgfedcba"
    assert texts_overlap(text1, text2) is False


def test_detect_add_delete_conflicts():
    """ADD+DELETE 同 section 同 content → 冲突移除。"""
    patches = [
        {"id": "p1", "target_section": "sec_a", "operation_type": "append_to_section", "content": "shared content"},
        {"id": "p2", "target_section": "sec_a", "operation_type": "delete_section", "content": "shared content"},
        {"id": "p3", "target_section": "sec_b", "operation_type": "append_to_section", "content": "other content"},
    ]
    cleaned, messages = detect_add_delete_conflicts(patches)
    # p1 和 p2 冲突被移除，只剩 p3
    assert len(cleaned) == 1
    assert cleaned[0]["id"] == "p3"
    assert len(messages) == 1
    assert "p1" in messages[0]
    assert "p2" in messages[0]


def test_detect_add_delete_no_conflict():
    """不同 section 的 ADD+DELETE → 不冲突。"""
    patches = [
        {"id": "p1", "target_section": "sec_a", "operation_type": "append_to_section", "content": "shared content"},
        {"id": "p2", "target_section": "sec_b", "operation_type": "delete_section", "content": "shared content"},
    ]
    cleaned, messages = detect_add_delete_conflicts(patches)
    # 不同 section 不冲突，全部保留
    assert len(cleaned) == 2
    assert len(messages) == 0


def test_detect_replace_overlaps():
    """同 section 两个 replace 的 old_text 高度重叠 → 保留 reasoning 长的。"""
    old_text = "the quick brown fox jumps over the lazy dog"
    patches = [
        {"id": "p1", "target_section": "sec_a", "operation_type": "replace_in_section", "old_text": old_text, "rationale": "short"},
        {"id": "p2", "target_section": "sec_a", "operation_type": "replace_in_section", "old_text": old_text, "rationale": "this is a much longer reasoning explanation"},
    ]
    cleaned, messages = detect_replace_overlaps(patches)
    # old_text 完全相同 → 重叠；p2 reasoning 更长 → 保留 p2，移除 p1
    assert len(cleaned) == 1
    assert cleaned[0]["id"] == "p2"
    assert len(messages) == 1
    assert "p1" in messages[0]


def test_deterministic_guardrail():
    """串联测试：ADD/DELETE 冲突 + replace 重叠 + 干净 patch。"""
    patches = [
        # ADD/DELETE 冲突对（同 section sec_a，同 content）
        {"id": "p1", "target_section": "sec_a", "operation_type": "append_to_section", "content": "shared content"},
        {"id": "p2", "target_section": "sec_a", "operation_type": "delete_section", "content": "shared content"},
        # replace 重叠对（同 section sec_b，old_text 相同）
        {"id": "p3", "target_section": "sec_b", "operation_type": "replace_in_section", "old_text": "the quick brown fox jumps over the lazy dog", "rationale": "short"},
        {"id": "p4", "target_section": "sec_b", "operation_type": "replace_in_section", "old_text": "the quick brown fox jumps over the lazy dog", "rationale": "longer reasoning here for testing"},
        # 干净 patch（不受影响）
        {"id": "p5", "target_section": "sec_c", "operation_type": "append_to_section", "content": "unique content"},
    ]
    cleaned, messages = deterministic_guardrail(patches)
    # p1/p2 被 ADD/DELETE 冲突移除，p3 被 replace 重叠移除（p4 reasoning 更长）
    remaining_ids = {p["id"] for p in cleaned}
    assert remaining_ids == {"p4", "p5"}
    # 至少两条冲突消息
    assert len(messages) >= 2


# ===========================================================================
# clusterer.py 测试
# ===========================================================================


def test_group_by_section():
    """同 section 分到同组。"""
    patches = [
        {"id": "p1", "target_section": "sec_a"},
        {"id": "p2", "target_section": "sec_a"},
        {"id": "p3", "target_section": "sec_b"},
    ]
    groups = group_by_section(patches, branch_factor=8)
    # sec_a 的两个 patch 在同组，sec_b 单独一组
    assert len(groups) == 2
    # 组大小分别为 2 和 1
    group_sizes = sorted(len(g) for g in groups)
    assert group_sizes == [1, 2]


def test_group_by_section_oversized():
    """超过 branch_factor 时分割。"""
    # 构造 10 个同 section 的 patch，branch_factor=3
    patches = [{"id": f"p{i}", "target_section": "sec_a"} for i in range(10)]
    groups = group_by_section(patches, branch_factor=3)
    # 分割为多个子组，每个子组不超过 branch_factor
    assert len(groups) >= 2
    for group in groups:
        assert len(group) <= 3
    # 所有 patch 都被分组
    total = sum(len(g) for g in groups)
    assert total == 10


def test_categorize_by_section():
    """single_pass 和 groupable 正确分类。"""
    patches = [
        {"id": "p1", "target_section": "sec_a"},  # 单独 → single_pass
        {"id": "p2", "target_section": "sec_b"},
        {"id": "p3", "target_section": "sec_b"},  # sec_b 两个 → groupable
    ]
    groupable, single_pass = categorize_by_section(patches, branch_factor=8)
    # sec_a 的 p1 → single_pass
    assert len(single_pass) == 1
    assert single_pass[0]["id"] == "p1"
    # sec_b 的 p2/p3 → groupable
    assert len(groupable) == 1
    assert len(groupable[0]) == 2
    groupable_ids = {p["id"] for p in groupable[0]}
    assert groupable_ids == {"p2", "p3"}


def test_categorize_no_section():
    """无 target_section 的 patch 归入 single_pass。"""
    patches = [
        {"id": "p1", "target_section": "sec_a"},
        {"id": "p2", "target_section": ""},  # 空 section
        {"id": "p3"},  # 无 section 字段
    ]
    groupable, single_pass = categorize_by_section(patches, branch_factor=8)
    # 全部归入 single_pass
    assert len(groupable) == 0
    assert len(single_pass) == 3
    single_ids = {p["id"] for p in single_pass}
    assert single_ids == {"p1", "p2", "p3"}


# ===========================================================================
# text_matcher.py 测试
# ===========================================================================


def test_exact_match_found():
    """精确匹配成功。"""
    section_content = "The quick brown fox jumps over the lazy dog"
    intent_text = "quick brown fox"
    result = exact_match(section_content, intent_text)
    assert result == "quick brown fox"


def test_exact_match_not_found():
    """精确匹配失败。"""
    section_content = "The quick brown fox jumps over the lazy dog"
    intent_text = "quick brown cat"
    result = exact_match(section_content, intent_text)
    assert result is None


def test_fuzzy_match_paraphrase():
    """意译文本模糊匹配成功。"""
    section_content = "The quick brown fox jumps over the lazy dog near the river"
    intent_text = "The quick brown fox jumps over the lazy cat"
    # intent_text 不是精确子串，但与 section_content 中的子串高度相似
    result = fuzzy_match(section_content, intent_text, threshold=0.6)
    assert result is not None
    # 匹配到的子串应包含核心词汇
    assert "quick brown fox" in result


def test_fuzzy_match_unrelated():
    """不相关文本模糊匹配失败。"""
    section_content = "The quick brown fox jumps over the lazy dog"
    intent_text = "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"
    # 完全不相关的文本，相似度低于阈值
    result = fuzzy_match(section_content, intent_text, threshold=0.6)
    assert result is None


def test_match_text_with_fallback_exact():
    """降级入口精确匹配阶段成功。"""
    section_content = "The quick brown fox jumps over the lazy dog"
    intent_text = "quick brown fox"
    result = match_text_with_fallback(section_content, intent_text)
    # 精确匹配阶段即成功
    assert result == "quick brown fox"


def test_match_text_with_fallback_fuzzy():
    """降级入口模糊匹配阶段成功。"""
    section_content = "The quick brown fox jumps over the lazy dog near the river"
    intent_text = "The quick brown fox jumps over the lazy cat"
    # 精确匹配失败，模糊匹配阶段成功
    result = match_text_with_fallback(section_content, intent_text, model_client=None)
    assert result is not None
    assert "quick brown fox" in result


def test_match_text_with_fallback_no_model():
    """无 model_client 时降级到 fuzzy。"""
    section_content = "The quick brown fox jumps over the lazy dog near the river"
    intent_text = "The quick brown fox jumps over the lazy cat"
    # model_client=None，精确匹配失败后降级到 fuzzy（不调用 LLM）
    result = match_text_with_fallback(
        section_content, intent_text, model_client=None
    )
    assert result is not None
    assert "quick brown fox" in result


# ===========================================================================
# PatchApplyExecutor 测试
# ===========================================================================


def test_apply_append():
    """append_to_section 操作。"""
    prompt = make_prompt("Original content")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="append_to_section",
        content="Appended content",
        rationale="test append",
    )
    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])
    assert report.changed is True
    assert new_prompt.sections[0].content == "Original content\nAppended content"
    assert "patch1" in report.applied_patch_ids


def test_apply_replace_exact():
    """replace_in_section 精确匹配成功。"""
    prompt = make_prompt("The quick brown fox jumps over the lazy dog")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="replace_in_section",
        content="",
        rationale="test replace",
        old_text="quick brown fox",
        new_text="swift red fox",
    )
    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])
    assert report.changed is True
    assert new_prompt.sections[0].content == "The swift red fox jumps over the lazy dog"
    assert "patch1" in report.applied_patch_ids


def test_apply_replace_fuzzy():
    """replace_in_section 精确匹配失败但模糊匹配成功。"""
    prompt = make_prompt("The quick brown fox jumps over the lazy dog")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="replace_in_section",
        content="",
        rationale="test fuzzy replace",
        old_text="The quick brown fox jumps over the lazy cat",
        new_text="A swift red fox leaps over the lazy dog",
    )
    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])
    # 模糊匹配成功，patch 被应用而非拒绝
    assert report.changed is True
    assert "patch1" in report.applied_patch_ids
    # new_text 出现在结果中
    assert "A swift red fox leaps over the lazy dog" in new_prompt.sections[0].content
    # 内容已变化
    assert new_prompt.sections[0].content != "The quick brown fox jumps over the lazy dog"


def test_apply_insert_after():
    """insert_after 操作。"""
    prompt = make_prompt("line1\nline2\nline3")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="insert_after",
        content="inserted line",
        rationale="test insert",
        target_text="line2",
    )
    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])
    assert report.changed is True
    assert new_prompt.sections[0].content == "line1\nline2\ninserted line\nline3"
    assert "patch1" in report.applied_patch_ids


def test_apply_reject_old_text_not_found():
    """old_text 完全找不到时 patch 被拒绝。"""
    prompt = make_prompt("The quick brown fox jumps over the lazy dog")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="replace_in_section",
        content="",
        rationale="test reject",
        old_text="ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",
        new_text="replacement",
    )
    executor = PatchApplyExecutor()
    new_prompt, report = executor.apply(prompt, [patch])
    # 精确匹配和模糊匹配均失败，patch 被拒绝
    assert report.changed is False
    assert "patch1" in report.rejected_patch_ids
    assert patch.status == "rejected"
    assert patch.rejection_reason == "OLD_TEXT_NOT_FOUND"


def test_apply_delete_section():
    """delete_section 操作。"""
    prompt = make_prompt("Content to be deleted")
    patch = ExtractionPatch(
        id="patch1",
        target_section_id="sec1",
        operation_type="delete_section",
        content="",
        rationale="test delete",
    )
    executor = PatchApplyExecutor(allow_delete=True)
    new_prompt, report = executor.apply(prompt, [patch])
    assert report.changed is True
    assert new_prompt.sections[0].content == ""
    assert "patch1" in report.applied_patch_ids


# ===========================================================================
# ParallelPatchMerger 测试
# ===========================================================================


def test_parallel_merger_passthrough():
    """model_client=None 时 passthrough。"""
    merger = ParallelPatchMerger(
        model_client=None,
        model_config=None,
        merge_prompt_path="prompts/patch_merge.txt",
        root_merge_prompt_path="prompts/patch_root_merge.txt",
    )
    patches = [
        {"id": "p1", "target_section": "sec_a", "operation_type": "append_to_section", "content": "content1"},
        {"id": "p2", "target_section": "sec_b", "operation_type": "append_to_section", "content": "content2"},
    ]
    result = merger.merge(patches, prompt_structure="dummy structure")
    # passthrough：返回原 patches 的副本
    assert len(result) == 2
    assert result[0]["id"] == "p1"
    assert result[1]["id"] == "p2"


# ===========================================================================
# PromptsConfig 测试
# ===========================================================================


def test_prompts_config_defaults():
    """默认路径正确。"""
    config = PromptsConfig()
    assert config.extraction == "prompts/extraction.txt"
    assert config.analysis == "prompts/analysis.txt"
    assert config.analysis_reflection == "prompts/analysis_reflection.txt"
    assert config.prompt_standardization == "prompts/prompt_standardization.txt"
    assert config.patch_generation == "prompts/patch_generation.txt"
    assert config.patch_calibration == "prompts/patch_calibration.txt"
    assert config.patch_merge == "prompts/patch_merge.txt"
    assert config.patch_root_merge == "prompts/patch_root_merge.txt"
    assert config.patch_text_match == "prompts/patch_text_match.txt"


def test_prompts_config_to_dict():
    """to_dict 包含所有字段。"""
    config = PromptsConfig()
    d = asdict(config)
    expected_keys = {
        "extraction",
        "analysis",
        "analysis_reflection",
        "prompt_standardization",
        "patch_generation",
        "patch_calibration",
        "patch_merge",
        "patch_root_merge",
        "patch_text_match",
        "prompt_compression",
        "prompt_compression_validation",
    }
    assert set(d.keys()) == expected_keys
    # 抽查几个默认值
    assert d["extraction"] == "prompts/extraction.txt"
    assert d["patch_text_match"] == "prompts/patch_text_match.txt"
    assert d["patch_merge"] == "prompts/patch_merge.txt"
