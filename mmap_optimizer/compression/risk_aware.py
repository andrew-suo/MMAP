"""Risk-aware compression candidate scoring, safety gating, and ranking.

This module exposes lightweight helpers for scoring and gating compression
candidates before they reach the default :class:`CompressionEngine`. The
helpers are intentionally decoupled from the optimizer loop, model clients,
and the semantic compression pipeline. They accept plain-dict inputs
(``section_contributions``, ``risk_signals``) and return deterministic
:class:`CompressionDecision` records suitable for auditing.

The default :class:`CompressionEngine` is **not** modified by this module.
The helpers can be composed with the existing engine by callers that want
risk-aware behavior, but they do not change any default paths.

Design notes:

* ``compression_score`` is bounded to ``[0, 1]``. Higher is safer/better.
* The composite combines compression_ratio, risk_score (inverted),
  positive contribution_delta, toxicity penalty, semantic_loss_risk
  penalty, and broken_sample_count penalty.
* The safety gate is **conservative**: any explicit risk threshold breach
  (high risk, high toxicity, severe semantic loss, large negative
  contribution, or broken samples without improvement) sets
  ``accepted=False`` and records a ``rejection_reason``.
* Ranking is fully deterministic for a given input order and uses
  ``(-compression_score, section_id asc, candidate_id asc)`` as the sort
  key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class CompressionDecision:
    """Scoring + safety decision for a single compression candidate.

    ``compression_score`` and ``accepted``/``rejection_reason`` are computed
    by :func:`score_compression_candidate`. All other fields are pass-through
    input metadata so the report remains self-contained for downstream
    auditing and ranking.
    """

    candidate_id: str
    section_id: str
    compression_ratio: float = 0.0
    contribution_delta: float = 0.0
    risk_score: float = 0.0
    toxicity_risk: float = 0.0
    broken_sample_count: int = 0
    semantic_loss_risk: float = 0.0
    candidate_sample_count: int = 0
    compression_score: float = 0.0
    accepted: bool = False
    rejection_reason: str | None = None
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "section_id": self.section_id,
            "compression_ratio": round(float(self.compression_ratio), 6),
            "contribution_delta": round(float(self.contribution_delta), 6),
            "risk_score": round(float(self.risk_score), 6),
            "toxicity_risk": round(float(self.toxicity_risk), 6),
            "broken_sample_count": int(self.broken_sample_count),
            "semantic_loss_risk": round(float(self.semantic_loss_risk), 6),
            "candidate_sample_count": int(self.candidate_sample_count),
            "compression_score": round(float(self.compression_score), 6),
            "accepted": bool(self.accepted),
            "rejection_reason": self.rejection_reason,
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------


COMPRESSION_RATIO_WEIGHT = 0.45
RISK_INVERTED_WEIGHT = 0.30
CONTRIBUTION_WEIGHT = 0.15
TOXICITY_PENALTY = 0.20
SEMANTIC_LOSS_PENALTY = 0.15
BROKEN_SAMPLE_PENALTY_PER_COUNT = 0.10
BROKEN_SAMPLE_PENALTY_MAX = 1.0

HIGH_RISK_THRESHOLD = 0.66
HIGH_TOXICITY_THRESHOLD = 0.50
SEVERE_SEMANTIC_LOSS_THRESHOLD = 0.75
LARGE_NEGATIVE_CONTRIBUTION_THRESHOLD = -0.30


def _unit(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    v = float(value)
    if v < low:
        return low
    if v > high:
        return high
    return v


def score_compression_candidate(
    candidate: CompressionDecision | Mapping[str, Any],
) -> CompressionDecision:
    """Return a scored copy of ``candidate`` with the safety gate applied.

    The input is never mutated. When the input is a :class:`Mapping`, it is
    converted into a :class:`CompressionDecision` first so the report is
    always a properly typed dataclass.

    ``compression_score`` is computed from the weighted components above and
    clamped to ``[0, 1]``. The function then walks through each safety gate
    in priority order; the **first failing gate** sets ``rejection_reason``
    and flips ``accepted`` to ``False``. ``reasons`` collects all triggered
    gates (including subsequent ones) for full auditability.
    """

    if isinstance(candidate, CompressionDecision):
        decision = CompressionDecision(
            candidate_id=candidate.candidate_id,
            section_id=candidate.section_id,
            compression_ratio=float(candidate.compression_ratio),
            contribution_delta=float(candidate.contribution_delta),
            risk_score=float(candidate.risk_score),
            toxicity_risk=float(candidate.toxicity_risk),
            broken_sample_count=int(candidate.broken_sample_count),
            semantic_loss_risk=float(candidate.semantic_loss_risk),
            candidate_sample_count=int(candidate.candidate_sample_count),
            metadata=dict(candidate.metadata),
        )
    else:
        decision = CompressionDecision(
            candidate_id=str(candidate.get("candidate_id", "")),
            section_id=str(candidate.get("section_id", "")),
            compression_ratio=float(candidate.get("compression_ratio", 0.0)),
            contribution_delta=float(candidate.get("contribution_delta", 0.0)),
            risk_score=float(candidate.get("risk_score", 0.0)),
            toxicity_risk=float(candidate.get("toxicity_risk", 0.0)),
            broken_sample_count=int(candidate.get("broken_sample_count", 0)),
            semantic_loss_risk=float(candidate.get("semantic_loss_risk", 0.0)),
            candidate_sample_count=int(candidate.get("candidate_sample_count", 0)),
            metadata=dict(candidate.get("metadata", {})),
        )

    ratio = _unit(decision.compression_ratio)
    risk = _unit(decision.risk_score)
    contribution = _unit(decision.contribution_delta, low=-1.0, high=1.0)
    toxicity = _unit(decision.toxicity_risk)
    semantic_loss = _unit(decision.semantic_loss_risk)
    broken_penalty = _unit(
        float(decision.broken_sample_count) * BROKEN_SAMPLE_PENALTY_PER_COUNT,
        high=BROKEN_SAMPLE_PENALTY_MAX,
    )

    raw_score = (
        COMPRESSION_RATIO_WEIGHT * ratio
        + RISK_INVERTED_WEIGHT * (1.0 - risk)
        + CONTRIBUTION_WEIGHT * max(0.0, contribution)
        - TOXICITY_PENALTY * toxicity
        - SEMANTIC_LOSS_PENALTY * semantic_loss
        - BROKEN_SAMPLE_PENALTY_PER_COUNT * broken_penalty
    )
    decision.compression_score = _unit(raw_score)

    # ------------------------------------------------------------------
    # Safety gates (priority order).
    # ------------------------------------------------------------------

    accepted_so_far = True
    rejection_reason: str | None = None

    if decision.candidate_sample_count == 0:
        accepted_so_far = False
        rejection_reason = rejection_reason or "NO_BEHAVIOR_SAMPLES"
        decision.reasons.append("no_behavior_samples")

    if decision.toxicity_risk >= HIGH_TOXICITY_THRESHOLD:
        accepted_so_far = False
        rejection_reason = rejection_reason or "HIGH_TOXICITY_RISK"
        decision.reasons.append("high_toxicity_risk")

    if decision.risk_score >= HIGH_RISK_THRESHOLD:
        accepted_so_far = False
        rejection_reason = rejection_reason or "HIGH_RISK_SECTION"
        decision.reasons.append("high_risk_section")

    if decision.semantic_loss_risk >= SEVERE_SEMANTIC_LOSS_THRESHOLD:
        accepted_so_far = False
        rejection_reason = rejection_reason or "SEVERE_SEMANTIC_LOSS_RISK"
        decision.reasons.append("severe_semantic_loss_risk")

    if decision.contribution_delta <= LARGE_NEGATIVE_CONTRIBUTION_THRESHOLD:
        accepted_so_far = False
        rejection_reason = rejection_reason or "LARGE_NEGATIVE_CONTRIBUTION"
        decision.reasons.append("large_negative_contribution")

    if decision.broken_sample_count > 0 and decision.contribution_delta <= 0.0:
        accepted_so_far = False
        rejection_reason = rejection_reason or "BROKEN_SAMPLES_WITHOUT_IMPROVEMENT"
        decision.reasons.append("broken_samples_without_improvement")

    decision.accepted = accepted_so_far
    decision.rejection_reason = rejection_reason

    if accepted_so_far and not decision.reasons:
        decision.reasons.append("accepted")

    return decision


# ---------------------------------------------------------------------------
# Safety gate predicate (helper for callers who only want accept/reject)
# ---------------------------------------------------------------------------


def should_accept_compression(
    candidate: CompressionDecision | Mapping[str, Any],
) -> tuple[bool, str | None]:
    """Return ``(accepted, rejection_reason)`` without computing a full score.

    This is a lightweight helper that only walks the safety gate rules. It
    is convenient for callers that want a quick accept/reject decision
    without the full scoring path.
    """

    scored = score_compression_candidate(candidate)
    return scored.accepted, scored.rejection_reason


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def rank_compression_candidates(
    candidates: Iterable[CompressionDecision | Mapping[str, Any]],
    *,
    score_first: bool = True,
) -> list[CompressionDecision]:
    """Return a ranked list of compression candidates.

    Ranking is deterministic with key
    ``(-compression_score, section_id asc, candidate_id asc)``.
    When ``score_first`` is ``True`` each candidate is passed through
    :func:`score_compression_candidate` before ranking (the inputs are not
    mutated). When ``False`` the existing ``compression_score`` fields are
    used verbatim.
    """

    scored: list[CompressionDecision] = []
    for candidate in candidates:
        if score_first:
            scored.append(score_compression_candidate(candidate))
        elif isinstance(candidate, CompressionDecision):
            scored.append(CompressionDecision(**candidate.to_dict()))
        else:
            scored.append(
                CompressionDecision(
                    candidate_id=str(candidate.get("candidate_id", "")),
                    section_id=str(candidate.get("section_id", "")),
                    compression_ratio=float(candidate.get("compression_ratio", 0.0)),
                    contribution_delta=float(candidate.get("contribution_delta", 0.0)),
                    risk_score=float(candidate.get("risk_score", 0.0)),
                    toxicity_risk=float(candidate.get("toxicity_risk", 0.0)),
                    broken_sample_count=int(candidate.get("broken_sample_count", 0)),
                    semantic_loss_risk=float(candidate.get("semantic_loss_risk", 0.0)),
                    candidate_sample_count=int(candidate.get("candidate_sample_count", 0)),
                    compression_score=float(candidate.get("compression_score", 0.0)),
                    accepted=bool(candidate.get("accepted", False)),
                    rejection_reason=candidate.get("rejection_reason"),
                    reasons=list(candidate.get("reasons", ())),
                    metadata=dict(candidate.get("metadata", {})),
                )
            )

    scored.sort(
        key=lambda d: (-d.compression_score, d.section_id, d.candidate_id)
    )
    return scored


def select_top_compression_candidates(
    candidates: Iterable[CompressionDecision | Mapping[str, Any]],
    max_candidates: int,
    *,
    accepted_only: bool = True,
    score_first: bool = True,
) -> list[CompressionDecision]:
    """Return the top ``max_candidates`` ranked candidates.

    When ``accepted_only`` is ``True`` (default) only candidates that pass
    the safety gate are returned. Set it to ``False`` to include rejected
    candidates (for debugging / audit reports that compare decisions).
    """

    if max_candidates <= 0:
        return []

    ranked = rank_compression_candidates(candidates, score_first=score_first)
    if accepted_only:
        ranked = [decision for decision in ranked if decision.accepted]
    return ranked[: int(max_candidates)]


# ---------------------------------------------------------------------------
# Convenience: build candidates from section-level inputs
# ---------------------------------------------------------------------------


def build_compression_candidates_from_sections(
    sections: Iterable[Mapping[str, Any]],
    *,
    section_contributions: Mapping[str, float] | None = None,
    risk_signals: Mapping[str, float] | None = None,
) -> list[CompressionDecision]:
    """Build scored :class:`CompressionDecision` records from section dicts.

    ``sections`` is an iterable of plain dicts, typically with keys
    ``section_id``, ``line_count_before``, ``line_count_after``,
    ``candidate_id`` (optional, defaults to ``compression_{section_id}``),
    ``toxicity_risk`` (optional, default ``0.0``), ``broken_sample_count``
    (optional, default ``0``), ``semantic_loss_risk`` (optional, default
    ``0.0``), ``candidate_sample_count`` (optional, default ``0``), and
    ``metadata`` (optional).

    ``section_contributions`` maps ``section_id`` to a ``contribution_delta``
    (typically from the section contribution metrics helpers). Missing
    sections default to ``0.0``.

    ``risk_signals`` maps ``section_id`` to a ``risk_score`` in ``[0, 1]``
    (typically from the risk signals helpers). Missing sections default to
    ``0.0``.
    """

    contributions = section_contributions or {}
    risks = risk_signals or {}
    results: list[CompressionDecision] = []

    for section in sections:
        section_id = str(section.get("section_id", ""))
        candidate_id = str(
            section.get("candidate_id") or f"compression_{section_id}"
        )
        before = max(0, int(section.get("line_count_before", 0)))
        after = max(0, int(section.get("line_count_after", before)))
        if before > 0:
            ratio = 1.0 - (float(after) / float(before))
        else:
            ratio = 0.0
        ratio = _unit(ratio)

        delta = float(
            section.get("contribution_delta", contributions.get(section_id, 0.0))
        )
        risk = float(section.get("risk_score", risks.get(section_id, 0.0)))
        toxicity = float(section.get("toxicity_risk", 0.0))
        broken = int(section.get("broken_sample_count", 0))
        semantic_loss = float(section.get("semantic_loss_risk", 0.0))
        sample_count = int(section.get("candidate_sample_count", 0))
        metadata = dict(section.get("metadata", {}))
        if "compressibility" in section:
            metadata["compressibility"] = section["compressibility"]
        if "priority" in section:
            metadata["priority"] = section["priority"]

        base = CompressionDecision(
            candidate_id=candidate_id,
            section_id=section_id,
            compression_ratio=ratio,
            contribution_delta=delta,
            risk_score=risk,
            toxicity_risk=toxicity,
            broken_sample_count=broken,
            semantic_loss_risk=semantic_loss,
            candidate_sample_count=sample_count,
            metadata=metadata,
        )
        results.append(score_compression_candidate(base))

    return results


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def compression_decision_to_dict(decision: CompressionDecision) -> dict[str, Any]:
    """Return a JSON-safe dictionary copy of ``decision``."""

    return decision.to_dict()


def compression_decisions_to_json(
    decisions: Iterable[CompressionDecision],
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> str:
    """Serialize a list of decisions to a JSON string."""

    payload = [decision.to_dict() for decision in decisions]
    return json.dumps(payload, indent=indent, sort_keys=sort_keys)


def write_compression_report(
    decisions: Iterable[CompressionDecision],
    output_path: Any,
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> str:
    """Write decisions to ``output_path`` as a JSON report.

    Returns the output path string (converted from a ``pathlib.Path`` when
    applicable) so callers can log or further inspect it.
    """

    from pathlib import Path

    path = Path(str(output_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        compression_decisions_to_json(decisions, indent=indent, sort_keys=sort_keys),
        encoding="utf-8",
    )
    return str(path)
