"""Risk-aware patch merge candidate ranking and selection helpers.

This module exposes lightweight pure-function helpers for scoring, ranking,
and selecting patch merge candidates based on:

* section contribution deltas (from :mod:`mmap_optimizer.metrics.section_deltas`)
* risk signals (from :mod:`mmap_optimizer.sampling.risk_signals`)
* explicit conflict counts
* side-effect signals

The helpers are intentionally decoupled from the default optimizer pipeline,
compression, and any existing merge implementation. They do not modify
:class:`~mmap_optimizer.patch.schema.Patch` objects and do not change the
default behavior of :class:`~mmap_optimizer.patch.applier.PatchApplier` or
:class:`~mmap_optimizer.patch.validator.PatchValidator`.

Design notes:

* ``merge_score`` is a bounded composite combining positive contributions
  (section improvement) with negative risk signals (risk score, conflicts,
  side effects, repair_needed).
* Ranking is fully deterministic: ``merge_score`` desc, ``risk_score`` asc,
  ``section_id`` ASCII, ``patch_id`` ASCII.
* The helpers accept either object-style or dict-style inputs for maximum
  compatibility with callers that build candidates procedurally.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class PatchMergeCandidate:
    """Risk-aware merge candidate score record.

    ``merge_score`` is the composite ranking score. All other fields are
    inputs or derived metadata useful for auditing.
    """

    patch_id: str
    section_id: str
    risk_score: float = 0.0
    contribution_delta: float = 0.0
    conflict_count: int = 0
    side_effect_risk: float = 0.0
    repair_needed: bool = False
    merge_score: float = 0.0
    rank: int = 0
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary copy of this record."""

        return {
            "patch_id": self.patch_id,
            "section_id": self.section_id,
            "risk_score": round(float(self.risk_score), 6),
            "contribution_delta": round(float(self.contribution_delta), 6),
            "conflict_count": int(self.conflict_count),
            "side_effect_risk": round(float(self.side_effect_risk), 6),
            "repair_needed": bool(self.repair_needed),
            "merge_score": round(float(self.merge_score), 6),
            "rank": int(self.rank),
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

_CONTRIBUTION_WEIGHT = 0.50
_RISK_WEIGHT = 0.30
_CONFLICT_WEIGHT = 0.20
_SIDE_EFFECT_WEIGHT = 0.15
_REPAIR_PENALTY = 0.25


def score_patch_merge_candidate(
    candidate: PatchMergeCandidate | Mapping[str, Any],
) -> PatchMergeCandidate:
    """Return a scored copy of ``candidate``.

    The input object is not mutated — fields are copied into a new
    :class:`PatchMergeCandidate`. If the input is a ``Mapping``, keys are
    case-sensitive and match the dataclass field names.
    """

    if isinstance(candidate, PatchMergeCandidate):
        patch_id = candidate.patch_id
        section_id = candidate.section_id
        risk_score = float(candidate.risk_score)
        contribution_delta = float(candidate.contribution_delta)
        conflict_count = int(candidate.conflict_count)
        side_effect_risk = float(candidate.side_effect_risk)
        repair_needed = bool(candidate.repair_needed)
        reasons = list(candidate.reasons)
        metadata = dict(candidate.metadata)
    else:
        patch_id = str(candidate.get("patch_id", ""))
        section_id = str(candidate.get("section_id", ""))
        risk_score = float(candidate.get("risk_score", 0.0))
        contribution_delta = float(candidate.get("contribution_delta", 0.0))
        conflict_count = int(candidate.get("conflict_count", 0))
        side_effect_risk = float(candidate.get("side_effect_risk", 0.0))
        repair_needed = bool(candidate.get("repair_needed", False))
        reasons = list(candidate.get("reasons", ()))
        metadata = dict(candidate.get("metadata", {}))

    # Clamp auxiliary signals to [0, 1] for predictable weighting.
    risk_score_clamped = max(0.0, min(1.0, risk_score))
    side_effect_clamped = max(0.0, min(1.0, side_effect_risk))
    conflict_penalty = min(float(conflict_count) * 0.1, 1.0)

    reasons_out: list[str] = list(reasons)
    if contribution_delta > 0:
        reasons_out.append("positive_section_contribution")
    if risk_score_clamped > 0.5:
        reasons_out.append("high_sample_risk")
    if conflict_count > 0:
        reasons_out.append("conflicts_detected")
    if side_effect_risk > 0.3:
        reasons_out.append("side_effect_risk")
    if repair_needed:
        reasons_out.append("repair_needed")

    merge_score = (
        _CONTRIBUTION_WEIGHT * contribution_delta
        - _RISK_WEIGHT * risk_score_clamped
        - _CONFLICT_WEIGHT * conflict_penalty
        - _SIDE_EFFECT_WEIGHT * side_effect_clamped
        - (_REPAIR_PENALTY if repair_needed else 0.0)
    )

    return PatchMergeCandidate(
        patch_id=patch_id,
        section_id=section_id,
        risk_score=risk_score_clamped,
        contribution_delta=contribution_delta,
        conflict_count=conflict_count,
        side_effect_risk=side_effect_clamped,
        repair_needed=repair_needed,
        merge_score=round(merge_score, 6),
        rank=0,
        reasons=reasons_out,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Ranking / selection
# ---------------------------------------------------------------------------


def rank_patch_merge_candidates(
    candidates: Iterable[PatchMergeCandidate | Mapping[str, Any]],
    *,
    score_first: bool = True,
) -> list[PatchMergeCandidate]:
    """Return a ranked, fresh list of merge candidates.

    Ranking is deterministic and never mutates the inputs. The primary key is
    ``-merge_score`` (higher score wins). Ties are broken first by lower
    ``risk_score``, then by ``section_id`` ASCII order, then by
    ``patch_id`` ASCII order.

    ``score_first`` controls whether candidates are scored before ranking.
    When it is ``False``, the existing ``merge_score`` on each candidate is
    used verbatim (candidates must already be scored or have explicit scores
    set by the caller).
    """

    scored: list[PatchMergeCandidate] = []
    for candidate in candidates:
        if score_first and isinstance(candidate, PatchMergeCandidate):
            scored.append(score_patch_merge_candidate(candidate))
        elif score_first:
            scored.append(score_patch_merge_candidate(candidate))
        else:
            if isinstance(candidate, PatchMergeCandidate):
                scored.append(PatchMergeCandidate(**candidate.to_dict()))
            else:
                scored.append(
                    PatchMergeCandidate(
                        patch_id=str(candidate.get("patch_id", "")),
                        section_id=str(candidate.get("section_id", "")),
                        risk_score=float(candidate.get("risk_score", 0.0)),
                        contribution_delta=float(
                            candidate.get("contribution_delta", 0.0)
                        ),
                        conflict_count=int(candidate.get("conflict_count", 0)),
                        side_effect_risk=float(
                            candidate.get("side_effect_risk", 0.0)
                        ),
                        repair_needed=bool(candidate.get("repair_needed", False)),
                        merge_score=float(candidate.get("merge_score", 0.0)),
                        reasons=list(candidate.get("reasons", ())),
                        metadata=dict(candidate.get("metadata", {})),
                    )
                )

    scored.sort(
        key=lambda c: (
            -c.merge_score,
            c.risk_score,
            c.section_id,
            c.patch_id,
        )
    )
    for rank, candidate in enumerate(scored, start=1):
        candidate.rank = rank
    return scored


def select_top_merge_candidates(
    candidates: Iterable[PatchMergeCandidate | Mapping[str, Any]],
    *,
    max_patches: int,
    score_first: bool = True,
) -> list[PatchMergeCandidate]:
    """Return the top-``max_patches`` candidates after scoring and ranking.

    ``max_patches <= 0`` returns an empty list. If fewer candidates exist than
    ``max_patches``, all are returned in rank order.
    """

    if max_patches <= 0:
        return []
    ranked = rank_patch_merge_candidates(candidates, score_first=score_first)
    return ranked[: int(max_patches)]


# ---------------------------------------------------------------------------
# Convenience: build candidates from patch objects
# ---------------------------------------------------------------------------


def build_merge_candidates_from_patches(
    patches: Iterable[Any],
    *,
    section_contributions: Mapping[str, float] | None = None,
    risk_signals: Mapping[str, float] | None = None,
    conflict_counts: Mapping[str, int] | None = None,
) -> list[PatchMergeCandidate]:
    """Build scored :class:`PatchMergeCandidate` records from patch objects.

    Each patch is expected to expose either attributes (``section_id``,
    ``risk_level``, ``possible_side_effects``) or matching dict keys. The
    patch identifier is taken from ``patch.id`` or ``patch['id']``.

    ``section_contributions`` maps ``section_id`` to a delta score (positive
    is improvement, negative is regression).
    ``risk_signals`` maps ``patch_id`` to a ``[0, 1]`` risk score.
    ``conflict_counts`` maps ``patch_id`` to the number of detected conflicts.

    Missing entries default to zero so the ranking remains stable even when
    some sections or samples lack external signals.
    """

    contributions = section_contributions or {}
    risks = risk_signals or {}
    conflicts = conflict_counts or {}

    candidates: list[PatchMergeCandidate] = []
    for patch in patches:
        patch_id = _attr(patch, "id", "").strip() or _attr(patch, "patch_id", "")
        section_id = _attr(patch, "section_id", "").strip()

        # Derive risk from explicit signal first, fall back to patch.risk_level.
        risk_score = float(risks.get(patch_id, risks.get(section_id, -1.0)))
        if risk_score < 0.0:
            risk_score = _risk_level_to_score(_attr(patch, "risk_level", "unknown"))

        side_effects = _attr(patch, "possible_side_effects", [])
        side_effect_risk = _side_effect_risk_from(side_effects)

        contribution_delta = float(
            contributions.get(section_id, contributions.get(patch_id, 0.0))
        )

        conflict_count = int(conflicts.get(patch_id, 0))
        repair_needed = risk_score >= 0.66 or conflict_count > 0

        candidates.append(
            PatchMergeCandidate(
                patch_id=str(patch_id),
                section_id=str(section_id),
                risk_score=float(risk_score),
                contribution_delta=float(contribution_delta),
                conflict_count=conflict_count,
                side_effect_risk=float(side_effect_risk),
                repair_needed=repair_needed,
            )
        )

    return candidates


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def merge_candidates_to_dict(
    candidates: Iterable[PatchMergeCandidate],
) -> dict[str, dict[str, Any]]:
    """Return a JSON-safe dictionary keyed by ``patch_id``."""

    return {candidate.patch_id: candidate.to_dict() for candidate in candidates}


def merge_candidates_to_json(
    candidates: Iterable[PatchMergeCandidate],
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> str:
    """Serialize candidates to a JSON string."""

    return json.dumps(merge_candidates_to_dict(candidates), indent=indent, sort_keys=sort_keys)


def write_merge_ranking_report(
    candidates: Iterable[PatchMergeCandidate],
    output_path: Any,
    *,
    indent: int = 2,
    sort_keys: bool = True,
) -> str:
    """Write merge ranking to ``output_path`` and return the path as string."""

    from pathlib import Path

    path = Path(str(output_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        merge_candidates_to_json(candidates, indent=indent, sort_keys=sort_keys),
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_RISK_LEVEL_MAP: dict[str, float] = {
    "unknown": 0.25,
    "low": 0.1,
    "medium": 0.35,
    "high": 0.7,
    "critical": 0.95,
}


def _risk_level_to_score(level: str) -> float:
    return _RISK_LEVEL_MAP.get(str(level).strip().lower(), 0.25)


def _side_effect_risk_from(side_effects: Any) -> float:
    if side_effects is None:
        return 0.0
    try:
        length = len(side_effects)
    except TypeError:
        return 0.0
    # Each side effect raises risk by 0.25, clamped to [0, 1].
    return min(float(length) * 0.25, 1.0)


def _attr(patch: Any, name: str, default: Any) -> Any:
    if isinstance(patch, Mapping):
        value = patch.get(name, default)
        return default if value is None else value
    value = getattr(patch, name, default)
    return default if value is None else value
