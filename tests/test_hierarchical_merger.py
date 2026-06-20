import json

from mmap_optimizer.model.client import MockModelClient, ModelResponse
from mmap_optimizer.patch.hierarchical_merger import (
    HierarchicalMergeConfig,
    HierarchicalPatchMerger,
    _group_by_section,
    _normalize_text_for_match,
    _texts_overlap,
    deterministic_guardrail,
)
from mmap_optimizer.patch.schema import Patch


def _make_patch(
    patch_id: str = "patch_001",
    section_id: str = "rules",
    operation_mode: str = "append",
    patch_text: str = "Add a new rule",
    rationale: str = "This rule is needed because...",
    **kwargs,
) -> Patch:
    """创建测试用 Patch 对象"""
    return Patch(
        id=patch_id,
        type="prompt_patch",
        status="draft",
        target_prompt_type="extraction",
        base_version_id="extraction_prompt_v1",
        section_id=section_id,
        operation_type=kwargs.pop("operation_type", "ADD_RULE"),
        operation_mode=operation_mode,
        intent_name=kwargs.pop("intent_name", patch_id),
        intent_description=kwargs.pop("intent_description", patch_id),
        patch_text=patch_text,
        rationale=rationale,
        source_sample_ids=kwargs.pop("source_sample_ids", ["s1"]),
        risk_level=kwargs.pop("risk_level", "low"),
        **kwargs,
    )


class _ScriptedMockClient(MockModelClient):
    """按顺序返回预设响应的 Mock 客户端，用于模拟 LLM 合并结果。

    继承自 MockModelClient；当预设响应耗尽后回退到父类默认行为
    （返回 default_output，非 JSON 数组，会被 merger 视为失败）。
    """

    def __init__(self, responses):
        super().__init__()
        self._responses = list(responses)
        self._index = 0

    def complete(self, messages, model_config=None, response_format=None):
        if self._index < len(self._responses):
            raw = self._responses[self._index]
            self._index += 1
            return ModelResponse(raw_output=raw)
        return super().complete(messages, model_config, response_format)


class _FailingMockClient(MockModelClient):
    """始终抛出异常的 Mock 客户端，用于模拟 LLM 调用失败。"""

    def complete(self, messages, model_config=None, response_format=None):
        raise RuntimeError("LLM 调用模拟失败")


# ---------- 1. 辅助函数测试 ----------


def test_normalize_text_for_match():
    # 测试去除标点、合并空白、转小写
    # 去除标点
    assert _normalize_text_for_match("Hello, World!") == "hello world"
    # 合并连续空白
    assert _normalize_text_for_match("  Multiple   Spaces  ") == "multiple spaces"
    # 转小写（连字符作为标点会被去除，故 UPPER-CASE → uppercase）
    assert _normalize_text_for_match("UPPER-CASE Text") == "uppercase text"
    # 空字符串
    assert _normalize_text_for_match("") == ""


def test_texts_overlap_substring():
    # 子串包含检测
    assert _texts_overlap("hello world", "world") is True
    assert _texts_overlap("world", "hello world") is True
    assert _texts_overlap("abc def", "def") is True


def test_texts_overlap_ngram():
    # N-gram 重叠率检测（非子串包含但 3-gram 重叠率高）
    text_a = "the quick brown fox jumps"
    text_b = "the quick brown fox runs"
    # 两段文本共享大量 3-gram，重叠率 >= 0.5
    assert _texts_overlap(text_a, text_b) is True


def test_texts_overlap_no_overlap():
    # 无重叠
    assert _texts_overlap("completely different text here", "xyz abc 123 456") is False
    # 空文本不重叠
    assert _texts_overlap("", "some text") is False
    assert _texts_overlap("some text", "") is False


# ---------- 2. deterministic_guardrail 测试 ----------


def test_guardrail_add_delete_conflict():
    # 同一 section 同一 content 的 ADD 和 DELETE 操作应被拘留
    p_add = _make_patch("p1", section_id="rules", operation_mode="append", patch_text="rule A")
    p_del = _make_patch("p2", section_id="rules", operation_mode="delete", patch_text="rule A")

    kept, detained = deterministic_guardrail([p_add, p_del])

    # ADD 与 DELETE 冲突，两者均被拘留
    assert len(kept) == 0
    assert len(detained) == 2
    # save_detention=True 应标记状态与拒绝原因
    assert all(p.status == "rejected" for p in detained)
    assert all(p.rejection_reason == "DETERMINISTIC_CONFLICT" for p in detained)


def test_guardrail_replace_overlap_conflict():
    # 同一 section 内 replace_in_section 的 old_text 重叠应被拘留，保留 rationale 更长的
    p_short = _make_patch(
        "p1",
        section_id="rules",
        operation_mode="replace_in_section",
        patch_text="new text",
        rationale="short",
        old_text="the quick brown fox",
    )
    p_long = _make_patch(
        "p2",
        section_id="rules",
        operation_mode="replace_in_section",
        patch_text="new text",
        rationale="this is a much longer rationale with more evidence",
        old_text="the quick brown fox jumps",
    )

    kept, detained = deterministic_guardrail([p_short, p_long])

    # p_long 的 rationale 更长，应保留；p_short 应被拘留
    assert [p.id for p in kept] == ["p2"]
    assert [p.id for p in detained] == ["p1"]


def test_guardrail_no_conflict():
    # 无冲突的 patches 应全部保留
    p1 = _make_patch("p1", section_id="rules", operation_mode="append", patch_text="rule A")
    p2 = _make_patch("p2", section_id="rules", operation_mode="append", patch_text="rule B")

    kept, detained = deterministic_guardrail([p1, p2])

    assert len(kept) == 2
    assert len(detained) == 0


def test_guardrail_different_sections():
    # 不同 section 的 patches 不应冲突
    p_add = _make_patch("p1", section_id="rules", operation_mode="append", patch_text="rule A")
    p_del = _make_patch("p2", section_id="other", operation_mode="delete", patch_text="rule A")

    kept, detained = deterministic_guardrail([p_add, p_del])

    # 不同 section 的 ADD/DELETE 不构成冲突
    assert len(kept) == 2
    assert len(detained) == 0


# ---------- 3. _group_by_section 测试 ----------


def test_group_by_section_single_section():
    # 单 section 的 patches 应在一个分组中
    patches = [_make_patch(f"p{i}", section_id="rules") for i in range(3)]

    groups = _group_by_section(patches, branch_factor=8)

    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_group_by_section_multiple_sections():
    # 多 section 的 patches 应分开分组
    patches = [
        *[_make_patch(f"r{i}", section_id="rules") for i in range(2)],
        *[_make_patch(f"v{i}", section_id="visual") for i in range(2)],
    ]

    groups = _group_by_section(patches, branch_factor=8)

    assert len(groups) == 2
    # 每组 2 个
    assert all(len(g) == 2 for g in groups)


def test_group_by_section_branch_factor():
    # 超过 branch_factor 的 section 应拆分为多个分组
    patches = [_make_patch(f"p{i}", section_id="rules") for i in range(10)]

    groups = _group_by_section(patches, branch_factor=3)

    # 10 / 3 = 3 余 1，共 4 组
    assert len(groups) == 4
    assert [len(g) for g in groups] == [3, 3, 3, 1]


def test_group_by_section_no_section():
    # 无 section_id 的 patches 应归入 no_section bucket
    patches = [_make_patch(f"p{i}", section_id="") for i in range(2)]

    groups = _group_by_section(patches, branch_factor=8)

    # 空 section_id 统一归入 no_section bucket，成一组
    assert len(groups) == 1
    assert len(groups[0]) == 2


# ---------- 4. HierarchicalPatchMerger.merge 测试 ----------


def test_merge_empty_patches():
    # 空 patches 列表应返回空结果
    merger = HierarchicalPatchMerger(model_client=MockModelClient())

    result = merger.merge(round_id="round_000001", patches=[], prompt_structure="- rules: Rules")

    assert result.final_patches == []
    assert result.rejected_patches == []
    assert result.layer_count == 0


def test_merge_single_patch():
    # 单个 patch 应直接返回（无需 LLM 合并）
    patch = _make_patch("p1", section_id="rules")
    merger = HierarchicalPatchMerger(model_client=MockModelClient())

    result = merger.merge(round_id="round_000001", patches=[patch], prompt_structure="- rules: Rules")

    assert len(result.final_patches) == 1
    assert result.final_patches[0].id == "p1"
    # 单 patch 不进入递归循环
    assert result.layer_count == 0


def test_merge_with_llm_success():
    # 使用 MockModelClient 模拟 LLM 合并成功，2 个 patches → 1 个合并后的 patch
    patches = [
        _make_patch("p1", section_id="rules", patch_text="rule A"),
        _make_patch("p2", section_id="rules", patch_text="rule B"),
    ]
    merged_output = json.dumps(
        [{"id": "merged_001", "patch_text": "合并后的规则 A 和 B", "rationale": "合并理由"}],
        ensure_ascii=False,
    )
    client = _ScriptedMockClient([merged_output])
    # max_retries=0 避免失败时引入 sleep
    merger = HierarchicalPatchMerger(
        model_client=client,
        config=HierarchicalMergeConfig(max_retries=0),
    )

    result = merger.merge(round_id="round_000001", patches=patches, prompt_structure="- rules: Rules")

    # 合并后剩 1 个 patch
    assert len(result.final_patches) == 1
    assert result.final_patches[0].id == "merged_001"
    assert result.used_fallback is False
    assert result.layer_count >= 1


def test_merge_with_llm_failure_fallback():
    # LLM 调用失败时，原始 patches 应传递到下一层
    patches = [
        _make_patch("p1", section_id="rules", patch_text="rule A"),
        _make_patch("p2", section_id="rules", patch_text="rule B"),
    ]
    client = _FailingMockClient()
    # max_retries=0 避免重试 sleep 拖慢测试
    merger = HierarchicalPatchMerger(
        model_client=client,
        config=HierarchicalMergeConfig(max_retries=0),
    )

    result = merger.merge(round_id="round_000001", patches=patches, prompt_structure="- rules: Rules")

    # 失败后原始 patches 透传
    assert len(result.final_patches) == 2
    assert result.used_fallback is True
    assert {p.id for p in result.final_patches} == {"p1", "p2"}


def test_merge_with_bloat_detection():
    # LLM 返回比输入更多的 patches 时应触发膨胀检测
    patches = [
        _make_patch("p1", section_id="rules", patch_text="rule A"),
        _make_patch("p2", section_id="rules", patch_text="rule B"),
    ]
    # 返回 3 个 patch（比输入 2 个多），触发膨胀检测
    bloat_output = json.dumps(
        [
            {"id": "b1", "patch_text": "rule A"},
            {"id": "b2", "patch_text": "rule B"},
            {"id": "b3", "patch_text": "rule C"},
        ],
        ensure_ascii=False,
    )
    client = _ScriptedMockClient([bloat_output])
    merger = HierarchicalPatchMerger(
        model_client=client,
        config=HierarchicalMergeConfig(max_retries=0),
    )

    result = merger.merge(round_id="round_000001", patches=patches, prompt_structure="- rules: Rules")

    # 膨胀检测触发后回退，原始 patches 透传
    assert len(result.final_patches) == 2
    assert result.used_fallback is True

    # 直接验证 _merge_single_group 的膨胀检测行为：返回 success=False
    merger_direct = HierarchicalPatchMerger(
        model_client=_ScriptedMockClient([bloat_output]),
        config=HierarchicalMergeConfig(max_retries=0),
    )
    merged, success = merger_direct._merge_single_group(
        list(patches), "- rules: Rules", "raw_patches", max_retries=0,
    )
    assert success is False
    assert len(merged) == 2


def test_merge_root_merge_applied():
    # 多层合并后应执行 root merge
    # 3 个不同 section 的 patch → 每组 1 个，不触发组内 LLM，直接进入 root merge
    patches = [
        _make_patch("p1", section_id="rules", patch_text="rule A"),
        _make_patch("p2", section_id="visual", patch_text="rule B"),
        _make_patch("p3", section_id="output", patch_text="rule C"),
    ]
    root_merged_output = json.dumps(
        [{"id": "root_merged_001", "patch_text": "全局合并后的规则", "rationale": "根合并理由"}],
        ensure_ascii=False,
    )
    client = _ScriptedMockClient([root_merged_output])
    merger = HierarchicalPatchMerger(model_client=client)

    result = merger.merge(
        round_id="round_000001",
        patches=patches,
        prompt_structure="- rules: Rules\n- visual: Visual\n- output: Output",
    )

    # root merge 将 3 个 patch 合并为 1 个
    assert len(result.final_patches) == 1
    assert result.final_patches[0].id == "root_merged_001"
