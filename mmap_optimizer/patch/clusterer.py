from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .schema import Patch


@dataclass
class PatchCluster:
    id: str
    target_prompt_type: str
    section_id: str
    operation_type: str
    patch_ids: list[str] = field(default_factory=list)
    patches: list[Patch] = field(default_factory=list)


def cluster_patches(patches: list[Patch]) -> list[PatchCluster]:
    groups: dict[tuple[str, str, str], list[Patch]] = defaultdict(list)
    for patch in patches:
        groups[(patch.target_prompt_type, patch.section_id, patch.operation_type)].append(patch)
    clusters: list[PatchCluster] = []
    for (target_prompt_type, section_id, operation_type), group in sorted(groups.items()):
        cluster_id = f"cluster_{target_prompt_type}_{section_id}_{operation_type}"
        clusters.append(
            PatchCluster(
                id=cluster_id,
                target_prompt_type=target_prompt_type,
                section_id=section_id,
                operation_type=operation_type,
                patch_ids=[patch.id for patch in group],
                patches=group,
            )
        )
    return clusters
