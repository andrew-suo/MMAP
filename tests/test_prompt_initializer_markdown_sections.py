"""Tests for the structural prompt initializer.

Covers the six mandated categories:

  1. Markdown split correctness   (multi-heading → multi-section)
  2. Fallback correctness         (no heading → legacy_unmapped)
  3. Hint override correctness    (hints → override section_id)
  4. No-hint stability            (no scenario hints → no business id leakage)
  5. Repeatable initialisation    (same prompt twice → identical ids)
  6. No business leakage          (framework cannot invent cable/debris/etc)
"""
from __future__ import annotations

from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import (
    initialize_prompt_version,
    normalize_section_id,
    parse_markdown_sections,
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


MULTI_HEADING_MARKDOWN = """## 1. 角色与任务范围

你是一名助理工程师。

## 2. 工作流程

按照步骤执行。

## 3. 输出格式

必须输出 JSON。
"""


SCENARIO_PROMPT = """## 1. 角色与任务范围

你是电信机房工业质检工程师，负责检查机柜内布线质量。

## 2. 结果判定总逻辑

### 2.1 不合格
任意步骤发现明确不合格情况即判定 FAIL。
- 线缆极其凌乱，呈严重网状散乱
- 存在大面积交叉

### 2.2 可接受
未满足 FAIL 条件时判定 PASS。

## 3. 检查步骤

### 3.1 第一步：检查场景适用性
判断图片是否属于机柜内部布线场景。
- 若完全看不到机柜内部、设备、线缆，则 result = UNCERTAIN

### 3.2 第二步：检查线缆是否严重凌乱
不合格判定：
- 线缆极其凌乱

排除范围：
- 正常弯曲不算

### 3.3 第三步：检查是否存在杂物
不合格判定：
- 工具类物品直接散落在机柜内部

### 3.4 第四步：给出最终结果
- 有 FAIL 条件 → NG
- 无 FAIL 且不是 NOT_INVOLVED → OK

## 4. 边界情况处理
- 图片模糊：只输出能确认的证据

## 5. 禁止行为
- 不要猜测不可见内容

## 6. 输出格式
必须只输出合法 JSON。
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
}

BUSINESS_IDS = {"scene_check", "cable_check", "debris_check",
                "invoice_check", "signature_check", "stamp_check", "medical_check"}


# ─────────── helpers ───────────

def _section_ids(prompt: str, *, hints=None):
    sections = parse_markdown_sections(prompt, section_id_hints=hints)
    return [s["id"] for s in sections]


# ─────────── 1. Markdown split correctness ───────────

def test_markdown_multi_heading_produces_multiple_sections():
    sections = parse_markdown_sections(MULTI_HEADING_MARKDOWN)
    assert len(sections) >= 2


def test_markdown_section_content_preserves_heading_and_body():
    sections = parse_markdown_sections(MULTI_HEADING_MARKDOWN)
    ids = {s["id"] for s in sections}
    assert "role_definition" in ids
    assert "output_schema" in ids
    role = next(s for s in sections if s["id"] == "role_definition")
    assert "角色与任务范围" in role["content"]
    assert "助理工程师" in role["content"]


def test_markdown_section_order_matches_text_order():
    sections = parse_markdown_sections(MULTI_HEADING_MARKDOWN)
    titles = [s["title"] for s in sections]
    assert titles == ["1. 角色与任务范围", "2. 工作流程", "3. 输出格式"]


def test_markdown_headings_level_preserved():
    sections = parse_markdown_sections(MULTI_HEADING_MARKDOWN)
    for s in sections:
        assert s["level"] == 2


def test_markdown_includes_subheadings():
    sections = parse_markdown_sections(SCENARIO_PROMPT)
    # subheading "2.1 不合格" / "2.2 可接受" must appear.
    titles = "".join(s["title"] for s in sections)
    assert "不合格" in titles
    assert "可接受" in titles


def test_initializer_renders_multiple_sections_for_markdown():
    version = initialize_prompt_version(MULTI_HEADING_MARKDOWN, PromptType.EXTRACTION, _contract())
    section_ids = [s.id for s in version.prompt_ir.sections if s.rendering_enabled]
    assert len(section_ids) >= 3


# ─────────── 2. Fallback correctness ───────────

def test_plain_text_no_headings_returns_empty_sections():
    text = "你是一个助手。回答用户问题。"
    sections = parse_markdown_sections(text)
    assert sections == []


def test_empty_prompt_returns_empty_sections():
    assert parse_markdown_sections("") == []
    assert parse_markdown_sections(None) == []  # type: ignore[arg-type]


def test_single_heading_prompt_produces_structured_ir():
    # A single heading now produces a structured IR (not legacy fallback).
    text = "# 唯一标题\n内容放在这里。"
    sections = parse_markdown_sections(text)
    assert len(sections) == 1
    assert sections[0]["title"] == "唯一标题"


def test_plain_text_initializer_uses_legacy_unmapped():
    text = "你是一个助手。回答用户问题。"
    version = initialize_prompt_version(text, PromptType.EXTRACTION, _contract())
    ids = [s.id for s in version.prompt_ir.sections]
    assert "legacy_unmapped" in ids
    legacy = version.prompt_ir.section_by_id("legacy_unmapped")
    assert legacy is not None
    assert "你是一个助手" in legacy.content


# ─────────── 3. Hint override correctness ───────────

def test_scenario_hints_replace_default_ids():
    ids = _section_ids(SCENARIO_PROMPT, hints=DOMAIN_HINTS)
    assert "scene_check" in ids
    assert "cable_check" in ids
    assert "debris_check" in ids


def test_scenario_hints_are_sorted_longest_match_first():
    # "最终结果" is inside "第四步：给出最终结果" → should produce final_decision.
    ids = _section_ids(SCENARIO_PROMPT, hints=DOMAIN_HINTS)
    assert "final_decision" in ids


def test_scenario_hints_work_through_initializer_public_api():
    version = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    ids = {s.id for s in version.prompt_ir.sections}
    assert "scene_check" in ids
    assert "cable_check" in ids
    assert "debris_check" in ids
    assert "final_decision" in ids


def test_section_content_preserved_under_hints():
    version = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    cable = version.prompt_ir.section_by_id("cable_check")
    debris = version.prompt_ir.section_by_id("debris_check")
    scene = version.prompt_ir.section_by_id("scene_check")
    assert cable is not None and "线缆" in cable.content
    assert debris is not None and "杂物" in debris.content
    assert scene is not None and "场景适用" in scene.content


def test_duplicate_hint_ids_get_suffix():
    prompt = """## 线缆检查（一）
A

## 线缆检查（二）
B
"""
    ids = _section_ids(prompt, hints={"线缆": "cable_check"})
    assert "cable_check" in ids
    assert "cable_check_2" in ids


# ─────────── 4. Non-hint case stability ───────────

def test_no_hints_does_not_inject_business_ids_into_parser():
    # Without domain hints the framework must not invent cable/debris/scene
    # ids out of thin air.  parse_markdown_sections must behave structurally.
    ids = _section_ids(SCENARIO_PROMPT)
    assert "cable_check" not in ids
    assert "debris_check" not in ids
    assert "scene_check" not in ids


def test_no_hints_still_produces_multiple_sections():
    ids = _section_ids(SCENARIO_PROMPT)
    assert len(ids) >= 4


def test_no_hints_section_ids_are_purely_structural():
    ids = _section_ids(SCENARIO_PROMPT)
    leaked = [i for i in ids if i in BUSINESS_IDS]
    assert leaked == [], f"framework leaked business section ids: {leaked}"


def test_normalize_section_id_without_hints_does_not_produce_business_id():
    for title in ("线缆凌乱", "明显杂物", "检查场景适用性", "发票核验"):
        sid = normalize_section_id(title)
        assert sid not in BUSINESS_IDS, f"title={title!r} produced {sid!r}"


# ─────────── 5. Stability / repeatability ───────────

def test_same_prompt_produces_same_ids_twice():
    version_a = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    version_b = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    ids_a = [s.id for s in version_a.prompt_ir.sections]
    ids_b = [s.id for s in version_b.prompt_ir.sections]
    assert ids_a == ids_b


def test_rendering_order_matches_sections_order():
    version = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    ir = version.prompt_ir
    # rendering_order must be a valid ordering of section ids.
    for sid in ir.rendering_order:
        assert ir.section_by_id(sid) is not None


def test_normalize_section_id_repeatable():
    results = [normalize_section_id("线缆检查", section_id_hints=DOMAIN_HINTS) for _ in range(5)]
    assert results == [results[0]] * 5


# ─────────── 6. No business leakage ───────────

def test_framework_cannot_invent_business_section_ids():
    # Pure Chinese structural content — framework should fall back to
    # section_NNN or generic structural ids, NEVER to business ids.
    prompt = """## 业务内容一
检查线缆是否凌乱。

## 业务内容二
检查是否存在杂物。

## 业务内容三
检查场景是否适用。
"""
    ids = _section_ids(prompt)
    for bid in BUSINESS_IDS:
        assert bid not in ids, f"framework leaked {bid}"


def test_normalize_section_id_with_no_hints_never_produces_business_id():
    # Feed many titles that do not carry structural keywords; framework
    # must not reach into a business id dictionary.
    titles = [
        "线缆检查", "杂物扫描", "场景判定", "发票识别",
        "签名核验", "印章检测", "医疗影像",
    ]
    for t in titles:
        assert normalize_section_id(t) not in BUSINESS_IDS


# ─────────── additional: output_schema frozen + legacy backup ───────────

def test_output_schema_is_frozen_in_markdown_mode():
    version = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    schema = version.prompt_ir.section_by_id("output_schema")
    assert schema is not None
    assert schema.mutability == "frozen"


def test_legacy_backup_still_present_in_markdown_mode():
    version = initialize_prompt_version(
        SCENARIO_PROMPT, PromptType.EXTRACTION, _contract(),
        section_id_hints=DOMAIN_HINTS,
    )
    legacy = version.prompt_ir.section_by_id("legacy_unmapped")
    assert legacy is not None
    assert "机柜内部" in legacy.content


# ─────────── additional: English slug fallback ───────────

def test_english_headings_snake_case():
    prompt = """## Role Definition
A

## Quality Criteria
B

## Output Schema
C
"""
    ids = _section_ids(prompt)
    assert "role_definition" in ids
    assert "quality_criteria" in ids
    assert "output_schema" in ids


# ─────────── additional: analysis prompt type ───────────

def test_analysis_prompt_splits_markdown():
    analysis_prompt = """## 1. 角色
你是评审者。

## 2. 任务
评审 patch。

## 3. 输出格式
JSON。
"""
    version = initialize_prompt_version(
        analysis_prompt, PromptType.ANALYSIS, _contract(PromptType.ANALYSIS),
    )
    ids = [s.id for s in version.prompt_ir.sections]
    assert "analysis_output_schema" in ids
    assert "legacy_unmapped" in ids


# ─────────── integration: ScenarioConfig → section_id_hints pipeline ───────────

def test_scenario_config_reads_section_id_hints_from_manifest(tmp_path):
    """ScenarioConfig.section_id_hints is populated from scenario.yaml manifest."""
    from mmap_optimizer.core.scenario import ScenarioConfig, load_scenario

    scenario_dir = tmp_path / "test_scenario"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.yaml").write_text(
        "name: Test\noptimizer_config: optimizer.yaml\ndata_dir: data\nprompts_dir: prompts\nschemas_dir: schemas\n"
        "section_id_hints:\n  cable_check: jian_cha_bu_zhou\n  debris_check: jian_cha_bu_zhou\n",
        encoding="utf-8",
    )
    (scenario_dir / "optimizer.yaml").write_text("batch_size: 5\n", encoding="utf-8")
    (scenario_dir / "data").mkdir()
    (scenario_dir / "prompts").mkdir()
    (scenario_dir / "schemas").mkdir()

    config = load_scenario(scenario_dir)
    assert config.section_id_hints == {"cable_check": "jian_cha_bu_zhou", "debris_check": "jian_cha_bu_zhou"}


def test_scenario_config_empty_hints_when_not_in_manifest(tmp_path):
    """When scenario.yaml has no section_id_hints, the field defaults to empty dict."""
    from mmap_optimizer.core.scenario import load_scenario

    scenario_dir = tmp_path / "no_hints"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.yaml").write_text(
        "name: No Hints\noptimizer_config: optimizer.yaml\ndata_dir: data\nprompts_dir: prompts\nschemas_dir: schemas\n",
        encoding="utf-8",
    )
    (scenario_dir / "optimizer.yaml").write_text("batch_size: 5\n", encoding="utf-8")
    (scenario_dir / "data").mkdir()
    (scenario_dir / "prompts").mkdir()
    (scenario_dir / "schemas").mkdir()

    config = load_scenario(scenario_dir)
    assert config.section_id_hints == {}


def test_scenario_config_ignores_non_dict_section_id_hints(tmp_path):
    """If section_id_hints is not a dict, it falls back to empty dict."""
    from mmap_optimizer.core.scenario import load_scenario

    scenario_dir = tmp_path / "bad_hints"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.yaml").write_text(
        "name: Bad Hints\noptimizer_config: optimizer.yaml\ndata_dir: data\nprompts_dir: prompts\nschemas_dir: schemas\n"
        "section_id_hints: not_a_dict\n",
        encoding="utf-8",
    )
    (scenario_dir / "optimizer.yaml").write_text("batch_size: 5\n", encoding="utf-8")
    (scenario_dir / "data").mkdir()
    (scenario_dir / "prompts").mkdir()
    (scenario_dir / "schemas").mkdir()

    config = load_scenario(scenario_dir)
    assert config.section_id_hints == {}


def test_section_id_hints_flow_from_scenario_to_prompt_version(tmp_path):
    """End-to-end: hints from scenario.yaml produce correct section IDs in PromptVersion."""
    hints = {
        "线缆": "cable_check",
        "杂物": "debris_check",
        "场景": "scene_check",
    }
    prompt = """## 角色定义
你是检查员。

## 线缆检查步骤
检查线缆是否扭曲。

## 场景检查
检查场景完整性。

## 杂物检测
检测是否有杂物。

## 输出格式
JSON。
"""
    version = initialize_prompt_version(
        prompt, PromptType.EXTRACTION, _contract(),
        section_id_hints=hints,
    )
    ids = [s.id for s in version.prompt_ir.sections]
    assert "cable_check" in ids, f"Expected cable_check in {ids}"
    assert "scene_check" in ids, f"Expected scene_check in {ids}"
    assert "debris_check" in ids, f"Expected debris_check in {ids}"
