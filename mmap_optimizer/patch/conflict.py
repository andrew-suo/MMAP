from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import Patch


@dataclass
class PatchConflict:
    id: str
    patch_ids: list[str]
    section_id: str
    conflict_type: str
    reason: str


OK_BIAS = ("优先输出OK", "优先判定OK", "强制输出OK", "倾向OK", "优先合格", "强制合格", "判为合格")
NG_BIAS = ("优先输出NG", "优先判定NG", "强制输出NG", "倾向NG", "优先不合格", "强制不合格", "判为不合格")
RELAXED = ("放宽", "忽略", "不作为不合格", "无需判不合格", "可以合格")
STRICT = ("严格", "必须", "一律判不合格", "必须判不合格", "不得忽略")


def detect_patch_conflicts(patches: list[Patch], prompt_ir: Any | None = None) -> list[PatchConflict]:
    conflicts: list[PatchConflict] = []
    for patch in patches:
        if prompt_ir is not None:
            section = prompt_ir.section_by_id(patch.section_id)
            if section is not None and (section.mutability == "frozen" or patch.section_id in {"output_schema", "analysis_output_schema"}):
                conflicts.append(
                    PatchConflict(
                        id=f"conflict_{patch.id}_frozen_target",
                        patch_ids=[patch.id],
                        section_id=patch.section_id,
                        conflict_type="SCHEMA_OR_FROZEN_TARGET",
                        reason="Patch targets a frozen/schema section.",
                    )
                )
    for idx, left in enumerate(patches):
        for right in patches[idx + 1:]:
            if left.section_id != right.section_id:
                continue
            conflict_type = _pair_conflict_type(left, right)
            if conflict_type is None:
                continue
            conflicts.append(
                PatchConflict(
                    id=f"conflict_{left.id}_{right.id}",
                    patch_ids=[left.id, right.id],
                    section_id=left.section_id,
                    conflict_type=conflict_type,
                    reason=f"{left.id} conflicts with {right.id}: {conflict_type}",
                )
            )
    return conflicts


def _pair_conflict_type(left: Patch, right: Patch) -> str | None:
    left_text = left.patch_text.upper()
    right_text = right.patch_text.upper()
    if (_contains_any(left_text, OK_BIAS) and _contains_any(right_text, NG_BIAS)) or (_contains_any(left_text, NG_BIAS) and _contains_any(right_text, OK_BIAS)):
        return "OPPOSITE_LABEL_BIAS"
    if (_contains_any(left.patch_text, RELAXED) and _contains_any(right.patch_text, STRICT)) or (_contains_any(left.patch_text, STRICT) and _contains_any(right.patch_text, RELAXED)):
        return "STRICTNESS_CONFLICT"
    ops = {left.operation_type, right.operation_type}
    if "DELETE_RULE" in ops and ops & {"ADD_RULE", "REWRITE_RULE", "REFINE_RULE"}:
        return "OPERATION_CONFLICT"
    return None


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    text_upper = text.upper()
    return any(needle.upper() in text_upper for needle in needles)
