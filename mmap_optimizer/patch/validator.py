from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mmap_optimizer.prompt.ir import PromptIR
from .schema import TEXT_LEVEL_OPERATION_MODES, Patch

FORBIDDEN_SECTIONS = {"output_schema", "analysis_output_schema"}
DISABLED_OPERATIONS = {"DELETE_RULE", "ADD_SECTION"}

ALLOWED_BY_SECTION = {
    "format_compliance_policy": {"STRENGTHEN_FORMAT_COMPLIANCE", "ADD_SELF_CHECK", "REFINE_RULE", "ADD_RULE"},
    "schema_guard_policy": {"STRENGTHEN_FORMAT_COMPLIANCE", "ADD_RULE", "REFINE_RULE"},
}


class PatchValidationError(ValueError):
    """Raised when a patch is invalid and cannot be applied safely."""


@dataclass
class PatchValidationResult:
    valid: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"valid": bool(self.valid), "reason": self.reason}


class PatchValidator:
    def validate(self, patch: Patch, prompt_ir: PromptIR) -> PatchValidationResult:
        section = prompt_ir.section_by_id(patch.section_id)
        if section is None:
            return PatchValidationResult(False, "INVALID_TARGET_SECTION")
        if patch.section_id in FORBIDDEN_SECTIONS or section.mutability == "frozen":
            return PatchValidationResult(False, "TARGET_SECTION_FROZEN")
        if patch.operation_type in DISABLED_OPERATIONS:
            return PatchValidationResult(False, "OPERATION_DISABLED")
        if not patch.patch_text.strip() and patch.operation_mode != "delete":
            return PatchValidationResult(False, "EMPTY_PATCH_TEXT")
        if patch.target_prompt_type == "extraction" and not patch.source_sample_ids:
            return PatchValidationResult(False, "MISSING_SOURCE_SAMPLE")

        constraints = patch.constraints or {}
        patch_allowed_ops = constraints.get("allowed_operation_types")
        if patch_allowed_ops is not None:
            if patch.operation_type not in set(patch_allowed_ops):
                return PatchValidationResult(
                    False,
                    f"OPERATION_NOT_ALLOWED_BY_CONSTRAINT: {patch.operation_type!r} not in {patch_allowed_ops}",
                )
        else:
            allowed = ALLOWED_BY_SECTION.get(patch.section_id)
            if allowed is not None and patch.operation_type not in allowed:
                return PatchValidationResult(
                    False,
                    f"OPERATION_NOT_ALLOWED: {patch.operation_type!r} not in {sorted(allowed)}",
                )

        forbidden_words = constraints.get("forbidden_keywords")
        default_schema_words = ["新增字段", "删除字段", "修改字段", "output schema", "analysis_output_schema"]
        check_words = list(forbidden_words) if forbidden_words is not None else default_schema_words
        for word in check_words:
            if word in patch.patch_text:
                return PatchValidationResult(
                    False,
                    f"SCHEMA_IMMUTABILITY_VIOLATION: forbidden keyword {word!r} found in patch_text",
                )

        must_mention = constraints.get("must_mention_section_ids") or constraints.get("must_mention")
        if must_mention:
            normalized = [str(x).strip() for x in must_mention if str(x).strip()]
            if normalized:
                # 仅检查 patch_text 和 rationale，不包含 section_id
                # （包含 section_id 会导致只要目标是该 section 就通过验证）
                haystack = f"{patch.patch_text}\n{patch.rationale or ''}"
                missing = [m for m in normalized if m not in haystack]
                if missing:
                    return PatchValidationResult(
                        False,
                        f"MUST_MENTION_SECTION_MISSING: {missing!r} not found in patch_text/rationale",
                    )

        mode = patch.effective_operation_mode
        if mode == "replace_in_section":
            old_text = patch.locator_value("old_text")
            if not old_text or not isinstance(old_text, str) or old_text not in section.content:
                return PatchValidationResult(False, "PATCH_LOCATOR_NOT_FOUND")
            occurrences = section.content.count(old_text)
            if occurrences > 1:
                return PatchValidationResult(False, "AMBIGUOUS_LOCATOR")
        elif mode in {"insert_after", "insert_before"}:
            target_text = patch.locator_value("target_text")
            if not target_text or not isinstance(target_text, str) or target_text not in section.content:
                return PatchValidationResult(False, "PATCH_LOCATOR_NOT_FOUND")
            occurrences = section.content.count(target_text)
            if occurrences > 1:
                return PatchValidationResult(False, "AMBIGUOUS_LOCATOR")
        elif mode == "delete":
            target_text = patch.locator_value("old_text") or patch.locator_value("target_text")
            if not target_text or not isinstance(target_text, str) or target_text not in section.content:
                return PatchValidationResult(False, "PATCH_LOCATOR_NOT_FOUND")
            occurrences = section.content.count(target_text)
            if occurrences > 1:
                return PatchValidationResult(False, "AMBIGUOUS_LOCATOR")
        return PatchValidationResult(True)
