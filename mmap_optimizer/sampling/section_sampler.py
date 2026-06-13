"""Section sampling helpers informed by contribution EMA."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from mmap_optimizer.metrics.section_contribution import compute_section_risk


@dataclass(frozen=True)
class SectionSampleCandidate:
    section_id: str
    score: float = 0.0
    risk_score: float = 0.0
    base_weight: float = 1.0


def _coerce_candidate(candidate: SectionSampleCandidate | Mapping[str, Any]) -> SectionSampleCandidate:
    if isinstance(candidate, SectionSampleCandidate):
        return candidate
    metrics = dict(candidate.get("metrics", {})) if isinstance(candidate.get("metrics", {}), Mapping) else {}
    score = float(candidate.get("ema_score", candidate.get("score", metrics.get("ema_score", metrics.get("score", 0.0)))))
    risk = candidate.get("risk_score", metrics.get("risk_score"))
    if risk is None:
        risk = compute_section_risk(metrics.get("cited", 0.0), metrics.get("parasite", 0.0), metrics.get("accuracy", 1.0))
    return SectionSampleCandidate(
        section_id=str(candidate.get("section_id", "")),
        score=score,
        risk_score=float(risk),
        base_weight=float(candidate.get("base_weight", 1.0)),
    )


def section_sampling_weight(candidate: SectionSampleCandidate | Mapping[str, Any]) -> float:
    """Return sampling weight; negative contribution and risk raise priority."""

    item = _coerce_candidate(candidate)
    negative_contribution_boost = max(0.0, -item.score)
    return max(0.0, item.base_weight) * (1.0 + negative_contribution_boost + item.risk_score)


def rank_sections_for_sampling(
    candidates: Iterable[SectionSampleCandidate | Mapping[str, Any]],
) -> list[SectionSampleCandidate]:
    """Rank sections so weak/high-risk contributors are sampled first."""

    coerced = [_coerce_candidate(candidate) for candidate in candidates]
    return sorted(coerced, key=section_sampling_weight, reverse=True)
