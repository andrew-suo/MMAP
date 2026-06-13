"""Patch validation and application primitives shared by prompt optimizers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from mmap_optimizer.prompts import EvaluationRule, PromptIR


@dataclass(frozen=True)
class PatchOperation:
    op: str
    path: str
    value: Any


@dataclass(frozen=True)
class PatchCandidate:
    patch_id: str
    title: str
    operations: tuple[PatchOperation, ...]
    rationale: str
    source_case_ids: tuple[str, ...] = ()
    target_prompt_type: str = "task"


@dataclass(frozen=True)
class PatchValidationResult:
    valid: bool
    reasons: tuple[str, ...] = ()
    schema_violations: tuple[str, ...] = ()
    output_format_violations: tuple[str, ...] = ()


class PatchValidator:
    """Validates prompt patches before they can be behavior-tested."""

    def __init__(
        self,
        *,
        target_prompt_type: str,
        frozen_paths: Iterable[str] = ("/output_schema", "/output_format"),
    ) -> None:
        self.target_prompt_type = target_prompt_type
        self.frozen_paths = tuple(frozen_paths)

    def validate(self, candidate: PatchCandidate) -> PatchValidationResult:
        reasons: list[str] = []
        schema_violations: list[str] = []
        output_format_violations: list[str] = []

        if candidate.target_prompt_type != self.target_prompt_type:
            reasons.append(
                f"target_prompt_type must be {self.target_prompt_type!r}, got {candidate.target_prompt_type!r}"
            )

        for operation in candidate.operations:
            if operation.op not in {"add", "replace"}:
                reasons.append(f"unsupported operation {operation.op!r} at {operation.path}")
            if operation.path.startswith("/output_schema"):
                schema_violations.append(f"schema is frozen: {operation.path}")
            if operation.path.startswith("/output_format"):
                output_format_violations.append(f"output format is frozen: {operation.path}")
            if not operation.path.startswith("/evaluation_rules/"):
                reasons.append(f"only /evaluation_rules/* may be changed, got {operation.path}")
            if operation.path.startswith("/evaluation_rules/") and not isinstance(operation.value, EvaluationRule):
                reasons.append(f"evaluation rule operation at {operation.path} must contain an EvaluationRule")

        all_reasons = tuple(reasons)
        return PatchValidationResult(
            valid=not all_reasons and not schema_violations and not output_format_violations,
            reasons=all_reasons,
            schema_violations=tuple(schema_violations),
            output_format_violations=tuple(output_format_violations),
        )


class PatchApplier:
    """Applies validated patches to a PromptIR."""

    def apply(self, prompt_ir: PromptIR, candidate: PatchCandidate) -> PromptIR:
        rules_by_id = {rule.rule_id: rule for rule in prompt_ir.evaluation_rules}
        order = [rule.rule_id for rule in prompt_ir.evaluation_rules]

        for operation in candidate.operations:
            if not operation.path.startswith("/evaluation_rules/"):
                raise ValueError(f"cannot apply non-rule operation {operation.path}")
            rule = operation.value
            if not isinstance(rule, EvaluationRule):
                raise TypeError("evaluation-rule operations require EvaluationRule values")
            if rule.rule_id not in rules_by_id:
                order.append(rule.rule_id)
            rules_by_id[rule.rule_id] = rule

        return prompt_ir.with_rules([rules_by_id[rule_id] for rule_id in order])
