from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.prompt.ir import PromptIR
from .clusterer import PatchCluster, cluster_patches
from .conflict import PatchConflict, detect_patch_conflicts
from .deduplicate import is_duplicate_patch, is_subsumed_patch, merge_trace, normalize_patch_text
from .merge_report import PatchMergeReport
from .schema import Patch

_RISK_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class TreeReduceMergeResult:
    final_patches: list[Patch]
    rejected_patches: list[Patch]
    merge_report: PatchMergeReport


class TreeReducePatchMerger:
    def merge(self, *, round_id: str, patches: list[Patch], prompt_ir: PromptIR | None = None) -> TreeReduceMergeResult:
        report = PatchMergeReport(id=f"patch_merge_{round_id}", round_id=round_id, input_patch_ids=[patch.id for patch in patches])
        final_patches: list[Patch] = []
        rejected_patches: list[Patch] = []
        clusters = cluster_patches(patches)
        report.cluster_count = len(clusters)
        for cluster in clusters:
            cluster_final, cluster_rejected, cluster_info = self._merge_cluster(round_id, cluster, prompt_ir)
            final_patches.extend(cluster_final)
            rejected_patches.extend(cluster_rejected)
            report.clusters.append(cluster_info)
            report.duplicate_patch_ids.extend(cluster_info.get("duplicate_patch_ids", []))
            report.subsumed_patch_ids.extend(cluster_info.get("subsumed_patch_ids", []))
            report.conflict_patch_ids.extend(cluster_info.get("conflict_patch_ids", []))
            report.merged_patch_ids.extend(cluster_info.get("merged_patch_ids", []))
        report.final_patch_ids = [patch.id for patch in final_patches]
        report.duplicate_patch_ids = sorted(set(report.duplicate_patch_ids))
        report.subsumed_patch_ids = sorted(set(report.subsumed_patch_ids))
        report.conflict_patch_ids = sorted(set(report.conflict_patch_ids))
        report.merged_patch_ids = sorted(set(report.merged_patch_ids))
        return TreeReduceMergeResult(final_patches=final_patches, rejected_patches=rejected_patches, merge_report=report)

    def _merge_cluster(self, round_id: str, cluster: PatchCluster, prompt_ir: PromptIR | None) -> tuple[list[Patch], list[Patch], dict]:
        info = {
            "cluster_id": cluster.id,
            "input_patch_ids": cluster.patch_ids,
            "output_patch_ids": [],
            "rejected_patch_ids": [],
            "duplicate_patch_ids": [],
            "subsumed_patch_ids": [],
            "conflict_patch_ids": [],
            "merged_patch_ids": [],
            "conflicts": [],
            "merge_operation": "tree_reduce",
        }
        conflicts = detect_patch_conflicts(cluster.patches, prompt_ir)
        conflict_ids = {patch_id for conflict in conflicts for patch_id in conflict.patch_ids}
        conflict_patches = [patch for patch in cluster.patches if patch.id in conflict_ids]
        for patch in conflict_patches:
            patch.status = "rejected"
            patch.rejection_reason = "PATCH_CONFLICT"
        non_conflict = [patch for patch in cluster.patches if patch.id not in conflict_ids]
        if conflicts:
            info["conflicts"] = [self._conflict_to_dict(conflict) for conflict in conflicts]
            info["conflict_patch_ids"] = sorted(conflict_ids)
            info["rejected_patch_ids"].extend(sorted(conflict_ids))

        reduced: list[Patch] = []
        for patch in non_conflict:
            duplicate_target = next((existing for existing in reduced if is_duplicate_patch(patch, existing)), None)
            if duplicate_target is not None:
                merge_trace(duplicate_target, patch)
                patch.status = "rejected"
                patch.rejection_reason = "DUPLICATE_PATCH"
                info["duplicate_patch_ids"].append(patch.id)
                info["rejected_patch_ids"].append(patch.id)
                continue
            subsuming_target = next((existing for existing in reduced if is_subsumed_patch(patch, existing)), None)
            if subsuming_target is not None:
                merge_trace(subsuming_target, patch)
                patch.status = "rejected"
                patch.rejection_reason = "SUBSUMED_PATCH"
                info["subsumed_patch_ids"].append(patch.id)
                info["rejected_patch_ids"].append(patch.id)
                continue
            subsumed_existing = [existing for existing in reduced if is_subsumed_patch(existing, patch)]
            for existing in subsumed_existing:
                merge_trace(patch, existing)
                reduced.remove(existing)
                existing.status = "rejected"
                existing.rejection_reason = "SUBSUMED_PATCH"
                info["subsumed_patch_ids"].append(existing.id)
                info["rejected_patch_ids"].append(existing.id)
            reduced.append(patch)

        if not reduced:
            return [], [*conflict_patches, *[patch for patch in non_conflict if patch.status == "rejected"]], info
        if len(reduced) == 1:
            reduced[0].status = "merged"
            info["output_patch_ids"].append(reduced[0].id)
            return [reduced[0]], [*conflict_patches, *[patch for patch in non_conflict if patch.status == "rejected"]], info

        merged_patch = self._merge_many(round_id, cluster, reduced)
        info["merged_patch_ids"].append(merged_patch.id)
        info["output_patch_ids"].append(merged_patch.id)
        return [merged_patch], [*conflict_patches, *[patch for patch in non_conflict if patch.status == "rejected"]], info

    def _merge_many(self, round_id: str, cluster: PatchCluster, patches: list[Patch]) -> Patch:
        first = patches[0]
        seen_texts: set[str] = set()
        text_lines = []
        for patch in patches:
            patch.status = "superseded"
            line = patch.patch_text.strip()
            # Deduplicate: skip patch_text that is identical after normalization
            normalized = normalize_patch_text(line)
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)
            text_lines.append(line if line.startswith("-") else f"- {line}")
        merged_id = f"merge_{round_id}_{cluster.target_prompt_type}_{cluster.section_id}_{cluster.operation_type}"
        return Patch(
            id=merged_id,
            type=first.type,
            status="merged",
            target_prompt_type=first.target_prompt_type,
            base_version_id=first.base_version_id,
            section_id=first.section_id,
            operation_type=first.operation_type,
            operation_mode="append",
            intent_name=f"merged_{cluster.section_id}_{cluster.operation_type}",
            intent_description="Tree-reduced related patches",
            patch_text="\n".join(text_lines),
            rationale="Tree-reduced from: " + ", ".join(patch.id for patch in patches),
            source_sample_ids=sorted({sid for patch in patches for sid in patch.source_sample_ids}),
            source_analysis_ids=sorted({aid for patch in patches for aid in patch.source_analysis_ids}),
            risk_level=max((patch.risk_level for patch in patches), key=lambda risk: _RISK_RANK.get(risk, 0), default="unknown"),
            possible_side_effects=sorted({effect for patch in patches for effect in patch.possible_side_effects}),
            extra={"merged_from_patch_ids": [patch.id for patch in patches]},
        )

    def _conflict_to_dict(self, conflict: PatchConflict) -> dict:
        return {
            "id": conflict.id,
            "patch_ids": conflict.patch_ids,
            "section_id": conflict.section_id,
            "conflict_type": conflict.conflict_type,
            "reason": conflict.reason,
        }
