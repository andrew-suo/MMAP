"""Aggregate and apply section-level contribution metrics.

The optimizer receives signal from several report types:

* patch test results: fixes, regressions, toxicity findings and accepted patches;
* compression reports: accepted/rejected compression candidates;
* few-shot reports: prompt-section activity observed while evaluating examples.

This module normalizes those heterogeneous records into one metrics payload per prompt
section.  Callers can either write the payload back to ``PromptSection.metrics`` or
persist it as a standalone ``section_contribution.json`` artifact.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


SECTION_CONTRIBUTION_ARTIFACT = "section_contribution.json"


@dataclass
class SectionContributionMetrics:
    """Contribution metrics accumulated for one prompt section."""

    fixed_count: int = 0
    broken_count: int = 0
    net_gain: int = 0
    toxicity_count: int = 0
    patch_accept_rate: float = 0.0
    compression_reject_rate: float = 0.0
    recent_activity: float = 0.0
    contribution_weight: float = 1.0
    patch_total: int = field(default=0, repr=False)
    patch_accepted: int = field(default=0, repr=False)
    compression_total: int = field(default=0, repr=False)
    compression_rejected: int = field(default=0, repr=False)

    def finalize(self) -> "SectionContributionMetrics":
        """Calculate derived rates, net gain and final contribution weight."""

        self.net_gain = self.fixed_count - self.broken_count
        self.patch_accept_rate = _safe_rate(self.patch_accepted, self.patch_total)
        self.compression_reject_rate = _safe_rate(
            self.compression_rejected, self.compression_total
        )
        self.contribution_weight = calculate_section_contribution_weight(self)
        return self

    def public_dict(self) -> dict[str, int | float]:
        """Return the JSON-safe public metric fields requested by downstream code."""

        payload = asdict(self)
        payload.pop("patch_total", None)
        payload.pop("patch_accepted", None)
        payload.pop("compression_total", None)
        payload.pop("compression_rejected", None)
        return payload


def aggregate_section_contributions(
    *,
    patch_test_results: Iterable[Mapping[str, Any]] | None = None,
    compression_reports: Iterable[Mapping[str, Any]] | None = None,
    few_shot_reports: Iterable[Mapping[str, Any]] | None = None,
    prompt_sections: Iterable[Any] | None = None,
    write_back_to_prompt_sections: bool = True,
    now: datetime | None = None,
) -> dict[str, dict[str, int | float]]:
    """Aggregate section-level metrics from optimizer reports.

    Report records are intentionally accepted as loose mappings so this function can
    consume existing JSON reports without requiring a schema migration.  Section IDs
    are read from common keys such as ``section_id``, ``section_ids`` and
    ``prompt_section_id``.  Count fields can be explicit integers or sample lists
    (for example ``fixed_samples`` or ``broken_samples``).

    When ``prompt_sections`` are provided, each section object's ``metrics`` mapping
    is updated with the aggregated metrics for its ``id``/``section_id``.  This keeps
    compatibility with pipelines that persist metrics on ``PromptSection`` directly.
    """

    clock = now or datetime.now(timezone.utc)
    by_section: dict[str, SectionContributionMetrics] = {}

    for record in patch_test_results or ():
        section_ids = _section_ids(record)
        for section_id in section_ids:
            metrics = _ensure(by_section, section_id)
            fixed_count = _count_from(record, "fixed_count", "fixed_samples", "fixes")
            broken_count = _count_from(record, "broken_count", "broken_samples", "breakages")
            toxicity_count = _count_from(
                record, "toxicity_count", "toxic_count", "toxic_patches", "toxicity"
            )
            metrics.fixed_count += fixed_count
            metrics.broken_count += broken_count
            metrics.toxicity_count += toxicity_count
            metrics.patch_total += max(
                1 if _has_patch_signal(record) else 0,
                fixed_count + broken_count + toxicity_count,
            )
            if _truthy_status(record, "accepted", "accept", "merged"):
                metrics.patch_accepted += 1
            elif record.get("status") in {"accepted", "merged", "pass", "passed"}:
                metrics.patch_accepted += 1
            metrics.recent_activity += _recent_activity(record, clock)

    for record in compression_reports or ():
        section_ids = _section_ids(record)
        for section_id in section_ids:
            metrics = _ensure(by_section, section_id)
            metrics.compression_total += 1
            if _is_rejected(record):
                metrics.compression_rejected += 1
            metrics.recent_activity += _recent_activity(record, clock)

    for record in few_shot_reports or ():
        section_ids = _section_ids(record)
        for section_id in section_ids:
            metrics = _ensure(by_section, section_id)
            metrics.fixed_count += _count_from(record, "fixed_count", "fixed_samples", "successes")
            metrics.broken_count += _count_from(record, "broken_count", "broken_samples", "failures")
            metrics.toxicity_count += _count_from(record, "toxicity_count", "toxic_count", "toxicity")
            metrics.recent_activity += _recent_activity(record, clock)

    finalized = {
        section_id: metrics.finalize().public_dict()
        for section_id, metrics in sorted(by_section.items())
    }

    if prompt_sections and write_back_to_prompt_sections:
        write_metrics_to_prompt_sections(prompt_sections, finalized)

    return finalized


def write_metrics_to_prompt_sections(
    prompt_sections: Iterable[Any], section_metrics: Mapping[str, Mapping[str, Any]]
) -> None:
    """Merge aggregated metrics into each ``PromptSection.metrics`` mapping."""

    for section in prompt_sections:
        section_id = _section_id_from_object(section)
        if section_id is None or section_id not in section_metrics:
            continue
        current_metrics = getattr(section, "metrics", None)
        if current_metrics is None:
            setattr(section, "metrics", dict(section_metrics[section_id]))
        elif isinstance(current_metrics, MutableMapping):
            current_metrics.update(section_metrics[section_id])
        else:
            setattr(section, "metrics", dict(section_metrics[section_id]))


def write_section_contribution_artifact(
    section_metrics: Mapping[str, Mapping[str, Any]],
    output_dir: str | Path,
    *,
    filename: str = SECTION_CONTRIBUTION_ARTIFACT,
) -> Path:
    """Write aggregated metrics as ``section_contribution.json`` and return its path."""

    path = Path(output_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(section_metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def calculate_section_contribution_weight(
    metrics: SectionContributionMetrics | Mapping[str, Any],
) -> float:
    """Calculate a bounded section contribution weight.

    Positive evidence (fixes, patch acceptance, and recent activity) increases the
    weight.  Negative evidence (broken samples, toxicity and compression rejection)
    decreases it.  The exponential form keeps the score monotonic while the final
    clamp prevents one noisy section from dominating patch merge or compression
    ranking decisions.
    """

    value = _get_metric(metrics, "net_gain")
    if value == 0:
        value = _get_metric(metrics, "fixed_count") - _get_metric(metrics, "broken_count")

    signal = (
        0.35 * value
        + 0.8 * _get_metric(metrics, "patch_accept_rate")
        - 0.7 * _get_metric(metrics, "toxicity_count")
        - 0.8 * _get_metric(metrics, "compression_reject_rate")
        + 0.05 * _get_metric(metrics, "recent_activity")
    )
    return round(min(3.0, max(0.1, math.exp(signal / 3.0))), 4)


def score_patch_merge_candidate(
    candidate: Mapping[str, Any],
    section_metrics: Mapping[str, Mapping[str, Any]],
    *,
    base_score_key: str = "score",
) -> float:
    """Score a patch merge candidate using section contribution weight."""

    base_score = float(candidate.get(base_score_key, candidate.get("base_score", 1.0)))
    return round(base_score * _average_section_weight(candidate, section_metrics), 6)


def rank_compression_candidates(
    candidates: Sequence[Mapping[str, Any]],
    section_metrics: Mapping[str, Mapping[str, Any]],
    *,
    base_score_key: str = "score",
) -> list[dict[str, Any]]:
    """Rank compression candidates with section contribution and rejection risk.

    The returned dictionaries include ``section_contribution_weight`` and
    ``weighted_score`` so callers can inspect why a candidate moved up or down.
    """

    ranked: list[dict[str, Any]] = []
    for candidate in candidates:
        contribution_weight = _average_section_weight(candidate, section_metrics)
        reject_rate = _average_metric(candidate, section_metrics, "compression_reject_rate")
        base_score = float(candidate.get(base_score_key, candidate.get("base_score", 1.0)))
        weighted_score = round(base_score * contribution_weight * (1.0 - reject_rate), 6)
        enriched = dict(candidate)
        enriched["section_contribution_weight"] = contribution_weight
        enriched["weighted_score"] = weighted_score
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: item["weighted_score"], reverse=True)


def _ensure(
    by_section: dict[str, SectionContributionMetrics], section_id: str
) -> SectionContributionMetrics:
    if section_id not in by_section:
        by_section[section_id] = SectionContributionMetrics()
    return by_section[section_id]


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _section_ids(record: Mapping[str, Any]) -> list[str]:
    for key in (
        "section_ids",
        "sections",
        "prompt_section_ids",
        "affected_sections",
        "source_sections",
    ):
        value = record.get(key)
        if value:
            if isinstance(value, str):
                return [value]
            return [str(item) for item in value]

    for key in ("section_id", "section", "prompt_section_id", "source_section"):
        value = record.get(key)
        if value is not None:
            return [str(value)]
    return []


def _section_id_from_object(section: Any) -> str | None:
    if isinstance(section, Mapping):
        for key in ("id", "section_id", "name"):
            if section.get(key) is not None:
                return str(section[key])
        return None
    for key in ("id", "section_id", "name"):
        if hasattr(section, key):
            value = getattr(section, key)
            if value is not None:
                return str(value)
    return None


def _count_from(record: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, (list, tuple, set, dict)):
            return len(value)
    return 0


def _truthy_status(record: Mapping[str, Any], *keys: str) -> bool:
    return any(bool(record.get(key)) for key in keys)


def _has_patch_signal(record: Mapping[str, Any]) -> bool:
    return any(
        key in record
        for key in (
            "accepted",
            "accept",
            "merged",
            "status",
            "fixed_count",
            "fixed_samples",
            "broken_count",
            "broken_samples",
            "toxicity_count",
            "toxic_count",
        )
    )


def _is_rejected(record: Mapping[str, Any]) -> bool:
    if _truthy_status(record, "rejected", "reject"):
        return True
    return record.get("status") in {"rejected", "reject", "failed", "blocked"}


def _recent_activity(record: Mapping[str, Any], now: datetime) -> float:
    timestamp = record.get("timestamp") or record.get("created_at") or record.get("updated_at")
    if timestamp is None:
        return 1.0
    observed_at = _parse_datetime(timestamp)
    if observed_at is None:
        return 1.0
    age_days = max(0.0, (now - observed_at).total_seconds() / 86_400)
    return round(math.exp(-age_days / 14.0), 6)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _get_metric(metrics: SectionContributionMetrics | Mapping[str, Any], key: str) -> float:
    if isinstance(metrics, SectionContributionMetrics):
        return float(getattr(metrics, key))
    return float(metrics.get(key, 0.0) or 0.0)


def _average_section_weight(
    candidate: Mapping[str, Any], section_metrics: Mapping[str, Mapping[str, Any]]
) -> float:
    section_ids = _section_ids(candidate)
    if not section_ids:
        return 1.0
    weights = [
        calculate_section_contribution_weight(section_metrics.get(section_id, {}))
        for section_id in section_ids
    ]
    return round(sum(weights) / len(weights), 6)


def _average_metric(
    candidate: Mapping[str, Any],
    section_metrics: Mapping[str, Mapping[str, Any]],
    metric_name: str,
) -> float:
    section_ids = _section_ids(candidate)
    if not section_ids:
        return 0.0
    values = [float(section_metrics.get(section_id, {}).get(metric_name, 0.0)) for section_id in section_ids]
    return sum(values) / len(values)
