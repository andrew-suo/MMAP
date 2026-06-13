"""Compression engine orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .report import CompressionReport
from .semantic import SemanticCompressionCandidate, semantic_compress_section


@dataclass(slots=True)
class CompressionCandidate:
    """Structured compression candidate returned by the engine."""

    content: str
    reason: str
    strategy: str
    accepted: bool
    semantic_attempt_count: int = 0
    semantic_validation_reason: str | None = None
    semantic_validation_raw_output: str | None = None
    semantic_candidate_line_count: int = 0
    semantic_rejected_reason: str | None = None


class CompressionEngine:
    """Coordinate deterministic and semantic compression strategies."""

    def __init__(
        self,
        *,
        llm: Any | None = None,
        max_attempts: int = 1,
        deterministic_compressor: Callable[[str], Any] | None = None,
        behavior_gate: Callable[[str, str], bool | tuple[bool, str]] | None = None,
    ) -> None:
        self.llm = llm
        self.max_attempts = max_attempts
        self.deterministic_compressor = deterministic_compressor
        self.behavior_gate = behavior_gate
        self.report: CompressionReport | None = None

    def compress_section(self, section_content: str) -> str:
        """Return compressed content and store the corresponding report."""

        candidate = self._compression_candidate_content(section_content)
        self.report = CompressionReport.from_candidate(
            original_content=section_content,
            candidate=candidate,
        )
        return candidate.content if candidate.accepted else section_content

    def _compression_candidate_content(self, section_content: str) -> CompressionCandidate:
        """Return a structured candidate instead of a ``(content, reason)`` tuple."""

        deterministic = self._deterministic_candidate(section_content)
        if deterministic is not None:
            return deterministic

        if self.llm is None:
            return CompressionCandidate(
                content=section_content,
                reason="no semantic llm configured",
                strategy="none",
                accepted=False,
            )

        semantic = semantic_compress_section(
            section_content,
            self.llm,
            max_attempts=self.max_attempts,
            behavior_gate=self.behavior_gate,
        )
        return self._from_semantic(semantic)

    def _deterministic_candidate(self, section_content: str) -> CompressionCandidate | None:
        if self.deterministic_compressor is None:
            return None

        raw = self.deterministic_compressor(section_content)
        if raw is None or raw is False:
            return None

        if isinstance(raw, CompressionCandidate):
            return raw

        reason = "deterministic_compression"
        accepted = True
        content: str
        if isinstance(raw, tuple):
            content = str(raw[0])
            if len(raw) > 1:
                reason = str(raw[1])
            if len(raw) > 2:
                accepted = bool(raw[2])
        else:
            content = str(raw)

        return CompressionCandidate(
            content=content,
            reason=reason,
            strategy="deterministic",
            accepted=accepted,
        )

    @staticmethod
    def _from_semantic(semantic: SemanticCompressionCandidate) -> CompressionCandidate:
        return CompressionCandidate(
            content=semantic.content,
            reason=semantic.reason,
            strategy="semantic",
            accepted=semantic.accepted,
            semantic_attempt_count=semantic.attempt_count,
            semantic_validation_reason=semantic.validation_reason,
            semantic_validation_raw_output=semantic.validation_raw_output,
            semantic_candidate_line_count=semantic.candidate_line_count,
            semantic_rejected_reason=semantic.rejected_reason,
        )
