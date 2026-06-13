from __future__ import annotations

import json
from pathlib import Path

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


def initialize_prompt_version(
    raw_prompt: str,
    prompt_type: PromptType,
    contract: OutputSchemaContract,
    *,
    fix_numbering: bool = False,
    normalize_spacing: bool = False,
    unique_headings: bool = False,
) -> PromptVersion:
    if fix_numbering:
        raw_prompt = fix_ordered_list_numbering(raw_prompt)
    if normalize_spacing:
        raw_prompt = normalize_markdown_spacing(raw_prompt)
    if unique_headings:
        raw_prompt = unique_heading_titles(raw_prompt)
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
    ir = PromptIR(
        id=f"{prompt_type.value}_prompt_ir_v1",
        prompt_type=prompt_type,
        version=1,
        output_schema_contract_id=contract.id,
        sections=sections,
        rendering_order=section_ids,
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
) -> PromptVersion:
    return initialize_prompt_version(
        Path(path).read_text(encoding="utf-8"),
        prompt_type,
        contract,
        fix_numbering=fix_numbering,
        normalize_spacing=normalize_spacing,
        unique_headings=unique_headings,
    )
