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
    layer_reports: list = field(default_factory=list)      # 每层的报告（MergeLayerReport 列表）
    guardrail_detained_ids: list[str] = field(default_factory=list)  # 被 guardrail 拘留的 patch IDs
    root_merge_applied: bool = False                       # 是否应用了根合并
    fallback_applied: bool = False                         # 是否触发了全局回退
