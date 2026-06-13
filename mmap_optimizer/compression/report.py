"""Structured reporting for compression decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CompressionReport:
    """Mutable report populated while evaluating a compression candidate.

    The semantic fields intentionally distinguish validation state from the
    behavior-preservation gate. Semantic validation can approve a candidate,
    but the behavior gate remains the final authority on whether the candidate
    may be used.
    """

    accepted: bool = False
    rejected_reason: str | None = None
    behavior_preservation_passed: bool | None = None

    semantic_validation_reason: str | None = None
    semantic_attempt_count: int = 0
    semantic_candidate_lines: list[list[str]] = field(default_factory=list)
    semantic_rejected_reason: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def record_semantic_attempt(self, candidate: str) -> None:
        """Record a semantic pruning attempt and its candidate lines."""

        self.semantic_attempt_count += 1
        self.semantic_candidate_lines.append(candidate.splitlines())

    def record_semantic_result(
        self,
        *,
        validation_reason: str | None,
        rejected_reason: str | None,
    ) -> None:
        """Store the latest semantic validation outcome."""

        self.semantic_validation_reason = validation_reason
        self.semantic_rejected_reason = rejected_reason

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the report."""

        return {
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
            "behavior_preservation_passed": self.behavior_preservation_passed,
            "semantic_validation_reason": self.semantic_validation_reason,
            "semantic_attempt_count": self.semantic_attempt_count,
            "semantic_candidate_lines": self.semantic_candidate_lines,
            "semantic_rejected_reason": self.semantic_rejected_reason,
            "metadata": self.metadata,
        }
