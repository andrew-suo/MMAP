from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.prompt.ir import PromptIR
from .schema import Patch

FORBIDDEN_SECTIONS = {"output_schema", "analysis_output_schema"}
DISABLED_OPERATIONS = {"DELETE_RULE", "ADD_SECTION"}

ALLOWED_BY_SECTION = {
    "format_compliance_policy": {"STRENGTHEN_FORMAT_COMPLIANCE", "ADD_SELF_CHECK", "REFINE_RULE", "ADD_RULE"},
    "schema_guard_policy": {"STRENGTHEN_FORMAT_COMPLIANCE", "ADD_RULE", "REFINE_RULE"},
}


@dataclass
class PatchValidationResult:
    valid: bool
    reason: str | None = None


class PatchValidator:
    def validate(self, patch: Patch, prompt_ir: PromptIR) -> PatchValidationResult:
        section = prompt_ir.section_by_id(patch.section_id)
        if section is None:
            return PatchValidationResult(False, "INVALID_TARGET_SECTION")
        if patch.section_id in FORBIDDEN_SECTIONS or section.mutability == "frozen":
            return PatchValidationResult(False, "TARGET_SECTION_FROZEN")
        if patch.operation_type in DISABLED_OPERATIONS:
            return PatchValidationResult(False, "OPERATION_DISABLED")
        if not patch.patch_text.strip():
            return PatchValidationResult(False, "EMPTY_PATCH_TEXT")
        if patch.target_prompt_type == "extraction" and not patch.source_sample_ids:
            return PatchValidationResult(False, "MISSING_SOURCE_SAMPLE")
        allowed = ALLOWED_BY_SECTION.get(patch.section_id)
        if allowed is not None and patch.operation_type not in allowed:
            return PatchValidationResult(False, "OPERATION_NOT_ALLOWED")
        schema_words = ["新增字段", "删除字段", "修改字段", "output schema", "analysis_output_schema"]
        if any(word in patch.patch_text for word in schema_words):
            return PatchValidationResult(False, "SCHEMA_IMMUTABILITY_VIOLATION")
        if patch.operation_mode == "replace_in_section":
            old_text = patch.old_text or patch.extra.get("old_text")
            if not old_text or old_text not in section.content:
                return PatchValidationResult(False, "PATCH_LOCATOR_NOT_FOUND")
        if patch.operation_mode in {"insert_after", "insert_before"}:
            target_text = patch.target_text or patch.extra.get("target_text")
            if not target_text or target_text not in section.content:
                return PatchValidationResult(False, "PATCH_LOCATOR_NOT_FOUND")
        return PatchValidationResult(True)
