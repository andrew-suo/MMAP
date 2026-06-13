"""Patch generation runner context assembly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mmap_optimizer.metrics.section_contribution import SectionContributionEMAStore, high_risk_section_ranking


class PatchGenerationRunner:
    """Builds patch-generation inputs with high-risk section rankings."""

    def __init__(self, run_dir: str | Path | None = None, *, high_risk_limit: int = 10) -> None:
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.high_risk_limit = high_risk_limit

    def build_input_context(self, base_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        context = dict(base_context or {})
        context["high_risk_sections"] = self._high_risk_sections(context)
        return context

    def _high_risk_sections(self, context: Mapping[str, Any]) -> list[dict[str, Any]]:
        if "section_contributions" in context:
            return high_risk_section_ranking(context["section_contributions"], limit=self.high_risk_limit)
        if self.run_dir is None:
            return []
        return SectionContributionEMAStore(self.run_dir).rankings(limit=self.high_risk_limit)
