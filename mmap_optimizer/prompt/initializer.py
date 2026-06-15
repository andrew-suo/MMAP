"""Prompt IR initializer — structural compiler, not semantic guesser.

Implements:

  raw_prompt
    └─ markdown heading parsing (structural only)
          ├─ ordered section boundaries
          ├─ normalize_section_id (hints → generic → slug → stable fallback)
          └─ build PromptIR

Fallback: when markdown cannot produce ≥2 sections, keep legacy_unmapped so
downstream consumers always have a valid target. The legacy container is also
kept around as a "raw backup" for markdown-parsed IRs.
"""
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


# ──────────────────── preserved for reference / fallback ────────────────────
EXTRACTION_SECTIONS = [
    "role_definition", "task_definition", "input_description", "quality_criteria",
    "visual_evidence_rules", "ambiguity_policy", "reasoning_constraints",
    "format_compliance_policy", "negative_cases", "self_check", "output_schema",
    "legacy_unmapped",
]
ANALYSIS_SECTIONS = [
    "role_definition", "analysis_task", "ground_truth_alignment", "error_attribution_policy",
    "prompt_section_attribution_policy", "patch_generation_policy", "patch_risk_policy",
    "schema_guard_policy", "uncertainty_policy", "self_check", "analysis_output_schema",
    "legacy_unmapped",
]


# ──────────────────── generic (non-industry) hints ─────────────────────────
# These keyword → id mappings reflect prompt *structure*, not vertical domain.
# Adding a new entry is fine — but it MUST be a generic structural category.
# DO NOT add industry / scenario hints here (e.g. cable, invoice, medical).
_GENERIC_SECTION_ID_HINTS: dict[str, str] = {
    "role_definition": "role_definition",
    "role definition": "role_definition",
    "task_definition": "task_definition",
    "task definition": "task_definition",
    "input_description": "input_description",
    "input description": "input_description",
    "quality_criteria": "quality_criteria",
    "quality criteria": "quality_criteria",
    "constraints": "constraints",
    "edge_cases": "edge_cases",
    "edge cases": "edge_cases",
    "output_schema": "output_schema",
    "output schema": "output_schema",
    "analysis_output_schema": "analysis_output_schema",
    "examples": "examples",
}

# Chinese generic structural keywords — also structural, not domain-specific.
# Order matters (longest match wins).  Callers sort keys by length.
_GENERIC_ZH_KEYWORDS: list[tuple[str, str]] = [
    ("角色定义", "role_definition"),
    ("角色与任务", "role_definition"),
    ("角色", "role_definition"),
    ("任务范围", "task_definition"),
    ("任务说明", "task_definition"),
    ("任务", "task_definition"),
    ("输入说明", "input_description"),
    ("输入", "input_description"),
    ("质量标准", "quality_criteria"),
    ("判定标准", "quality_criteria"),
    ("质量", "quality_criteria"),
    ("约束条件", "constraints"),
    ("约束", "constraints"),
    ("边界情况", "edge_cases"),
    ("边界处理", "edge_cases"),
    ("边界", "edge_cases"),
    ("禁止行为", "prohibited_behavior"),
    ("禁止", "prohibited_behavior"),
    ("输出格式", "output_schema"),
    ("输出字段", "output_schema"),
    ("输出", "output_schema"),
    ("示例", "examples"),
]


# ──────────────────── helpers ──────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _slugify(text: str) -> str:
    """ASCII-only snake_cased id.  Non-English / numeric-only → empty string."""
    if not text:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    if not cleaned:
        return ""
    # Require ≥2 alphabetic characters — this rejects titles that are purely
    # numeric (e.g. "3" or "2.1") so the parser falls through to the stable
    # numeric fallback instead of producing a confusing "3" section id.
    alpha = sum(1 for c in cleaned if c.isalpha())
    if alpha < 2:
        return ""
    return cleaned


def _resolve_from_hints(title: str, hints: dict[str, str]) -> str | None:
    """Check title against hint map.  Longest match wins."""
    if not hints or not title:
        return None
    lowered = title.lower()
    best_key = ""
    best_value: str | None = None
    for keyword, target_id in hints.items():
        if not keyword:
            continue
        if keyword.lower() not in lowered:
            continue
        if len(keyword) > len(best_key):
            best_key = keyword
            best_value = target_id
    return best_value


def _stable_fallback_id(used_ids: set[str]) -> str:
    n = len(used_ids) + 1
    while f"section_{n:03d}" in used_ids:
        n += 1
    return f"section_{n:03d}"


def normalize_section_id(
    title: str,
    *,
    used_ids: set[str] | None = None,
    section_id_hints: dict[str, str] | None = None,
) -> str:
    """Structurally derive a stable section id.

    Resolution priority (from strongest signal to weakest):

      1. scenario/domain hints (explicit override — external input)
      2. framework generic structural hints (English + Chinese)
      3. English slug fallback
      4. stable numeric fallback: section_NNN
      5. duplicate suffix: _2 / _3 / ...
    """
    if used_ids is None:
        used_ids = set()
    section_id_hints = section_id_hints or {}

    candidate: str | None = None

    # (1) scenario hints
    if section_id_hints:
        candidate = _resolve_from_hints(title, section_id_hints)
    # (2) generic structural hints — English keywords
    if not candidate:
        candidate = _resolve_from_hints(title, _GENERIC_SECTION_ID_HINTS)
    # (2b) generic structural hints — Chinese keywords (longest match)
    if not candidate:
        lowered = title
        best_key = ""
        best_value: str | None = None
        for keyword, target_id in _GENERIC_ZH_KEYWORDS:
            if keyword in lowered and len(keyword) > len(best_key):
                best_key = keyword
                best_value = target_id
        if best_value and best_key:
            candidate = best_value
    # (3) English slug fallback
    if not candidate:
        slug = _slugify(title)
        if slug:
            candidate = slug
    # (4) stable numeric fallback
    if not candidate:
        candidate = _stable_fallback_id(used_ids)

    # (5) duplicate suffix handling
    if candidate in used_ids:
        suffix = 2
        while f"{candidate}_{suffix}" in used_ids:
            suffix += 1
        candidate = f"{candidate}_{suffix}"
    return candidate


# ──────────────────── markdown → sections ───────────────────────────────────

def parse_markdown_sections(
    raw_prompt: str,
    *,
    section_id_hints: dict[str, str] | None = None,
    group_subheadings: bool = True,
) -> list[dict[str, Any]]:
    """Split raw markdown text into ordered section entries.

    Purely structural: headings are the boundaries; everything below a heading
    (until the next heading of equal-or-higher level) becomes the body.

    When ``group_subheadings=True`` (default) and no ``section_id_hints`` are
    provided, sub-headings (### and below) are folded into their nearest
    parent heading (##).  Only top-level headings become sections; their
    content includes the full text of all sub-headings beneath them.

    When ``section_id_hints`` are provided, flat mode is automatically used
    so that each heading (including sub-headings) becomes its own section.
    This allows hints to target specific sub-headings precisely.

    Returns a list of dicts with keys: id, title, level, content, subsections.
    Returns [] if prompt is empty, has no headings, or produced <2 sections.
    """
    if not raw_prompt:
        return []

    matches = list(_HEADING_RE.finditer(raw_prompt))
    if not matches:
        return []

    used_ids: set[str] = set()
    section_id_hints = section_id_hints or {}

    # When hints are provided, use flat mode so each heading can be targeted.
    # Without hints, grouped mode keeps things concise.
    effective_group = group_subheadings and not section_id_hints

    if not effective_group:
        # Flat mode: every heading becomes a section (original behavior).
        sections: list[dict[str, Any]] = []
        for idx, m in enumerate(matches):
            hashes = m.group(1)
            title = m.group(2).strip()
            level = len(hashes)
            body_start = m.end() + 1 if m.end() + 1 <= len(raw_prompt) else m.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_prompt)
            body = raw_prompt[body_start:body_end].rstrip("\n")

            sid = normalize_section_id(
                title,
                used_ids=used_ids,
                section_id_hints=section_id_hints,
            )
            used_ids.add(sid)

            sections.append({
                "id": sid,
                "title": title,
                "level": level,
                "content": f"{'#' * level} {title}\n{body}" if body else f"{'#' * level} {title}",
                "subsections": [],
            })

        if len(sections) < 2:
            return []
        return sections

    # ── grouped mode ──
    # Determine the top-level heading level (minimum level across all headings).
    min_level = min(len(m.group(1)) for m in matches)

    # First pass: collect all heading spans.
    heading_spans: list[tuple[int, str, int, int, int]] = []  # (level, title, match_start, body_start, body_end)
    for idx, m in enumerate(matches):
        hashes = m.group(1)
        title = m.group(2).strip()
        level = len(hashes)
        body_start = m.end() + 1 if m.end() + 1 <= len(raw_prompt) else m.end()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_prompt)
        heading_spans.append((level, title, m.start(), body_start, body_end))

    # Second pass: group sub-headings under their nearest parent at min_level.
    # A parent is a heading at min_level.  All subsequent headings at > min_level
    # belong to that parent until the next heading at min_level.
    #
    # When a sub-heading's title matches a section_id_hint, that hint should
    # "bubble up" to influence the parent section's id — because in grouped
    # mode the sub-heading is not a standalone section.
    grouped: list[dict[str, Any]] = []
    current_parent: dict[str, Any] | None = None

    for level, title, match_start, body_start, body_end in heading_spans:
        if level == min_level:
            # Start a new parent section.
            if current_parent is not None:
                grouped.append(current_parent)
            body = raw_prompt[body_start:body_end].rstrip("\n")
            sid = normalize_section_id(
                title,
                used_ids=used_ids,
                section_id_hints=section_id_hints,
            )
            used_ids.add(sid)
            current_parent = {
                "id": sid,
                "title": title,
                "level": level,
                "content": f"{'#' * level} {title}\n{body}" if body else f"{'#' * level} {title}",
                "subsections": [],
            }
        else:
            # Sub-heading: fold into current parent.
            if current_parent is not None:
                sub_body = raw_prompt[body_start:body_end].rstrip("\n")
                sub_sid = normalize_section_id(
                    title,
                    used_ids=used_ids,
                    section_id_hints=section_id_hints,
                )
                used_ids.add(sub_sid)
                current_parent["subsections"].append({
                    "id": sub_sid,
                    "title": title,
                    "level": level,
                    "content": f"{'#' * level} {title}\n{sub_body}" if sub_body else f"{'#' * level} {title}",
                })
                # Extend parent content to include sub-heading text.
                sub_text = raw_prompt[match_start:body_end].rstrip("\n")
                current_parent["content"] += "\n" + sub_text

    if current_parent is not None:
        grouped.append(current_parent)

    if len(grouped) < 2:
        return []
    return grouped


# ──────────────────── IR builder ────────────────────────────────────────────

def _legacy_fallback_ir(
    raw_prompt: str,
    prompt_type: PromptType,
    contract: OutputSchemaContract,
) -> PromptIR:
    """Produce the legacy shape: schema section + empty placeholder sections
    + legacy_unmapped containing the raw prompt.  Used when no markdown was
    detected, ensuring backwards compatibility."""
    section_ids = ANALYSIS_SECTIONS if prompt_type == PromptType.ANALYSIS else EXTRACTION_SECTIONS
    output_section_id = contract.target_section_id
    sections: list[PromptSection] = []
    for sid in section_ids:
        if sid == output_section_id:
            content = "必须严格遵守以下外部不可变输出 schema：\n" + json.dumps(contract.schema, ensure_ascii=False, indent=2)
            sections.append(PromptSection(
                id=sid, type="output_schema", content=content,
                priority="critical", compressibility="none", mutability="frozen", scope="framework",
            ))
        elif sid == "legacy_unmapped":
            sections.append(PromptSection(
                id=sid, type="legacy", content=raw_prompt,
                compressibility="low", mutability="limited",
            ))
        else:
            sections.append(PromptSection(
                id=sid, type=sid, content="", rendering_enabled=False,
            ))
    return PromptIR(
        id=f"{prompt_type.value}_prompt_ir_v1",
        prompt_type=prompt_type,
        version=1,
        output_schema_contract_id=contract.id,
        sections=sections,
        rendering_order=list(section_ids),
    )


def _build_ir_from_parsed(
    raw_prompt: str,
    parsed_sections: list[dict[str, Any]],
    prompt_type: PromptType,
    contract: OutputSchemaContract,
) -> PromptIR:
    """Turn parsed section dicts into a PromptIR.

    - Exactly one frozen schema section is produced.  If the parser generated
      a section whose id matches ``{prompt_type}_output_schema`` that section
      becomes the frozen schema section.  Otherwise the first section whose
      id is ``output_schema`` / ``analysis_output_schema`` is chosen; failing
      that, a fresh frozen schema section is appended.
    - A ``legacy_unmapped`` raw backup section is always present (not rendered
      by default) for safety.
    """
    sections: list[PromptSection] = []
    rendering_order: list[str] = []

    target_schema_id = contract.target_section_id or (
        "analysis_output_schema" if prompt_type == PromptType.ANALYSIS else "output_schema"
    )
    alternative_schema_ids = {"output_schema", "analysis_output_schema"}
    schema_body = "必须严格遵守以下外部不可变输出 schema：\n" + json.dumps(contract.schema, ensure_ascii=False, indent=2)
    schema_emitted_in = None  # the actual section id that got the frozen schema treatment

    # First pass: if there is a section whose id matches target_schema_id,
    # that takes precedence and becomes the frozen schema section.  Otherwise
    # any section whose id is output_schema/analysis_output_schema is frozen
    # and renamed to target_schema_id, so the contract's expected target is
    # always present.
    prefer_target = any(s["id"] == target_schema_id for s in parsed_sections)
    use_alt = not prefer_target and any(s["id"] in alternative_schema_ids for s in parsed_sections)

    for entry in parsed_sections:
        sid = entry["id"]
        title = entry["title"]
        level = entry["level"]
        content = entry["content"]

        metrics: dict[str, Any] = {
            "source": "markdown_heading",
            "heading_level": level,
            "title": title,
        }

        is_schema = False
        if prefer_target and sid == target_schema_id and schema_emitted_in is None:
            is_schema = True
        elif use_alt and sid in alternative_schema_ids and schema_emitted_in is None:
            is_schema = True

        if is_schema:
            merged = f"{content}\n\n{schema_body}" if content.strip() else schema_body
            sections.append(PromptSection(
                id=target_schema_id, type="output_schema", content=merged,
                name=title, scope="framework", priority="critical",
                compressibility="none", mutability="frozen",
                rendering_enabled=True, metrics=metrics,
            ))
            schema_emitted_in = target_schema_id
        else:
            sections.append(PromptSection(
                id=sid, type=sid, content=content,
                name=title, scope="task", priority="medium",
                compressibility="medium", mutability="normal",
                rendering_enabled=True, metrics=metrics,
            ))
        rendering_order.append(sections[-1].id)

    if schema_emitted_in is None and target_schema_id:
        sections.append(PromptSection(
            id=target_schema_id, type="output_schema", content=schema_body,
            scope="framework", priority="critical",
            compressibility="none", mutability="frozen",
        ))
        rendering_order.append(target_schema_id)

    sections.append(PromptSection(
        id="legacy_unmapped", type="legacy", content=raw_prompt,
        compressibility="low", mutability="limited", rendering_enabled=False,
    ))
    rendering_order.append("legacy_unmapped")

    return PromptIR(
        id=f"{prompt_type.value}_prompt_ir_v1",
        prompt_type=prompt_type,
        version=1,
        output_schema_contract_id=contract.id,
        sections=sections,
        rendering_order=rendering_order,
    )


# ──────────────────── public entry point ────────────────────────────────────

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
    """Create a PromptVersion from raw prompt text.

    Structural-only compiler:

      1. optional preprocessing (numbering / spacing / heading uniqueness)
      2. markdown heading parsing → ordered sections
      3. if ≥2 sections → build IR from parsed sections (plus frozen schema
         and legacy_unmapped raw backup)
      4. otherwise → legacy fallback IR (all content in legacy_unmapped)
    """
    if fix_numbering:
        raw_prompt = fix_ordered_list_numbering(raw_prompt)
    if normalize_spacing:
        raw_prompt = normalize_markdown_spacing(raw_prompt)
    if unique_headings:
        raw_prompt = unique_heading_titles(raw_prompt)

    parsed = parse_markdown_sections(raw_prompt, section_id_hints=section_id_hints)

    if parsed:
        ir = _build_ir_from_parsed(raw_prompt, parsed, prompt_type, contract)
    else:
        ir = _legacy_fallback_ir(raw_prompt, prompt_type, contract)

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
