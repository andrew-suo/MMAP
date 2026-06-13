from __future__ import annotations

import re
from dataclasses import dataclass, field

from mmap_optimizer.prompt.ir import PromptIR


@dataclass
class PromptHealthIssue:
    code: str
    severity: str
    message: str
    section_id: str | None = None


@dataclass
class PromptHealthReport:
    prompt_ir_id: str
    issues: list[PromptHealthIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def check_prompt_health(prompt_ir: PromptIR) -> PromptHealthReport:
    report = PromptHealthReport(prompt_ir_id=prompt_ir.id)
    section_ids = [section.id for section in prompt_ir.sections]
    if len(section_ids) != len(set(section_ids)):
        report.issues.append(PromptHealthIssue("H1_DUPLICATE_SECTION_ID", "error", "Duplicate section ids detected."))
    for section_id in prompt_ir.rendering_order:
        if section_id not in set(section_ids):
            report.issues.append(PromptHealthIssue("H2_RENDER_ORDER_MISSING_SECTION", "error", "Rendering order references a missing section.", section_id))
    seen_headings: set[str] = set()
    for section in prompt_ir.sections:
        if section.rendering_enabled and not section.content.strip():
            report.issues.append(PromptHealthIssue("H3_EMPTY_RENDERED_SECTION", "warning", "Rendered section is empty.", section.id))
        for heading in _headings(section.content):
            if heading in seen_headings:
                report.issues.append(PromptHealthIssue("H4_DUPLICATE_HEADING", "warning", f"Duplicate heading: {heading}", section.id))
            seen_headings.add(heading)
        if section.mutability == "frozen" and section.compressibility != "none":
            report.issues.append(PromptHealthIssue("H5_FROZEN_COMPRESSIBLE", "error", "Frozen section must not be compressible.", section.id))
        if section.id in {"output_schema", "analysis_output_schema"} and section.mutability != "frozen":
            report.issues.append(PromptHealthIssue("H6_SCHEMA_NOT_FROZEN", "error", "Schema section must be frozen.", section.id))
        if section.id == "legacy_unmapped" and len(section.content.splitlines()) > 200:
            report.issues.append(PromptHealthIssue("H7_LEGACY_UNMAPPED_LARGE", "warning", "Legacy unmapped section is large.", section.id))
    return report


def _headings(text: str) -> list[str]:
    return [match.group(0).strip() for match in re.finditer(r"^#{1,6}\s+.+$", text, flags=re.MULTILINE)]


def safe_autofix_prompt_ir(prompt_ir: PromptIR) -> PromptIR:
    """Apply conservative prompt-health fixes that do not change semantics."""

    changed = False
    seen: set[str] = set()
    sections = []
    for index, section in enumerate(prompt_ir.sections, start=1):
        section_id = section.id or f"section_{index}"
        if section_id in seen:
            section_id = f"{section_id}_{index}"
        seen.add(section_id)
        content = section.content.rstrip()
        if section_id != section.id or content != section.content:
            changed = True
            section = section.clone_with_content(content, rendering_enabled=section.rendering_enabled)
            section.id = section_id
        if section.id in {"output_schema", "analysis_output_schema"} and section.mutability != "frozen":
            changed = True
            section.mutability = "frozen"
            section.compressibility = "none"
        sections.append(section)
    if not changed:
        return prompt_ir
    from dataclasses import replace
    rendering_order = [sid for sid in prompt_ir.rendering_order if sid in seen] or [section.id for section in sections]
    return replace(prompt_ir, sections=sections, rendering_order=rendering_order)
