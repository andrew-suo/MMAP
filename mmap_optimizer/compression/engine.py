"""Compression candidate orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mmap_optimizer.compression.report import CompressionReport
from mmap_optimizer.compression.semantic import (
    PruneFn,
    SemanticCompressionResult,
    ValidationFn,
    semantic_prune_section,
)


@dataclass(frozen=True, slots=True)
class CompressionCandidate:
    """Structured candidate content plus semantic and behavior-gate outcomes."""

    content: str
    accepted: bool
    semantic: SemanticCompressionResult
    behavior_preservation_passed: bool | None
    rejected_reason: str | None


BehaviorGate = Callable[[str, str], bool]


def _copy_semantic_to_report(
    report: CompressionReport,
    semantic: SemanticCompressionResult,
) -> None:
    report.semantic_attempt_count = semantic.attempt_count
    report.semantic_candidate_lines = semantic.candidate_lines
    report.record_semantic_result(
        validation_reason=semantic.validation_reason,
        rejected_reason=semantic.rejected_reason,
    )


def _compression_candidate_content(
    original_section: str,
    *,
    prune: PruneFn,
    validate: ValidationFn,
    max_attempts: int = 1,
    behavior_gate: BehaviorGate | None = None,
    report: CompressionReport | None = None,
) -> CompressionCandidate:
    """Build and vet a compression candidate.

    Semantic validation metadata is always written to ``report`` when supplied
    and is also returned in the structured ``CompressionCandidate``. The
    behavior-preservation gate remains the final decision point: even a
    semantically valid candidate is rejected if the behavior gate fails.
    """

    semantic = semantic_prune_section(
        original_section,
        prune,
        validate,
        max_attempts=max_attempts,
    )

    if report is not None:
        _copy_semantic_to_report(report, semantic)

    if not semantic.accepted:
        if report is not None:
            report.accepted = False
            report.rejected_reason = semantic.rejected_reason
        return CompressionCandidate(
            content=original_section,
            accepted=False,
            semantic=semantic,
            behavior_preservation_passed=None,
            rejected_reason=semantic.rejected_reason,
        )

    behavior_passed = True if behavior_gate is None else behavior_gate(original_section, semantic.content)
    if report is not None:
        report.behavior_preservation_passed = behavior_passed

    if not behavior_passed:
        if report is not None:
            report.accepted = False
            report.rejected_reason = "behavior_preservation_failed"
        return CompressionCandidate(
            content=original_section,
            accepted=False,
            semantic=semantic,
            behavior_preservation_passed=False,
            rejected_reason="behavior_preservation_failed",
        )

    if report is not None:
        report.accepted = True
        report.rejected_reason = None
    return CompressionCandidate(
        content=semantic.content,
        accepted=True,
        semantic=semantic,
        behavior_preservation_passed=behavior_passed,
        rejected_reason=None,
    )
