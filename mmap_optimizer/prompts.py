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


def _parse_semver(version: str) -> tuple[int, int, int]:
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return 0, 0, 0
    return int(parts[0]), int(parts[1]), int(parts[2])
