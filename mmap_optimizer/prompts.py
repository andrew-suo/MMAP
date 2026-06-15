"""Prompt IR and versioning primitives.

The optimizer uses these classes for both task prompts and evaluation prompts.
Evaluation-specific optimization therefore does not need a parallel prompt model;
it can reuse :class:`PromptIR` and :class:`PromptVersion` with a different
``prompt_type`` value.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping, Sequence


DEFAULT_EVALUATION_PROMPT_SYSTEM = """# Role
You are a strict, evidence-grounded evaluator. Your job is to determine whether a model output satisfies the task expectations under the provided evaluation prompt.

# Legacy EVALUATION_PROMPT — Evaluation Discipline Framework

## 1. Eval-Blind Context Discipline
Evaluate only from the provided prompt, input, expected answer / ground truth, and model output. Do not use outside knowledge or infer unstated business rules. Do not add constraints that were not stated in the provided context.

## 2. Passing Case Protection
If the model output satisfies the expected behavior under the current prompt and task context, mark it as correct / pass according to the existing output vocabulary. Do not invent improvement suggestions for passing cases. Do not penalize for style, length, or wording differences that do not violate any stated rule.

## 3. Failure Localization
When the output is wrong, identify the most specific failure reason and locate which prompt rule, output-format requirement, or decision condition was violated. Do not collapse a specific failure into a generic "wrong" label without naming the violated rule.

## 4. Separate Task Failure from Formatting Failure
Distinguish semantic / task-decision failures from output-format / schema failures. If both exist, report both according to the existing output contract, but do not collapse them into a vague generic error.

## 5. Evidence-Grounded Judgement
Every failure explanation must be grounded in observable evidence from the model output, expected answer / ground truth, or current prompt text. Do not declare an outcome without citing evidence.

## 6. No Patch Generation During Evaluation
Evaluation should diagnose correctness and failure reasons only. Do not generate patch objects, rewrite prompt sections, propose concrete patch operations, or fix the model output — unless the current output schema already has a dedicated recommendation field.

## 7. Minimal Actionable Failure Reason
Prefer a concise, actionable failure reason that can guide downstream patch generation. Avoid broad statements such as "be more careful" or "improve reasoning".

## 8. Output Contract Strictness
Return exactly the current required evaluation output format. Do not include Markdown, explanations outside JSON, fences, extra commentary, or fields not defined by the current contract.

## 9. Ambiguity Handling
If correctness cannot be determined from the provided context, use the existing uncertainty / invalid / inconclusive mechanism if one exists. If no such mechanism exists, choose the closest existing status without inventing a new status, and explain the missing evidence within the allowed fields.

# Migration Note
This evaluation prompt has been enriched with the evaluation discipline and failure-localization rules inherited from the legacy EVALUATION_PROMPT.
- The frozen output schema, output format, and evaluation-rules decision vocabulary remain unchanged.
- No new status labels, decisions, or required fields are introduced.
- No optimizer loop, CLI, or runtime behavior is affected.
- No patch-template behavior is modified or added.
"""


@dataclass(frozen=True)
class EvaluationRule:
    """A structured rule in an evaluation prompt."""

    rule_id: str
    condition: str
    decision: str
    explanation: str = ""

    def render(self) -> str:
        suffix = f" Rationale: {self.explanation}" if self.explanation else ""
        return f"- [{self.rule_id}] If {self.condition}, decide `{self.decision}`.{suffix}"


@dataclass(frozen=True)
class PromptIR:
    """Intermediate representation for prompts.

    ``output_schema`` and ``output_format`` are intentionally top-level fields
    so validators can freeze them while still allowing prompt-rule edits.
    """

    system: str
    evaluation_rules: tuple[EvaluationRule, ...] = ()
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    output_format: str = "json"
    prompt_type: str = "task"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluation_rules", tuple(self.evaluation_rules))
        object.__setattr__(self, "output_schema", MappingProxyType(dict(self.output_schema)))

    def render(self) -> str:
        rules = "\n".join(rule.render() for rule in self.evaluation_rules) or "- No evaluation rules."
        return (
            f"{self.system}\n\n"
            f"Evaluation rules:\n{rules}\n\n"
            f"Output format: {self.output_format}\n"
            f"Output schema: {dict(self.output_schema)}"
        )

    def with_rules(self, rules: Sequence[EvaluationRule]) -> "PromptIR":
        return replace(self, evaluation_rules=tuple(rules))


@dataclass(frozen=True)
class PromptVersion:
    """Version wrapper for a prompt IR."""

    version: str
    prompt_ir: PromptIR
    parent_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def bump(self, prompt_ir: PromptIR, patch_id: str) -> "PromptVersion":
        major, minor, patch = _parse_semver(self.version)
        return PromptVersion(
            version=f"{major}.{minor}.{patch + 1}",
            prompt_ir=prompt_ir,
            parent_version=self.version,
            metadata={**self.metadata, "last_patch_id": patch_id},
        )


DEFAULT_EVALUATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "decision": "string",
    "reason": "string",
}


def make_default_evaluation_prompt_ir() -> PromptIR:
    """Return a `PromptIR` pre-configured with the legacy EVALUATION_PROMPT
    system discipline, JSON output contract, and empty evaluation rules.

    This keeps the existing label vocabulary, output schema, and output format
    intact — only the system instruction content is enriched with the legacy
    evaluation discipline.
    """
    return PromptIR(
        system=DEFAULT_EVALUATION_PROMPT_SYSTEM,
        evaluation_rules=(),
        output_schema=DEFAULT_EVALUATION_OUTPUT_SCHEMA,
        output_format="json",
        prompt_type="evaluation",
    )


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return 0, 0, 0
    return int(parts[0]), int(parts[1]), int(parts[2])
