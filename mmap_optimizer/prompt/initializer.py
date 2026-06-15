from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mmap_optimizer.core.enums import PromptType
from .contract import OutputSchemaContract
from .refactor import fix_ordered_list_numbering
from .standardizer import normalize_markdown_spacing, unique_heading_titles
from .ir import PromptIR, PromptSection
from .version import PromptVersion


EXTRACTION_SECTIONS = [
    "role_definition", "task_definition", "input_description", "quality_criteria",
    "visual_evidence_rules", "ambiguity_policy", "reasoning_constraints",
    "format_compliance_policy", "negative_cases", "self_check", "output_schema", "legacy_unmapped",
]
ANALYSIS_SECTIONS = [
    "role_definition", "analysis_task", "ground_truth_alignment", "error_attribution_policy",
    "prompt_section_attribution_policy", "patch_generation_policy", "patch_risk_policy",
    "schema_guard_policy", "uncertainty_policy", "self_check", "analysis_output_schema", "legacy_unmapped",
]


GENERIC_SECTION_ID_HINTS: dict[str, str] = {
    "角色": "role_definition",
    "角色定义": "role_definition",
    "任务": "task_definition",
    "任务范围": "task_definition",
    "输入": "input_description",
    "输入说明": "input_description",
    "质量": "quality_criteria",
    "质量标准": "quality_criteria",
    "判定标准": "quality_criteria",
    "证据": "visual_evidence_rules",
    "视觉证据": "visual_evidence_rules",
    "歧义": "ambiguity_policy",
    "不确定": "ambiguity_policy",
    "推理": "reasoning_constraints",
    "外部知识": "reasoning_constraints",
    "禁止": "prohibited_behavior",
    "禁止行为": "prohibited_behavior",
    "边界": "edge_cases",
    "边界情况": "edge_cases",
    "边界处理": "edge_cases",
    "输出": "output_schema",
    "输出格式": "output_schema",
    "输出字段": "output_schema",
    "schema": "output_schema",
    "示例": "examples",
    "examples": "examples",
    "output": "output_schema",
    "role": "role_definition",
    "task": "task_definition",
    "判定": "decision_logic",
    "判定逻辑": "decision_logic",
    "结果判定": "decision_logic",
    "最终结果": "final_decision",
    "检查步骤": "check_steps",
    "self check": "self_check",
    "self-check": "self_check",
    "selfcheck": "self_check",
}


_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _slugify(title: str) -> str:
    """Convert a title to a stable, readable section_id slug.

    Supports English titles. Chinese titles return an empty string; callers
    should detect that and fall back to stable section_NNN ids.
    """
    text = title.strip()
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters == 0 or ascii_letters / total_letters < 0.8:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("_").lower()
    return cleaned


def normalize_section_id(
    title: str,
    *,
    used_ids: set[str] | None = None,
    section_id_hints: dict[str, str] | None = None,
) -> str:
    """Derive a stable section_id from a heading title.

    Resolution order:
      1. domain-specific section_id_hints (exact keyword in title)
      2. framework generic hints (exact keyword in title)
      3. English slug fallback
      4. stable fallback id (section_NNN)
      5. duplicate suffix (_2, _3, ...)
    """
    if used_ids is None:
        used_ids = set()
    if section_id_hints is None:
        section_id_hints = {}

    base_id = _resolve_base_id(title, section_id_hints)

    if not base_id:
        return _stable_fallback_id(used_ids)

    final_id = base_id
    suffix = 2
    while final_id in used_ids:
        final_id = f"{base_id}_{suffix}"
        suffix += 1
    return final_id


def _resolve_base_id(title: str, section_id_hints: dict[str, str]) -> str:
    clean_title = title.strip()

    # 1) domain-specific hints: exact keyword appears as a substring
    for keyword, target_id in section_id_hints.items():
        if keyword and keyword in clean_title:
            return target_id

    # 2) framework generic hints: exact keyword appears as a substring
    for keyword, target_id in GENERIC_SECTION_ID_HINTS.items():
        if keyword and keyword in clean_title:
            return target_id

    # 3) English slug fallback
    slug = _slugify(clean_title)
    if slug:
        return slug

    # 4) no stable id derived — caller handles fallback
    return ""


def _stable_fallback_id(used_ids: set[str]) -> str:
    index = 1
    while True:
        candidate = f"section_{index:03d}"
        if candidate not in used_ids:
            return candidate
        index += 1


def parse_markdown_sections(
    raw_prompt: str,
    *,
    section_id_hints: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse raw prompt text into ordered section entries using Markdown headings.

    Returns a list of dicts with keys: id, title, level, content, metadata.

    Returns an empty list if no headings are detected or only one section is
    meaningful. The caller decides how to fall back.
    """
    if not raw_prompt or not raw_prompt.strip():
        return []

    text = raw_prompt
    matches = list(_HEADING_PATTERN.finditer(text))
    if not matches:
        return []

    section_id_hints = section_id_hints or {}
    used_ids: set[str] = set()

    sections: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        hashes = m.group(1)
        title = m.group(2).strip()
        level = len(hashes)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() + 1:end] if m.end() + 1 < end else ""
        body = body.rstrip("\n")

        base_id = _resolve_base_id(title, section_id_hints)

        if base_id:
            sid = base_id
            suffix = 2
            while sid in used_ids:
                sid = f"{base_id}_{suffix}"
                suffix += 1
        else:
            sid = _stable_fallback_id(used_ids)

        used_ids.add(sid)
        metadata = extract_bullet_metadata(body)

        sections.append({
            "id": sid,
            "title": title,
            "level": level,
            "content": body,
            "metadata": metadata,
        })

    if len(sections) < 2:
        return []
    return sections


_RULE_GROUP_LABEL_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("fail_condition", ("不合格", "FAIL", "失败条件", "判定为fail", "判定失败", "不满足")),
    ("exclusion", ("排除范围", "不视为", "not fail", "not_fail", "例外", "排除")),
    ("edge_case", ("边界情况", "边界处理", "edge case", "edge_case", "边缘")),
    ("prohibited_behavior", ("禁止行为", "不要", "不得", "禁止", "严禁", "must not", "don't", "do not", "cannot")),
    ("output_field", ("输出字段", "字段", "schema", "field", "fields", "field:")),
    ("example", ("示例", "example", "examples", "for example", "e.g.", "例如", "eg:")),
]


def _detect_rule_group(label: str) -> str | None:
    """Infer a rule group from a local label line appearing before bullets.

    The label must be a short heading-style line. Order matters: exclusion is
    checked before fail_condition so that "排除范围 ... FAIL" picks exclusion.
    """
    if not label:
        return None
    stripped = label.strip().rstrip(":：")
    if not stripped:
        return None
    if len(stripped) > 80:
        return None
    if stripped.lstrip().startswith(("-", "*", "+", "1.", "2.", "3.")):
        return None
    lowered = stripped.lower()
    ordered_groups: list[tuple[str, tuple[str, ...]]] = [
        ("exclusion", ("排除范围", "不视为", "not fail", "not_fail", "例外", "排除")),
        ("fail_condition", ("不合格", "FAIL", "失败条件", "判定为fail", "判定失败", "不满足")),
        ("edge_case", ("边界情况", "边界处理", "edge case", "edge_case", "边缘")),
        ("prohibited_behavior", ("禁止行为", "不要", "不得", "禁止", "严禁", "must not", "don't", "do not", "cannot")),
        ("output_field", ("输出字段", "字段", "schema", "field", "fields", "field:")),
        ("example", ("示例", "example", "examples", "for example", "e.g.", "例如", "eg:")),
    ]
    for group, keywords in ordered_groups:
        for kw in keywords:
            if kw.lower() in lowered:
                return group
    return None


_BULLET_LINE_PATTERN = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")


def extract_bullet_metadata(section_text: str) -> dict[str, Any]:
    """Extract lightweight bullet/list metadata from a section body.

    Returns a dict with keys: bullet_count, numbered_list_count,
    total_list_items, rule_groups, rules, has_fenced_code, has_json_example.
    """
    metadata: dict[str, Any] = {
        "bullet_count": 0,
        "numbered_list_count": 0,
        "total_list_items": 0,
        "rule_groups": [],
        "rules": [],
        "has_fenced_code": False,
        "has_json_example": False,
    }
    if not section_text or not section_text.strip():
        return metadata

    lines = section_text.splitlines()
    current_group: str = "bullet"
    in_fence = False

    if "```" in section_text:
        metadata["has_fenced_code"] = True
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            metadata["has_json_example"] = True
            break
        if stripped.startswith("[") and stripped.endswith("]") and ":" in stripped:
            metadata["has_json_example"] = True
            break

    rule_set: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        bullet_match = _BULLET_LINE_PATTERN.match(line)
        if bullet_match:
            item_text = bullet_match.group(1).strip()
            is_numbered = bool(re.match(r"^\s*\d+[.)]", line))
            if is_numbered:
                metadata["numbered_list_count"] += 1
            else:
                metadata["bullet_count"] += 1
            metadata["total_list_items"] += 1
            metadata["rules"].append({
                "type": current_group,
                "text": item_text,
            })
            if current_group and current_group not in rule_set and current_group != "bullet":
                rule_set.add(current_group)
        else:
            maybe_group = _detect_rule_group(stripped)
            if maybe_group:
                current_group = maybe_group

    metadata["rule_groups"] = sorted(rule_set)
    return metadata


def _fallback_initializer(
    raw_prompt: str,
    prompt_type: PromptType,
    contract: OutputSchemaContract,
) -> tuple[list[PromptSection], list[str]]:
    """Build the legacy layout (all content in legacy_unmapped + schema sections).

    Preserves original behavior for prompts without Markdown structure.
    """
    section_ids = ANALYSIS_SECTIONS if prompt_type == PromptType.ANALYSIS else EXTRACTION_SECTIONS
    output_section_id = contract.target_section_id
    sections: list[PromptSection] = []
    for sid in section_ids:
        if sid == output_section_id:
            content = "必须严格遵守以下外部不可变输出 schema：\n" + json.dumps(contract.schema, ensure_ascii=False, indent=2)
            sections.append(PromptSection(id=sid, type="output_schema", content=content, priority="critical", compressibility="none", mutability="frozen", scope="framework"))
        elif sid == "legacy_unmapped":
            sections.append(PromptSection(id=sid, type="legacy", content=raw_prompt, compressibility="low", mutability="limited"))
        else:
            sections.append(PromptSection(id=sid, type=sid, content="", rendering_enabled=False))
    return sections, list(section_ids)


def initialize_prompt_version(
    raw_prompt: str,
    prompt_type: PromptType,
    contract: OutputSchemaContract,
    *,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
    unique_headings: bool = False,
    section_id_hints: dict[str, str] | None = None,
) -> PromptVersion:
    if fix_numbering:
        raw_prompt = fix_ordered_list_numbering(raw_prompt)
    if normalize_spacing:
        raw_prompt = normalize_markdown_spacing(raw_prompt)
    if unique_headings:
        raw_prompt = unique_heading_titles(raw_prompt)

    section_id_hints = section_id_hints or {}
    output_section_id = contract.target_section_id

    parsed_sections = parse_markdown_sections(raw_prompt, section_id_hints=section_id_hints)

    if parsed_sections:
        ir_sections: list[PromptSection] = []
        rendering_order: list[str] = []
        known_schema_ids = {"output_schema", "analysis_output_schema"}

        for entry in parsed_sections:
            sid = entry["id"]
            title = entry["title"]
            level = entry["level"]
            content = entry["content"]
            metadata = entry["metadata"]

            heading_line = "#" * level + " " + title
            body = f"{heading_line}\n{content}" if content else heading_line

            metrics: dict[str, Any] = {
                "source": "markdown_heading",
                "heading_level": level,
                "title": title,
                "bullet_count": metadata.get("bullet_count", 0),
                "rule_groups": list(metadata.get("rule_groups", [])),
                "rules": list(metadata.get("rules", [])),
                "total_list_items": metadata.get("total_list_items", 0),
                "numbered_list_count": metadata.get("numbered_list_count", 0),
                "has_fenced_code": metadata.get("has_fenced_code", False),
                "has_json_example": metadata.get("has_json_example", False),
            }

            if sid in known_schema_ids:
                schema_text = "必须严格遵守以下外部不可变输出 schema：\n" + json.dumps(contract.schema, ensure_ascii=False, indent=2)
                combined_body = f"{heading_line}\n{content}\n\n{schema_text}" if content else schema_text
                ir_sections.append(PromptSection(
                    id=sid,
                    type="output_schema",
                    content=combined_body,
                    name=title,
                    scope="framework",
                    priority="critical",
                    compressibility="none",
                    mutability="frozen",
                    rendering_enabled=True,
                    metrics=metrics,
                ))
            else:
                ir_sections.append(PromptSection(
                    id=sid,
                    type=sid,
                    content=body,
                    name=title,
                    scope="task",
                    priority="medium",
                    compressibility="medium",
                    mutability="normal",
                    rendering_enabled=True,
                    metrics=metrics,
                ))
            rendering_order.append(sid)

        existing_ids = {s.id for s in ir_sections}
        if output_section_id and output_section_id not in existing_ids:
            content = "必须严格遵守以下外部不可变输出 schema：\n" + json.dumps(contract.schema, ensure_ascii=False, indent=2)
            ir_sections.append(PromptSection(
                id=output_section_id,
                type="output_schema",
                content=content,
                priority="critical",
                compressibility="none",
                mutability="frozen",
                scope="framework",
            ))
            rendering_order.append(output_section_id)

        # Backwards-compat legacy_unmapped with full prompt text (not rendered)
        ir_sections.append(PromptSection(
            id="legacy_unmapped",
            type="legacy",
            content=raw_prompt,
            compressibility="low",
            mutability="limited",
            rendering_enabled=False,
        ))
        rendering_order.append("legacy_unmapped")

        ir = PromptIR(
            id=f"{prompt_type.value}_prompt_ir_v1",
            prompt_type=prompt_type,
            version=1,
            output_schema_contract_id=contract.id,
            sections=ir_sections,
            rendering_order=rendering_order,
        )
    else:
        legacy_sections, legacy_order = _fallback_initializer(raw_prompt, prompt_type, contract)
        ir = PromptIR(
            id=f"{prompt_type.value}_prompt_ir_v1",
            prompt_type=prompt_type,
            version=1,
            output_schema_contract_id=contract.id,
            sections=legacy_sections,
            rendering_order=legacy_order,
        )

    version = PromptVersion(
        id=f"{prompt_type.value}_prompt_v1",
        prompt_type=prompt_type,
        version=1,
        prompt_ir=ir,
        output_schema_contract_id=contract.id,
    )
    version.render()
    return version


def initialize_prompt_from_file(
    path: str | Path,
    prompt_type: PromptType,
    contract: OutputSchemaContract,
    *,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
    unique_headings: bool = False,
    section_id_hints: dict[str, str] | None = None,
) -> PromptVersion:
    return initialize_prompt_version(
        Path(path).read_text(encoding="utf-8"),
        prompt_type,
        contract,
        fix_numbering=fix_numbering,
        normalize_spacing=normalize_spacing,
        unique_headings=unique_headings,
        section_id_hints=section_id_hints,
    )
