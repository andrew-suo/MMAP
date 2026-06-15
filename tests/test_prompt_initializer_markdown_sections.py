from __future__ import annotations

import pytest

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import (
    GENERIC_SECTION_ID_HINTS,
    extract_bullet_metadata,
    initialize_prompt_version,
    normalize_section_id,
    parse_markdown_sections,
)
from mmap_optimizer.prompt.health import check_prompt_health


def _contract(prompt_type=PromptType.EXTRACTION):
    return OutputSchemaContract(
        id="test-contract",
        prompt_type=prompt_type,
        version=1,
        schema={"type": "object"},
        primary_answer_fields=["result"],
    )


INDUSTRIAL_PROMPT = """## 1. 角色与任务范围

你是电信机房工业质检工程师，负责检查机柜内布线质量。

## 2. 结果判定总逻辑

### 2.1 NOT_INVOLVED（不涉及）
图片根本不是机柜内部布线场景。

### 2.2 FAIL（不合格）
任意步骤发现明确不合格情况，即判 FAIL：
- 线缆极其凌乱，呈严重网状散乱（蜘蛛网状）
- 存在大面积交叉、线缆之间空隙明显
- 工具类物品直接散落在机柜内部

### 2.3 PASS（可接受）
未满足 FAIL 或 NOT_INVOLVED 条件时，判定为 PASS。

## 3. 检查步骤

### 3.1 第一步：检查场景适用性
判断图片是否属于机柜内部布线场景。
- 若完全看不到机柜内部、设备、线缆，则 result = UNCERTAIN

### 3.2 第二步：检查线缆是否"严重凌乱"
核心原则：以是否导致机柜内线缆不整齐或存在安全隐患为核心判断标准。

不合格判定（FAIL）：
- 线缆极其凌乱，呈严重网状散乱（蜘蛛网状）
- 存在大面积交叉、线缆之间空隙明显
- 光纤或线缆散落在机柜内部平台

排除范围（不视为 FAIL）：
- 正常弯曲、缠绕
- 飞线不视为严重凌乱

### 3.3 第三步：检查是否存在明显杂物
核心原则：以是否存在杂物或导致机柜内部杂乱为核心判断标准。

不合格判定（FAIL）：
- 工具类物品直接散落在机柜内部
- 设备类散乱摆放
- 包装类杂物大面积堆放

排除范围（不视为 FAIL）：
- 塑料袋内仅装有未使用的线缆、螺丝等备用零件
- 纸质文件放置于机柜内部，未造成环境杂乱

### 3.4 第四步：给出最终结果
- 有 FAIL 条件 → NG
- 无 FAIL 且不是 NOT_INVOLVED → OK

## 4. 边界情况处理
- 图片模糊：只输出能确认的证据
- 飞线不视为严重凌乱

## 5. 禁止行为
- 不要猜测不可见内容
- 不要修改、扩展或省略输出 schema

## 6. 输出格式
必须只输出合法 JSON。
字段：
- result
- confidence
- evidence
- used_prompt_sections
"""


DOMAIN_HINTS = {
    "场景适用": "scene_check",
    "检查场景": "scene_check",
    "线缆": "cable_check",
    "布线": "cable_check",
    "严重凌乱": "cable_check",
    "杂物": "debris_check",
    "工具": "debris_check",
    "包装": "debris_check",
    "最终结果": "final_decision",
    "给出最终结果": "final_decision",
}


# ──────────────── Markdown heading parsing ─────────────────


def test_markdown_headings_parse_into_multiple_sections():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT)
    assert len(sections) > 1, "expected multiple sections"
    ids = [s["id"] for s in sections]
    assert not all(i == "legacy_unmapped" for i in ids), "expected structured ids"


def test_plain_text_prompt_falls_back_to_legacy_unmapped():
    text = "你是一个助手。请回答用户的问题。"
    sections = parse_markdown_sections(text)
    assert sections == []
    version = initialize_prompt_version(text, PromptType.EXTRACTION, _contract())
    section_ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in section_ids
    assert version.prompt_ir.section_by_id("legacy_unmapped").content.strip()


def test_empty_prompt_falls_back_to_legacy_unmapped():
    version = initialize_prompt_version("", PromptType.EXTRACTION, _contract())
    section_ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in section_ids


def test_single_heading_prompt_falls_back_to_legacy_unmapped():
    text = "# 唯一标题\n内容放在这里。"
    sections = parse_markdown_sections(text)
    assert sections == []
    version = initialize_prompt_version(text, PromptType.EXTRACTION, _contract())
    section_ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in section_ids


# ──────────────── section_id hints ─────────────────


def test_generic_hints_produce_expected_ids():
    prompt = """## 角色与任务范围
你是一个工程师。

## 输出格式
必须输出 JSON。

## 禁止行为
不要猜测不可见内容。
"""
    sections = parse_markdown_sections(prompt)
    ids = [s["id"] for s in sections]
    assert "role_definition" in ids
    assert "output_schema" in ids
    assert "prohibited_behavior" in ids


def test_domain_hints_produce_domain_specific_ids():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT, section_id_hints=DOMAIN_HINTS)
    ids = [s["id"] for s in sections]
    assert "scene_check" in ids
    assert "cable_check" in ids
    assert "debris_check" in ids
    assert "final_decision" in ids


def test_without_domain_hints_still_parses_multiple_sections():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT)
    ids = [s["id"] for s in sections]
    assert len(ids) > 1
    assert not all(i == "legacy_unmapped" for i in ids)


def test_without_domain_hints_does_not_guarantee_business_ids():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT)
    ids = set(s["id"] for s in sections)
    # If any of these appear it must be because the generic hints or slug
    # matched — the important thing is that they are NOT hardcoded by the
    # framework for business purposes.
    ids_without_generic_override = ids - {"scene_check", "cable_check", "debris_check"}
    assert len(ids_without_generic_override) >= 2


# ──────────────── section content preserved ─────────────────


def _build_version(hints):
    return initialize_prompt_version(
        INDUSTRIAL_PROMPT,
        PromptType.EXTRACTION,
        _contract(),
        section_id_hints=hints,
    )


def test_cable_check_content_preserved():
    version = _build_version(DOMAIN_HINTS)
    cable = version.prompt_ir.section_by_id("cable_check")
    assert cable is not None
    assert "线缆" in cable.content or "线缆是否" in cable.content
    assert "严重凌乱" in cable.content
    assert "排除范围" in cable.content


def test_debris_check_content_preserved():
    version = _build_version(DOMAIN_HINTS)
    debris = version.prompt_ir.section_by_id("debris_check")
    assert debris is not None
    assert "明显杂物" in debris.content
    assert "工具类物品" in debris.content
    assert "包装类杂物" in debris.content


def test_scene_check_content_preserved():
    version = _build_version(DOMAIN_HINTS)
    scene = version.prompt_ir.section_by_id("scene_check")
    assert scene is not None
    assert "场景适用性" in scene.content
    assert "机柜内部" in scene.content


# ──────────────── order / stability / duplicates ─────────────────


def test_section_order_preserved_via_rendering_order():
    version = _build_version(DOMAIN_HINTS)
    order = version.prompt_ir.rendering_order
    role_idx = order.index("role_definition")
    decision_idx = order.index("decision_logic") if "decision_logic" in order else None
    scene_idx = order.index("scene_check")
    cable_idx = order.index("cable_check")
    debris_idx = order.index("debris_check")
    assert role_idx < (decision_idx if decision_idx is not None else scene_idx)
    assert scene_idx < cable_idx
    assert cable_idx < debris_idx


def test_duplicate_section_ids_get_suffix():
    prompt = """## 线缆检查（一）
内容 A。

## 线缆检查（二）
内容 B。
"""
    hints = {"线缆": "cable_check"}
    sections = parse_markdown_sections(prompt, section_id_hints=hints)
    ids = [s["id"] for s in sections]
    assert "cable_check" in ids
    assert "cable_check_2" in ids


def test_stable_ids_across_multiple_calls():
    version1 = _build_version(DOMAIN_HINTS)
    version2 = _build_version(DOMAIN_HINTS)
    ids1 = [s.id for s in version1.prompt_ir.sections]
    ids2 = [s.id for s in version2.prompt_ir.sections]
    assert ids1 == ids2


# ──────────────── bullet / list metadata ─────────────────


def test_bullet_lines_preserved_in_section_content():
    version = _build_version(DOMAIN_HINTS)
    cable = version.prompt_ir.section_by_id("cable_check")
    assert "- " in cable.content or "* " in cable.content


def test_extract_bullet_metadata_counts_items():
    text = """不合格判定（FAIL）：
- 线缆极其凌乱
- 存在大面积交叉

排除范围（不视为 FAIL）：
- 正常弯曲
- 飞线不视为严重凌乱
"""
    meta = extract_bullet_metadata(text)
    assert meta["bullet_count"] >= 4
    assert "fail_condition" in meta["rule_groups"]
    assert "exclusion" in meta["rule_groups"]


def test_extract_bullet_metadata_empty_body():
    meta = extract_bullet_metadata("")
    assert meta["bullet_count"] == 0
    assert meta["rule_groups"] == []
    assert meta["rules"] == []


def test_section_metrics_include_bullet_metadata():
    version = _build_version(DOMAIN_HINTS)
    cable = version.prompt_ir.get_section("cable_check")
    metrics = cable.metrics or {}
    assert metrics.get("source") == "markdown_heading"
    assert metrics.get("bullet_count", 0) > 0
    assert "fail_condition" in metrics.get("rule_groups", [])
    assert "exclusion" in metrics.get("rule_groups", [])


# ──────────────── normalize_section_id helper ─────────────────


def test_normalize_section_id_domain_hints_first():
    used = set()
    assert normalize_section_id(
        "第一步：检查场景适用性",
        used_ids=used,
        section_id_hints=DOMAIN_HINTS,
    ) == "scene_check"


def test_normalize_section_id_generic_hints_second():
    used = set()
    assert normalize_section_id("角色与任务范围", used_ids=used) == "role_definition"


def test_normalize_section_id_english_slug_third():
    used = set()
    assert normalize_section_id("Output Schema", used_ids=used) == "output_schema"


def test_normalize_section_id_stable_fallback_fourth():
    used = set()
    sid = normalize_section_id("一些中文标题", used_ids=used)
    assert sid.startswith("section_")


def test_normalize_section_id_duplicate_suffix():
    used = {"cable_check"}
    sid = normalize_section_id(
        "线缆检查（二）",
        used_ids=used,
        section_id_hints=DOMAIN_HINTS,
    )
    assert sid == "cable_check_2"


# ──────────────── no framework hardcoded business ids ─────────────────


def test_framework_generic_hints_do_not_include_business_ids():
    forbidden = {
        "scene_check", "cable_check", "debris_check",
        "invoice_check", "signature_check", "stamp_check",
    }
    targets = set(GENERIC_SECTION_ID_HINTS.values())
    assert targets.isdisjoint(forbidden), (
        f"generic hints leaked business ids: {targets & forbidden}"
    )


# ──────────────── integration: rendered text + health ─────────────────


def test_industrial_prompt_renders_without_health_errors():
    version = _build_version(DOMAIN_HINTS)
    rendered = version.prompt_ir.rendered or ""
    assert "机柜内部" in rendered
    assert "严重凌乱" in rendered
    report = check_prompt_health(version.prompt_ir)
    assert report.ok, f"health issues: {report.issues}"


def test_default_extraction_prompt_still_works():
    import pathlib
    text = pathlib.Path("prompts/raw/extraction.txt").read_text(encoding="utf-8")
    version = initialize_prompt_version(text, PromptType.EXTRACTION, _contract())
    ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in ids
    assert "role_definition" in ids or any(i.startswith("section_") for i in ids)
    report = check_prompt_health(version.prompt_ir)
    assert report.ok


def test_default_analysis_prompt_still_works():
    import pathlib
    text = pathlib.Path("prompts/raw/analysis.txt").read_text(encoding="utf-8")
    contract = OutputSchemaContract(
        id="test-analysis",
        prompt_type=PromptType.ANALYSIS,
        version=1,
        schema={"type": "object"},
        primary_answer_fields=["judgement"],
    )
    version = initialize_prompt_version(text, PromptType.ANALYSIS, contract)
    ids = [s.id for s in version.prompt_ir.sections]
    assert "analysis_output_schema" in ids
    report = check_prompt_health(version.prompt_ir)
    assert report.ok


def test_legacy_unmapped_preserved_in_markdown_mode():
    version = _build_version(DOMAIN_HINTS)
    ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in ids
    legacy = version.prompt_ir.get_section("legacy_unmapped")
    assert "机柜内部" in legacy.content


def test_output_schema_section_is_frozen_in_markdown_mode():
    version = _build_version(DOMAIN_HINTS)
    schema_section = version.prompt_ir.get_section("output_schema")
    assert schema_section is not None
    assert schema_section.mutability == "frozen"


def test_numbered_list_items_are_counted():
    text = """不合格判定（FAIL）：
1. 线缆极其凌乱
2. 存在大面积交叉
3. 工具类物品散落

排除范围（不视为 FAIL）：
1. 正常弯曲
2. 飞线不视为严重凌乱
"""
    meta = extract_bullet_metadata(text)
    assert meta["numbered_list_count"] >= 4
    assert meta["total_list_items"] >= 4
    assert "fail_condition" in meta["rule_groups"]
    assert "exclusion" in meta["rule_groups"]


def test_edge_case_rule_group_detected():
    text = """边界情况处理：
- 图片模糊：只输出能确认的证据
- 飞线不视为严重凌乱
"""
    meta = extract_bullet_metadata(text)
    assert "edge_case" in meta["rule_groups"]


def test_prohibited_behavior_rule_group_detected():
    text = """禁止行为：
- 不要猜测不可见内容
- 不要修改输出 schema
"""
    meta = extract_bullet_metadata(text)
    assert "prohibited_behavior" in meta["rule_groups"]


def test_fenced_code_and_json_detected():
    text = """示例：
```json
{"result": "PASS"}
```
"""
    meta = extract_bullet_metadata(text)
    assert meta["has_fenced_code"] is True


def test_parse_markdown_sections_respects_heading_levels():
    prompt = """## 顶层章节
顶层内容。

### 子章节一
子内容 A。

### 子章节二
子内容 B。
"""
    sections = parse_markdown_sections(prompt)
    assert len(sections) >= 2
    levels = [s["level"] for s in sections]
    assert 2 in levels
    assert 3 in levels


def test_chinese_punctuation_in_title_still_works():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT, section_id_hints=DOMAIN_HINTS)
    ids = [s["id"] for s in sections]
    assert "scene_check" in ids
    assert "cable_check" in ids


def test_duplicate_suffix_stable_order():
    prompt = """## 线缆检查（一）
内容 A。

## 线缆检查（二）
内容 B。

## 线缆检查（三）
内容 C。
"""
    hints = {"线缆": "cable_check"}
    sections = parse_markdown_sections(prompt, section_id_hints=hints)
    ids = [s["id"] for s in sections]
    assert ids == ["cable_check", "cable_check_2", "cable_check_3"]


def test_section_title_preserved_in_content():
    version = _build_version(DOMAIN_HINTS)
    cable = version.prompt_ir.get_section("cable_check")
    assert "线缆" in cable.content


def test_no_invalid_target_section_when_generated_id_exists():
    version = _build_version(DOMAIN_HINTS)
    existing_ids = {s.id for s in version.prompt_ir.sections}
    assert "scene_check" in existing_ids
    assert "cable_check" in existing_ids
    assert "debris_check" in existing_ids


def test_markdown_sections_preserve_order_equals_rendering_order():
    sections = parse_markdown_sections(INDUSTRIAL_PROMPT, section_id_hints=DOMAIN_HINTS)
    version = _build_version(DOMAIN_HINTS)
    parsed_ids = [s["id"] for s in sections]
    rendering_order = version.prompt_ir.rendering_order
    for pid in parsed_ids:
        assert pid in rendering_order
    for a, b in zip(parsed_ids, [r for r in rendering_order if r in parsed_ids]):
        assert a == b


def test_minimal_markdown_with_hints():
    prompt = """## 线缆检查
- 线缆极其凌乱
- 存在交叉
"""
    sections = parse_markdown_sections(prompt, section_id_hints=DOMAIN_HINTS)
    ids = [s["id"] for s in sections]
    assert "cable_check" in ids


def test_minimal_markdown_without_hints_uses_generic_or_fallback():
    prompt = """## 检查步骤
- 线缆是否整齐
- 是否存在杂物
"""
    sections = parse_markdown_sections(prompt)
    ids = [s["id"] for s in sections]
    assert len(ids) >= 1
    # "检查步骤" → generic hint check_steps, otherwise section_001
    assert any(i == "check_steps" or i.startswith("section_") for i in ids)
