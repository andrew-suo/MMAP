from __future__ import annotations

from collections import defaultdict

from .schema import Patch


class PatchMerger:
    def merge(self, patches: list[Patch]) -> list[Patch]:
        groups: dict[tuple[str, str], list[Patch]] = defaultdict(list)
        for patch in patches:
            groups[(patch.section_id, patch.operation_type)].append(patch)
        merged: list[Patch] = []
        for (_, _), group in groups.items():
            if len(group) == 1:
                group[0].status = "merged"
                merged.append(group[0])
                continue
            first = group[0]
            merged_patch = Patch(
                id="merge_" + "_".join(p.id for p in group), type=first.type, status="merged",
                target_prompt_type=first.target_prompt_type, base_version_id=first.base_version_id, section_id=first.section_id,
                operation_type=first.operation_type, operation_mode="append", intent_name=first.intent_name,
                intent_description="Merged related patches", patch_text="\n".join(f"- {p.patch_text}" for p in group),
                rationale="Merged from: " + ", ".join(p.id for p in group),
                source_sample_ids=sorted({sid for p in group for sid in p.source_sample_ids}),
                source_analysis_ids=sorted({aid for p in group for aid in p.source_analysis_ids}),
                risk_level=max((p.risk_level for p in group), default="unknown"),
            )
            merged.append(merged_patch)
        return merged
