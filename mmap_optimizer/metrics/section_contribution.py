from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.analysis.record import AnalysisRecord
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.testing.patch_runner import PatchTestResult


@dataclass
class SectionContribution:
    section_id: str
    active_count: int = 0
    cited_count: int = 0
    parasite_count: int = 0
    fixed_count: int = 0
    broken_count: int = 0
    accepted_patch_count: int = 0
    rejected_patch_count: int = 0
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


def build_section_contribution(
    *,
    patches: list[Patch] | None = None,
    analysis_records: list[AnalysisRecord] | None = None,
    patch_results: list[PatchTestResult] | None = None,
) -> dict[str, SectionContribution]:
    by_section: dict[str, SectionContribution] = {}

    def get(section_id: str) -> SectionContribution:
        by_section.setdefault(section_id, SectionContribution(section_id=section_id))
        return by_section[section_id]

    for patch in patches or []:
        contribution = get(patch.section_id)
        if patch.status in {"accepted", "candidate", "merged", "superseded"}:
            contribution.active_count += 1
        if patch.status == "rejected" or patch.rejection_reason or patch.toxicity_result == "toxic":
            contribution.parasite_count += 1
            contribution.rejected_patch_count += 1
        else:
            contribution.accepted_patch_count += int(patch.status in {"accepted", "merged", "candidate"})
        contribution.fixed_count += len(patch.fixed_sample_ids)
        contribution.broken_count += len(patch.broken_sample_ids)

    for record in analysis_records or []:
        for attribution in record.prompt_section_attribution:
            if isinstance(attribution, dict):
                section_id = attribution.get("section_id") or attribution.get("target_section")
            else:
                section_id = str(attribution)
            if section_id:
                get(str(section_id)).cited_count += 1

    patch_by_id = {patch.id: patch for patch in patches or []}
    for result in patch_results or []:
        patch = patch_by_id.get(result.patch_id)
        if patch is None:
            continue
        contribution = get(patch.section_id)
        contribution.fixed_count += len(result.fixed_sample_ids)
        contribution.broken_count += len(result.broken_sample_ids)
        if result.toxicity_result == "toxic":
            contribution.parasite_count += 1

    for contribution in by_section.values():
        contribution.score = (
            contribution.active_count * 1.0
            + contribution.cited_count * 0.5
            + contribution.fixed_count * 2.0
            - contribution.broken_count * 3.0
            - contribution.parasite_count * 2.0
        )
        contribution.metadata = {
            "channels": {
                "active": contribution.active_count,
                "cited": contribution.cited_count,
                "parasite": contribution.parasite_count,
            }
        }
    return by_section
