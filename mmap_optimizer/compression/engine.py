"""Compression candidate ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from mmap_optimizer.metrics.section_contribution import compute_section_risk


@dataclass
class CompressionCandidate:
    section_id: str
    tokens: int
    contribution_score: float = 0.0
    risk_score: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)


def _coerce_candidate(candidate: CompressionCandidate | Mapping[str, Any]) -> CompressionCandidate:
    if isinstance(candidate, CompressionCandidate):
        return candidate
    metrics = dict(candidate.get("metrics", {})) if isinstance(candidate.get("metrics", {}), Mapping) else {}
    risk_score = candidate.get("risk_score", metrics.get("risk_score"))
    if risk_score is None:
        risk_score = compute_section_risk(metrics.get("cited", 0.0), metrics.get("parasite", 0.0), metrics.get("accuracy", 1.0))
    contribution = float(candidate.get("contribution_score", candidate.get("score", metrics.get("ema_score", metrics.get("score", 0.0)))))
    return CompressionCandidate(
        section_id=str(candidate.get("section_id", "")),
        tokens=int(candidate.get("tokens", 0)),
        contribution_score=contribution,
        risk_score=float(risk_score),
        metrics=metrics,
    )


class CompressionEngine:
    """Orders sections for compression.

    Higher return order means earlier compression.  High contribution or high
    risk sections are deliberately pushed down so critical rules survive longer.
    """

    def compression_priority(self, candidate: CompressionCandidate | Mapping[str, Any]) -> float:
        item = _coerce_candidate(candidate)
        return float(item.tokens) - (100.0 * max(0.0, item.contribution_score)) - (100.0 * item.risk_score)

    def sort_candidates(self, candidates: Iterable[CompressionCandidate | Mapping[str, Any]]) -> list[CompressionCandidate]:
        coerced = [_coerce_candidate(candidate) for candidate in candidates]
        return sorted(coerced, key=self.compression_priority, reverse=True)
