"""Per-section contribution deltas from before/after evaluation records.

Given two lists of :class:`~mmap_optimizer.evaluation.evaluator.EvaluationRecord`
(one representing the baseline, one representing the round after applying a patch
or set of patches), this module computes, for every prompt section referenced by
either list:

* the baseline accuracy and the new accuracy on the same sample population,
* the raw delta,
* the per-sample improvement / regression / unchanged counts,
* a stable contribution ``weight`` and a ``rank``.

This module is intentionally a *reporting helper* — it never drives sampling,
compression, merging or any other risk-aware optimizer loop decision.  Callers
may serialize the resulting records as a JSON artifact using the provided helpers.

Design notes:

* A prompt section is considered to have "moved" if any evaluation record that
  references it flips between ``primary_answer_correct`` and its opposite between
  baseline and new.  This keeps the signal coarse enough to be reliable without
  requiring a prompt-section attribution engine.
* The contribution ``weight`` is a bounded, monotonic function of the net
  evidence so noisy sections cannot dominate downstream ranking.
* Ties in ranking are broken by the (stable) ASCII sort of ``section_id`` so the
  helper produces deterministic output on identical inputs.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SECTION_CONTRIBUTION_ARTIFACT = "section_contribution.json"


@dataclass
class SectionContributionDelta:
    """Per-section contribution metrics accumulated from two record sets."""

    section_id: str
    baseline_score: float = 0.0
    new_score: float = 0.0
    delta: float = 0.0
    sample_count: int = 0
    improved_count: int = 0
    regressed_count: int = 0
    unchanged_count: int = 0
    weight: float = 1.0
    rank: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe dictionary copy of this record."""

        return asdict(self)


def _section_ids_from(record: Any) -> list[str]:
    """Extract section IDs from a record (dict or object)."""

    if isinstance(record, Mapping):
        sections = record.get("used_prompt_sections") or record.get(
            "prompt_sections", []
        )
    else:
        sections = getattr(record, "used_prompt_sections", None) or getattr(
            record, "prompt_sections", []
        )

    ids: list[str] = []
    for entry in sections or []:
        if isinstance(entry, Mapping):
            sid = entry.get("section_id") or entry.get("id") or entry.get("name")
            if sid is not None:
                ids.append(str(sid))
        elif isinstance(entry, str):
            ids.append(entry)

    # Fallback: if the record has a top-level section_id, include it so simple
    # callers can accumulate section metrics without full attribution data.
    if not ids:
        if isinstance(record, Mapping):
            sid = record.get("section_id")
        else:
            sid = getattr(record, "section_id", None)
        if sid is not None:
            ids.append(str(sid))

    return ids


def _correct(record: Any) -> bool:
    if isinstance(record, Mapping):
        return bool(record.get("primary_answer_correct")) or record.get(
            "overall_status"
        ) in {"correct", "CORRECT", "ok", "OK"}
    return bool(getattr(record, "primary_answer_correct", False))


def _sample_id(record: Any) -> str | None:
    if isinstance(record, Mapping):
        value = record.get("sample_id") or record.get("id")
        return str(value) if value is not None else None
    value = getattr(record, "sample_id", None) or getattr(record, "id", None)
    return str(value) if value is not None else None


def compute_section_deltas(
    baseline_records: Iterable[Any],
    new_records: Iterable[Any],
) -> dict[str, SectionContributionDelta]:
    """Compute per-section contribution metrics from two ordered record sets.

    ``baseline_records`` and ``new_records`` are iterables of either
    :class:`EvaluationRecord` objects or dictionaries with the same core
    fields.  Sample-level comparison uses the shared ``sample_id``; records
    without a ``sample_id`` still contribute to section-level totals but do
    not count as ``improved`` or ``regressed`` — they are reflected as
    ``unchanged`` so the weight signal still moves.

    Returns a mapping keyed by section ID.  The returned objects do not have
    their ``rank`` field populated; call :func:`rank_section_deltas` to assign
    ranks in a deterministic way.
    """

    baseline_list: list[Any] = list(baseline_records)
    new_list: list[Any] = list(new_records)

    baseline_by_sample: dict[str, Any] = {}
    new_by_sample: dict[str, Any] = {}
    for rec in baseline_list:
        sid = _sample_id(rec)
        if sid is not None:
            baseline_by_sample[sid] = rec
    for rec in new_list:
        sid = _sample_id(rec)
        if sid is not None:
            new_by_sample[sid] = rec

    # Per-section counters for matched (sample-id) records.
    baseline_correct_count: dict[str, int] = {}
    new_correct_count: dict[str, int] = {}
    baseline_total: dict[str, int] = {}
    new_total: dict[str, int] = {}
    improved: dict[str, int] = {}
    regressed: dict[str, int] = {}
    unchanged: dict[str, int] = {}
    observed_sections: set[str] = set()

    for sid in set(baseline_by_sample) | set(new_by_sample):
        base_rec = baseline_by_sample.get(sid)
        new_rec = new_by_sample.get(sid)
        sections = set()
        if base_rec is not None:
            sections.update(_section_ids_from(base_rec))
        if new_rec is not None:
            sections.update(_section_ids_from(new_rec))
        if not sections:
            continue
        observed_sections.update(sections)
        base_correct = _correct(base_rec) if base_rec is not None else None
        new_correct = _correct(new_rec) if new_rec is not None else None

        # Record as baseline-total if baseline record exists, new-total otherwise
        if base_rec is not None:
            for sec in sections:
                baseline_total[sec] = baseline_total.get(sec, 0) + 1
                if base_correct:
                    baseline_correct_count[sec] = baseline_correct_count.get(sec, 0) + 1
        if new_rec is not None:
            for sec in sections:
                new_total[sec] = new_total.get(sec, 0) + 1
                if new_correct:
                    new_correct_count[sec] = new_correct_count.get(sec, 0) + 1

        # Delta logic: only when both records exist for this sample_id.
        if base_rec is not None and new_rec is not None:
            if not base_correct and new_correct:
                for sec in sections:
                    improved[sec] = improved.get(sec, 0) + 1
            elif base_correct and not new_correct:
                for sec in sections:
                    regressed[sec] = regressed.get(sec, 0) + 1
            else:
                for sec in sections:
                    unchanged[sec] = unchanged.get(sec, 0) + 1

    result: dict[str, SectionContributionDelta] = {}
    for section_id in sorted(observed_sections):
        b_total = baseline_total.get(section_id, 0)
        n_total = new_total.get(section_id, 0)
        b_score = (baseline_correct_count.get(section_id, 0) / b_total) if b_total else 0.0
        n_score = (new_correct_count.get(section_id, 0) / n_total) if n_total else 0.0
        delta = n_score - b_score
        sample_count = max(b_total, n_total)
        imp = improved.get(section_id, 0)
        reg = regressed_count = regressed.get(section_id, 0)
        unc = unchanged.get(section_id, 0)
        weight = _calculate_section_contribution_weight(
            delta=delta,
            improved_count=imp,
            regressed_count=reg,
            sample_count=sample_count,
        )
        result[section_id] = SectionContributionDelta(
            section_id=section_id,
            baseline_score=_round6(b_score),
            new_score=_round6(n_score),
            delta=_round6(delta),
            sample_count=sample_count,
            improved_count=imp,
            regressed_count=reg,
            unchanged_count=unc,
            weight=weight,
            metadata={
                "baseline_total": b_total,
                "new_total": n_total,
            },
        )
    return result


def rank_section_deltas(
    deltas: Mapping[str, SectionContributionDelta] | Sequence[SectionContributionDelta],
    *,
    primary_key: str = "delta",
    weight_bonus: float = 0.01,
) -> list[SectionContributionDelta]:
    """Stable-rank section deltas from highest contribution to lowest.

    ``primary_key`` selects the primary ranking signal — either ``"delta"``
    (the default, ranks by accuracy movement) or ``"weight"`` (ranks by the
    composite weight).  A small ``weight_bonus`` is folded in so ties on the
    primary signal are broken deterministically by weight before falling back
    to the ASCII sort of ``section_id``.

    The returned list is a fresh list of new :class:`SectionContributionDelta`
    objects; the inputs are not mutated.
    """

    items: list[SectionContributionDelta] = []
    if isinstance(deltas, Mapping):
        for value in deltas.values():
            items.append(SectionContributionDelta(**value.to_dict()))
    else:
        for value in deltas:
            items.append(SectionContributionDelta(**value.to_dict()))

    if primary_key == "weight":
        items.sort(
            key=lambda item: (-item.weight, item.section_id),
        )
    elif primary_key == "delta_weight":
        items.sort(
            key=lambda item: (
                -(item.delta + weight_bonus * item.weight),
                item.section_id,
            ),
        )
    else:
        items.sort(
            key=lambda item: (-item.delta, item.section_id),
        )

    for rank, item in enumerate(items, start=1):
        item.rank = rank
    return items


def section_contributions_to_dict(
    deltas: Mapping[str, SectionContributionDelta] | Sequence[SectionContributionDelta],
) -> dict[str, dict[str, Any]]:
    """Convert delta records into a JSON-safe dictionary keyed by section_id."""

    if isinstance(deltas, Mapping):
        return {section_id: delta.to_dict() for section_id, delta in deltas.items()}
    return {delta.section_id: delta.to_dict() for delta in deltas}


def write_section_contribution_artifact(
    deltas: Mapping[str, SectionContributionDelta] | Sequence[SectionContributionDelta],
    output_dir: str | Path,
    *,
    filename: str = SECTION_CONTRIBUTION_ARTIFACT,
) -> Path:
    """Write delta records as ``section_contribution.json`` and return the path."""

    path = Path(output_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(section_contributions_to_dict(deltas), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def _calculate_section_contribution_weight(
    *,
    delta: float,
    improved_count: int,
    regressed_count: int,
    sample_count: int,
) -> float:
    """Bounded monotonic section contribution weight.

    Positive evidence increases the weight; negative evidence decreases it.
    The exponential form keeps the score monotonic while the final clamp
    prevents one noisy section from dominating ranking.
    """

    evidence = 0.5 * delta + 0.3 * improved_count - 0.6 * regressed_count
    # Sample count nudges the signal up to a small cap so sections with a few
    # samples still get meaningful weight but empty/zero-sample sections keep
    # the default 1.0 baseline.
    if sample_count:
        evidence += 0.05 * min(1.0, sample_count / 10.0)
    weight = math.exp(evidence / 3.0)
    return round(min(3.0, max(0.1, weight)), 4)


def _round6(value: float) -> float:
    return round(float(value), 6)
