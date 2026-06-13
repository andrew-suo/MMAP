"""Semantic pruning and validation retry logic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class PruneFn(Protocol):
    """Callable that produces a pruned section candidate."""

    def __call__(self, section: str) -> str: ...


class ValidationFn(Protocol):
    """Callable that validates a candidate against the original section."""

    def __call__(self, original_section: str, candidate_section: str) -> Any: ...


@dataclass(frozen=True, slots=True)
class SemanticValidationResult:
    """Normalized validation result returned by semantic validators."""

    valid: bool
    reason: str | None = None


@dataclass(slots=True)
class SemanticCompressionResult:
    """Result of semantic pruning attempts."""

    content: str
    accepted: bool
    attempt_count: int
    validation_reason: str | None = None
    rejected_reason: str | None = None
    candidate_lines: list[list[str]] = field(default_factory=list)


def _parse_validation_result(raw_result: Any) -> SemanticValidationResult:
    """Normalize validator output or raise ValueError for malformed results."""

    if isinstance(raw_result, SemanticValidationResult):
        return raw_result
    if isinstance(raw_result, bool):
        return SemanticValidationResult(valid=raw_result)
    if isinstance(raw_result, dict):
        valid = raw_result.get("valid")
        if not isinstance(valid, bool):
            raise ValueError("semantic validation result must include boolean 'valid'")
        reason = raw_result.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("semantic validation 'reason' must be a string when provided")
        return SemanticValidationResult(valid=valid, reason=reason)
    raise ValueError("semantic validation result must be bool, dict, or SemanticValidationResult")


def semantic_prune_section(
    original_section: str,
    prune: PruneFn,
    validate: ValidationFn,
    *,
    max_attempts: int = 1,
) -> SemanticCompressionResult:
    """Prune a section with retry-on-validation-failure semantics.

    Each validation attempt compares the new candidate with the unmodified
    ``original_section``. This is important because a failed candidate must not
    become the baseline for a later retry.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    candidate_lines: list[list[str]] = []
    last_reason: str | None = None

    for attempt in range(1, max_attempts + 1):
        candidate = prune(original_section)
        candidate_lines.append(candidate.splitlines())

        try:
            validation = _parse_validation_result(validate(original_section, candidate))
        except ValueError as exc:
            return SemanticCompressionResult(
                content=original_section,
                accepted=False,
                attempt_count=attempt,
                validation_reason=None,
                rejected_reason=f"validation_parse_error: {exc}",
                candidate_lines=candidate_lines,
            )

        last_reason = validation.reason
        if validation.valid:
            return SemanticCompressionResult(
                content=candidate,
                accepted=True,
                attempt_count=attempt,
                validation_reason=validation.reason,
                rejected_reason=None,
                candidate_lines=candidate_lines,
            )

    return SemanticCompressionResult(
        content=original_section,
        accepted=False,
        attempt_count=max_attempts,
        validation_reason=last_reason,
        rejected_reason="semantic_validation_failed",
        candidate_lines=candidate_lines,
    )
