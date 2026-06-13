"""Section-level contribution and risk tracking.

This module keeps a run-level exponential moving average (EMA) of section
contribution scores in ``section_contribution_ema.json``.  The EMA is keyed by
section id so downstream samplers, patch ranking, compression, and artifacts can
make stable decisions across optimizer rounds instead of overreacting to a
single noisy evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

EMA_FILENAME = "section_contribution_ema.json"
DEFAULT_EMA_ALPHA = 0.35


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SectionContribution:
    """Contribution telemetry for one prompt section.

    ``score`` is intentionally a net contribution signal: accurate cited usage
    increases it, parasite usage and inaccuracy decrease it.  Therefore a
    negative score is a sampling/ranking warning.  ``risk_score`` is a separate
    safety signal that specifically highlights sections that are frequently
    cited, have parasite behavior, and low measured accuracy.
    """

    section_id: str
    score: float
    cited: float = 0.0
    parasite: float = 0.0
    accuracy: float = 1.0
    ema_score: float | None = None
    risk_score: float | None = None
    samples: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metrics(
        cls,
        section_id: str,
        *,
        cited: float = 0.0,
        parasite: float = 0.0,
        accuracy: float = 1.0,
        samples: int = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> "SectionContribution":
        """Build contribution from normalized section metrics."""

        cited_n = _clamp(float(cited))
        parasite_n = _clamp(float(parasite))
        accuracy_n = _clamp(float(accuracy))
        score = (accuracy_n * cited_n) - parasite_n - (1.0 - accuracy_n)
        risk_score = compute_section_risk(cited_n, parasite_n, accuracy_n)
        return cls(
            section_id=section_id,
            score=score,
            cited=cited_n,
            parasite=parasite_n,
            accuracy=accuracy_n,
            risk_score=risk_score,
            samples=samples,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_mapping(cls, section_id: str, metrics: Mapping[str, Any]) -> "SectionContribution":
        if "score" in metrics:
            cited = float(metrics.get("cited", metrics.get("citation_rate", 0.0)))
            parasite = float(metrics.get("parasite", metrics.get("parasite_rate", 0.0)))
            accuracy = float(metrics.get("accuracy", 1.0))
            risk_score = float(metrics.get("risk_score", compute_section_risk(cited, parasite, accuracy)))
            return cls(
                section_id=section_id,
                score=float(metrics["score"]),
                cited=cited,
                parasite=parasite,
                accuracy=accuracy,
                ema_score=metrics.get("ema_score"),
                risk_score=risk_score,
                samples=int(metrics.get("samples", 1)),
                metadata=dict(metrics.get("metadata", {})),
            )
        return cls.from_metrics(
            section_id,
            cited=float(metrics.get("cited", metrics.get("citation_rate", 0.0))),
            parasite=float(metrics.get("parasite", metrics.get("parasite_rate", 0.0))),
            accuracy=float(metrics.get("accuracy", 1.0)),
            samples=int(metrics.get("samples", 1)),
            metadata=metrics.get("metadata", {}),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "score": self.score,
            "ema_score": self.ema_score if self.ema_score is not None else self.score,
            "risk_score": self.risk_score if self.risk_score is not None else compute_section_risk(self.cited, self.parasite, self.accuracy),
            "cited": self.cited,
            "parasite": self.parasite,
            "accuracy": self.accuracy,
            "samples": self.samples,
            "metadata": dict(self.metadata),
        }


def compute_section_risk(cited: float, parasite: float, accuracy: float) -> float:
    """Return risk for high-cited, high-parasite, low-accuracy sections."""

    cited_n = _clamp(float(cited))
    parasite_n = _clamp(float(parasite))
    accuracy_n = _clamp(float(accuracy))
    return (0.4 * cited_n) + (0.4 * parasite_n) + (0.2 * (1.0 - accuracy_n))


class SectionContributionEMAStore:
    """Persists cross-round section contribution EMA for one optimizer run."""

    def __init__(self, run_dir: str | Path, *, alpha: float = DEFAULT_EMA_ALPHA) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / EMA_FILENAME
        self.alpha = _clamp(alpha)
        self._data: dict[str, dict[str, Any]] = self.load()

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, Mapping)}

    def update(self, contributions: Iterable[SectionContribution | Mapping[str, Any]]) -> dict[str, SectionContribution]:
        updated: dict[str, SectionContribution] = {}
        for item in contributions:
            contribution = item if isinstance(item, SectionContribution) else SectionContribution.from_mapping(str(item["section_id"]), item)
            previous = self._data.get(contribution.section_id, {})
            previous_ema = float(previous.get("ema_score", contribution.score))
            ema_score = (self.alpha * contribution.score) + ((1.0 - self.alpha) * previous_ema)
            risk_score = contribution.risk_score if contribution.risk_score is not None else compute_section_risk(
                contribution.cited, contribution.parasite, contribution.accuracy
            )
            smoothed = SectionContribution(
                section_id=contribution.section_id,
                score=contribution.score,
                cited=contribution.cited,
                parasite=contribution.parasite,
                accuracy=contribution.accuracy,
                ema_score=ema_score,
                risk_score=risk_score,
                samples=contribution.samples + int(previous.get("samples", 0)),
                metadata=contribution.metadata,
            )
            self._data[contribution.section_id] = smoothed.to_json()
            updated[contribution.section_id] = smoothed
        self.save()
        return updated

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

    def rankings(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        ranked = sorted(
            self._data.values(),
            key=lambda row: (float(row.get("risk_score", 0.0)), -float(row.get("ema_score", 0.0))),
            reverse=True,
        )
        return ranked if limit is None else ranked[:limit]

    def metrics_for(self, section_id: str) -> dict[str, Any]:
        return dict(self._data.get(section_id, {}))


def update_section_contribution_ema(
    run_dir: str | Path,
    contributions: Iterable[SectionContribution | Mapping[str, Any]],
    *,
    alpha: float = DEFAULT_EMA_ALPHA,
) -> dict[str, SectionContribution]:
    """Update and persist run-level section contribution EMA."""

    return SectionContributionEMAStore(run_dir, alpha=alpha).update(contributions)


def high_risk_section_ranking(
    contributions: Mapping[str, Mapping[str, Any]] | Iterable[SectionContribution | Mapping[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank sections by risk, keeping negative EMA scores ahead on ties."""

    if isinstance(contributions, Mapping):
        rows = [dict(value, section_id=section_id) for section_id, value in contributions.items()]
    else:
        rows = [item.to_json() if isinstance(item, SectionContribution) else dict(item) for item in contributions]
    for row in rows:
        row.setdefault("risk_score", compute_section_risk(row.get("cited", 0.0), row.get("parasite", 0.0), row.get("accuracy", 1.0)))
        row.setdefault("ema_score", row.get("score", 0.0))
    rows.sort(key=lambda row: (float(row.get("risk_score", 0.0)), -float(row.get("ema_score", 0.0))), reverse=True)
    return rows[:limit]
