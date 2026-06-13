"""Prompt artifact data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from mmap_optimizer.metrics.section_contribution import SectionContribution, SectionContributionEMAStore


@dataclass
class PromptSection:
    """A section in a prompt artifact.

    ``metrics`` carries section contribution telemetry so prompt artifacts remain
    self-describing when inspected outside the optimizer run directory.
    """

    section_id: str
    content: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def attach_contribution(self, contribution: SectionContribution | Mapping[str, Any]) -> None:
        if isinstance(contribution, SectionContribution):
            payload = contribution.to_json()
        else:
            payload = dict(contribution)
        self.metrics["section_contribution"] = payload
        self.metrics["section_score"] = payload.get("ema_score", payload.get("score"))
        self.metrics["section_risk_score"] = payload.get("risk_score")


def attach_section_scores(
    sections: list[PromptSection],
    contributions: Mapping[str, SectionContribution | Mapping[str, Any]] | SectionContributionEMAStore,
) -> list[PromptSection]:
    """Attach contribution metrics to matching prompt sections."""

    for section in sections:
        if isinstance(contributions, SectionContributionEMAStore):
            metrics = contributions.metrics_for(section.section_id)
        else:
            value = contributions.get(section.section_id)
            metrics = value.to_json() if isinstance(value, SectionContribution) else dict(value or {})
        if metrics:
            section.attach_contribution(metrics)
    return sections
