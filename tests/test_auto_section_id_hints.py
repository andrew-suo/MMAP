"""Tests for auto-generated section_id_hints (pinyin fallback + LLM hint generator)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import (
    _pinyin_slug,
    initialize_prompt_version,
    normalize_section_id,
    parse_markdown_sections,
)
from mmap_optimizer.prompt.hint_generator import (
    auto_generate_hints,
    _extract_headings,
    _headings_covered_by_generic,
)


# ─────────── fixtures ───────────

def _contract(prompt_type=PromptType.EXTRACTION):
    return OutputSchemaContract(
        id="test-contract",
        prompt_type=prompt_type,
        version=1,
        schema={"type": "object"},
        primary_answer_fields=["result"],
    )


SCENARIO_PROMPT = """## 1. 角色与任务范围

你是电信机房工业质检工程师，负责检查机柜内布线质量。

## 2. 结果判定总逻辑

### 2.1 不合格
任意步骤发现明确不合格情况即判定 FAIL。

### 2.2 可接受
未满足 FAIL 条件时判定 PASS。

## 3. 检查步骤

### 3.1 第一步：检查场景适用性
判断图片是否属于机柜内部布线场景。

### 3.2 第二步：检查线缆是否严重凌乱
不合格判定：线缆极其凌乱。

### 3.3 第三步：检查是否存在明显杂物
不合格判定：工具类物品直接散落在机柜内部。

### 3.4 第四步：给出最终结果
有 FAIL 条件 → NG。

## 4. 边界情况处理
图片模糊：只输出能确认的证据。

## 5. 禁止行为
不要猜测不可见内容。

## 6. 输出格式
必须只输出合法 JSON。
"""


# ─────────── 1. Pinyin slug fallback ───────────

def test_pinyin_slug_produces_snake_case_from_chinese():
    slug = _pinyin_slug("严重凌乱")
    assert slug == "yan_zhong_ling_luan"


def test_pinyin_slug_strips_leading_numbers():
    slug = _pinyin_slug("3.2 第二步：检查线缆是否严重凌乱")
    assert "jian_cha" in slug
    assert slug.startswith("di_er_bu")


def test_pinyin_slug_returns_empty_for_english():
    assert _pinyin_slug("Quality Criteria") == ""


def test_pinyin_slug_returns_empty_for_pure_numbers():
    assert _pinyin_slug("2.1") == ""


def test_pinyin_slug_returns_empty_for_empty():
    assert _pinyin_slug("") == ""


def test_normalize_section_id_uses_pinyin_fallback_for_chinese_without_hints():
    sid = normalize_section_id("检查线缆是否严重凌乱")
    # Should not be section_NNN — should be a pinyin slug
    assert not sid.startswith("section_")
    assert "jian_cha" in sid or "xian_lan" in sid


def test_normalize_section_id_hints_take_priority_over_pinyin():
    sid = normalize_section_id(
        "检查线缆是否严重凌乱",
        section_id_hints={"严重凌乱": "cable_check"},
    )
    assert sid == "cable_check"


def test_normalize_section_id_generic_hints_take_priority_over_pinyin():
    # "边界情况处理" should match generic hint "边界情况" → edge_cases
    sid = normalize_section_id("边界情况处理")
    assert sid == "edge_cases"


def test_pinyin_slug_not_business_id():
    BUSINESS_IDS = {"scene_check", "cable_check", "debris_check"}
    for title in ("线缆凌乱", "明显杂物", "检查场景适用性"):
        sid = normalize_section_id(title)
        assert sid not in BUSINESS_IDS, f"{title!r} → {sid!r} leaked business id"


def test_pinyin_slug_deterministic():
    results = [_pinyin_slug("严重凌乱") for _ in range(5)]
    assert len(set(results)) == 1


# ─────────── 2. Hint generator module ───────────

def test_extract_headings_from_markdown():
    headings = _extract_headings(SCENARIO_PROMPT)
    assert len(headings) >= 6
    assert "3.2 第二步：检查线缆是否严重凌乱" in headings


def test_extract_headings_empty_prompt():
    assert _extract_headings("") == []
    assert _extract_headings("no headings here") == []


def test_headings_covered_by_generic():
    titles = [
        "1. 角色与任务范围",
        "6. 输出格式",
        "4. 边界情况处理",
        "3.2 第二步：检查线缆是否严重凌乱",
    ]
    covered = _headings_covered_by_generic(titles)
    # "角色与任务范围" → role_definition (generic)
    # "输出格式" → output_schema (generic)
    # "边界情况处理" → edge_cases (generic)
    # "检查线缆是否严重凌乱" → NOT covered by generic
    assert "1. 角色与任务范围" in covered
    assert "6. 输出格式" in covered
    assert "4. 边界情况处理" in covered
    assert "3.2 第二步：检查线缆是否严重凌乱" not in covered


def test_auto_generate_hints_with_mock_model():
    mock_response = json.dumps({
        "严重凌乱": "cable_check",
        "明显杂物": "debris_check",
        "场景适用性": "scene_check",
        "最终结果": "final_decision",
    })
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(raw_output=mock_response)

    hints = auto_generate_hints(SCENARIO_PROMPT, mock_client)
    assert "严重凌乱" in hints
    assert hints["严重凌乱"] == "cable_check"
    assert "明显杂物" in hints
    assert hints["明显杂物"] == "debris_check"


def test_auto_generate_hints_validates_snake_case():
    mock_response = json.dumps({
        "严重凌乱": "cable_check",
        "杂物": "Invalid-Id",
        "场景": "123bad",
    })
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(raw_output=mock_response)

    hints = auto_generate_hints(SCENARIO_PROMPT, mock_client)
    assert "严重凌乱" in hints
    assert "杂物" not in hints  # Invalid-Id rejected
    assert "场景" not in hints  # 123bad rejected


def test_auto_generate_hints_handles_malformed_json():
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(raw_output="not json at all")

    hints = auto_generate_hints(SCENARIO_PROMPT, mock_client)
    assert hints == {}


def test_auto_generate_hints_handles_json_in_code_fence():
    mock_response = '```json\n{"严重凌乱": "cable_check"}\n```'
    mock_client = MagicMock()
    mock_client.complete.return_value = MagicMock(raw_output=mock_response)

    hints = auto_generate_hints(SCENARIO_PROMPT, mock_client)
    assert hints.get("严重凌乱") == "cable_check"


def test_auto_generate_hints_empty_prompt():
    mock_client = MagicMock()
    hints = auto_generate_hints("", mock_client)
    assert hints == {}
    mock_client.complete.assert_not_called()


def test_auto_generate_hints_all_covered_by_generic():
    """If all headings are covered by generic hints, no LLM call is made."""
    prompt = """## 角色定义
A

## 输出格式
B
"""
    mock_client = MagicMock()
    hints = auto_generate_hints(prompt, mock_client)
    assert hints == {}
    mock_client.complete.assert_not_called()


# ─────────── 3. Integration: pinyin fallback in full pipeline ───────────

def test_chinese_prompt_without_hints_produces_pinyin_ids():
    """Full pipeline: Chinese prompt without hints should produce pinyin slugs, not section_NNN."""
    ids = [s["id"] for s in parse_markdown_sections(SCENARIO_PROMPT)]
    # At least some IDs should be pinyin slugs (not section_NNN)
    pinyin_ids = [i for i in ids if not i.startswith("section_") and not i in {
        "role_definition", "quality_criteria", "edge_cases", "prohibited_behavior",
        "output_schema", "legacy_unmapped",
    }]
    assert len(pinyin_ids) > 0, f"Expected pinyin IDs but got: {ids}"


def test_chinese_prompt_with_hints_overrides_pinyin():
    """Manual hints should produce semantic IDs, not pinyin slugs."""
    hints = {
        "场景适用性": "scene_check",
        "严重凌乱": "cable_check",
        "明显杂物": "debris_check",
    }
    ids = [s["id"] for s in parse_markdown_sections(SCENARIO_PROMPT, section_id_hints=hints)]
    assert "scene_check" in ids
    assert "cable_check" in ids
    assert "debris_check" in ids
