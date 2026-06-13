from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PatchMergeReport:
    id: str
    round_id: str
    input_patch_ids: list[str] = field(default_factory=list)
    cluster_count: int = 0
    clusters: list[dict] = field(default_factory=list)
    duplicate_patch_ids: list[str] = field(default_factory=list)
    subsumed_patch_ids: list[str] = field(default_factory=list)
    conflict_patch_ids: list[str] = field(default_factory=list)
    merged_patch_ids: list[str] = field(default_factory=list)
    final_patch_ids: list[str] = field(default_factory=list)
