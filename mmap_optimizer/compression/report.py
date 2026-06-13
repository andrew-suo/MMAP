"""Reporting primitives for compression runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class CompressionReport:
    """Structured metadata emitted by the compression engine.

    The semantic fields intentionally mirror the semantic candidate result so a
    caller can persist exactly what happened during LLM pruning and validation.
    """

    original_line_count: int = 0
    candidate_line_count: int = 0
    strategy: str | None = None
    accepted: bool = False
    reason: str | None = None

    semantic_attempt_count: int = 0
    semantic_validation_reason: str | None = None
    semantic_validation_raw_output: str | None = None
    semantic_candidate_line_count: int = 0
    semantic_rejected_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary representation."""

        return asdict(self)

    @classmethod
    def from_candidate(
        cls,
        *,
        original_content: str,
        candidate: Any,
    ) -> "CompressionReport":
        """Build a report from any candidate-like object.

        The engine passes a :class:`CompressionCandidate`, while tests and
        integrations may pass compatible objects.  Missing semantic attributes
        default to neutral values.
        """

        content = getattr(candidate, "content", "") or ""
        return cls(
            original_line_count=_line_count(original_content),
            candidate_line_count=_line_count(content),
            strategy=getattr(candidate, "strategy", None),
            accepted=bool(getattr(candidate, "accepted", False)),
            reason=getattr(candidate, "reason", None),
            semantic_attempt_count=int(getattr(candidate, "semantic_attempt_count", 0) or 0),
            semantic_validation_reason=getattr(candidate, "semantic_validation_reason", None),
            semantic_validation_raw_output=getattr(candidate, "semantic_validation_raw_output", None),
            semantic_candidate_line_count=int(
                getattr(candidate, "semantic_candidate_line_count", 0) or 0
            ),
            semantic_rejected_reason=getattr(candidate, "semantic_rejected_reason", None),
        )


def _line_count(content: str) -> int:
    """Count logical lines without treating an empty string as one line."""

    if not content:
        return 0
    return len(content.splitlines())
