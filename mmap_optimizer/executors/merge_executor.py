"""MergeExecutor - Patch 合并执行器。

将多个 patch 合并为更少的 patch，支持 tree_merge / hierarchical_merge
策略，并在合并后通过 PatchValidator 进行校验。

tree_merge 策略复用老系统 ``TreeReducePatchMerger``，通过数据结构
转换将 ExtractionPatch / AnalysisPatch 映射为老系统 ``Patch``，合并
完成后再转回。当老系统不可用或合并抛异常时，回退到 passthrough
策略（原样返回输入 patch）。
"""

from __future__ import annotations

from typing import Any

from ..patch_types import AnalysisPatch, ExtractionPatch, PatchMergeReport
from ..sample import SampleSet
from ..structured_prompt import StructuredPrompt
from .patch_validator import PatchValidator

# 老系统导入：用 try/except 包裹，便于在老系统不可用时回退到 passthrough。
try:
    from ..patch.schema import Patch as _OldPatch
    from ..patch.tree_reduce import TreeReducePatchMerger as _TreeReducePatchMerger

    _OLD_SYSTEM_AVAILABLE = True
except Exception:  # pragma: no cover - 老系统缺失时的兜底分支
    _OldPatch = None  # type: ignore[assignment]
    _TreeReducePatchMerger = None  # type: ignore[assignment]
    _OLD_SYSTEM_AVAILABLE = False


class MergeExecutor:
    """Patch 合并执行器。

    支持的策略：
    - ``tree_merge``：调用老系统 ``TreeReducePatchMerger`` 进行去重/合并。
    - ``hierarchical_merge``：当前等价于 ``tree_merge``（占位实现）。
    - 任意策略失败时回退到 passthrough（原样返回输入 patch）。

    合并完成后，如果传入 ``sample_set``，会对 merged patches 跑一次
    ``PatchValidator.validate_batch``，校验失败的 patch 会被标记
    ``rejection_reason="MERGED_PATCH_VALIDATION_FAILED"``。
    """

    def __init__(self, patch_validator: PatchValidator | None = None) -> None:
        """初始化合并执行器。

        Args:
            patch_validator: 可选的 PatchValidator 实例。如果未提供，
                内部创建默认实例。
        """
        self.patch_validator = patch_validator or PatchValidator()

    def merge(
        self,
        patches: list,
        prompt: StructuredPrompt,
        merge_strategy: str = "tree_merge",
        sample_set: SampleSet | None = None,
    ) -> tuple[list, PatchMergeReport]:
        """合并 patch 列表。

        Args:
            patches: 待合并的 patch 列表（ExtractionPatch 或 AnalysisPatch）。
            prompt: 目标 StructuredPrompt，用于生成 round_id 和后置校验。
            merge_strategy: 合并策略，支持 ``tree_merge`` / ``hierarchical_merge``。
            sample_set: 可选的样本集合，提供时会在合并后做校验。

        Returns:
            (merged_patches, report) 元组。merged_patches 为合并后的 patch
            列表；report 记录合并过程的统计信息。
        """
        input_patch_ids = [getattr(p, "id", "") for p in patches]
        warnings: list[str] = []

        # 空输入快速返回
        if not patches:
            report = PatchMergeReport(
                id=f"merge_report_{prompt.id}",
                input_patch_count=0,
                merged_patch_count=0,
                conflict_count=0,
                strategy=merge_strategy,
                input_patch_ids=[],
                merged_patch_ids=[],
                dropped_patch_ids=[],
                conflict_patch_ids=[],
                merge_reason="empty input",
                fallback_used=False,
                warnings=["empty patch list"],
            )
            return [], report

        # 选择合并策略：hierarchical_merge 当前等价于 tree_merge
        effective_strategy = merge_strategy
        if merge_strategy == "hierarchical_merge":
            effective_strategy = "tree_merge"
            warnings.append(
                "hierarchical_merge falls back to tree_merge (placeholder)"
            )

        # 尝试 tree_merge
        merged_patches: list
        dropped_patches: list
        conflict_count: int
        conflict_patch_ids: list[str]
        conflicts: list[dict[str, Any]]
        fallback_used: bool = False
        merge_reason: str = ""

        if effective_strategy == "tree_merge" and _OLD_SYSTEM_AVAILABLE:
            try:
                merged_patches, dropped_patches, conflict_count, conflict_patch_ids, conflicts, merge_reason = (
                    self._tree_merge(patches, prompt)
                )
            except Exception as exc:  # pragma: no cover - 异常路径
                warnings.append(
                    f"tree_merge failed, falling back to passthrough: {exc}"
                )
                merged_patches = list(patches)
                dropped_patches = []
                conflict_count = 0
                conflict_patch_ids = []
                conflicts = []
                fallback_used = True
                merge_reason = f"tree_merge exception: {exc}"
        else:
            if not _OLD_SYSTEM_AVAILABLE:
                warnings.append(
                    "old system TreeReducePatchMerger unavailable, using passthrough"
                )
                merge_reason = "old system unavailable"
            else:
                merge_reason = f"unsupported strategy: {merge_strategy}"
                warnings.append(merge_reason)
            merged_patches = list(patches)
            dropped_patches = []
            conflict_count = 0
            conflict_patch_ids = []
            conflicts = []
            fallback_used = True

        # 合并后校验：如果提供 sample_set，对 merged patches 跑 PatchValidator
        validation_warnings = self._post_merge_validate(
            merged_patches, prompt, sample_set
        )
        warnings.extend(validation_warnings)

        merged_patch_ids = [getattr(p, "id", "") for p in merged_patches]
        dropped_patch_ids = [getattr(p, "id", "") for p in dropped_patches]

        report = PatchMergeReport(
            id=f"merge_report_{prompt.id}",
            input_patch_count=len(patches),
            merged_patch_count=len(merged_patches),
            conflict_count=conflict_count,
            merged_patches=[self._patch_to_dict(p) for p in merged_patches],
            conflicts=conflicts,
            metadata={
                "strategy": merge_strategy,
                "effective_strategy": effective_strategy,
            },
            strategy=merge_strategy,
            dropped_patch_count=len(dropped_patches),
            input_patch_ids=input_patch_ids,
            merged_patch_ids=merged_patch_ids,
            dropped_patch_ids=dropped_patch_ids,
            conflict_patch_ids=conflict_patch_ids,
            merge_reason=merge_reason,
            fallback_used=fallback_used,
            warnings=warnings,
        )

        return merged_patches, report

    # ------------------------------------------------------------------
    # tree_merge 实现
    # ------------------------------------------------------------------

    def _tree_merge(
        self,
        patches: list,
        prompt: StructuredPrompt,
    ) -> tuple[list, list, int, list[str], list[dict[str, Any]], str]:
        """调用老系统 TreeReducePatchMerger 进行合并。

        Returns:
            (merged_patches, dropped_patches, conflict_count,
             conflict_patch_ids, conflicts, merge_reason) 元组。
        """
        assert _OldPatch is not None and _TreeReducePatchMerger is not None

        # 转换为老系统 Patch
        old_patches = [self._to_old_patch(p, prompt) for p in patches]

        round_id = f"merge_{prompt.id}"
        merger = _TreeReducePatchMerger()
        result = merger.merge(
            round_id=round_id,
            patches=old_patches,
            prompt_ir=None,
        )

        # 转换回 ExtractionPatch / AnalysisPatch
        merged_patches: list = []
        for old_patch in result.final_patches:
            patch_class = self._resolve_patch_class(old_patch)
            merged_patches.append(self._from_old_patch(old_patch, patch_class))

        dropped_patches: list = []
        for old_patch in result.rejected_patches:
            patch_class = self._resolve_patch_class(old_patch)
            dropped_patches.append(self._from_old_patch(old_patch, patch_class))

        old_report = result.merge_report
        conflict_patch_ids = list(getattr(old_report, "conflict_patch_ids", []))
        conflict_count = len(conflict_patch_ids)

        # 提取 conflicts 信息（从 clusters 中聚合）
        conflicts: list[dict[str, Any]] = []
        clusters = getattr(old_report, "clusters", []) or []
        for cluster in clusters:
            conflicts.extend(cluster.get("conflicts", []) or [])

        merge_reason = (
            f"tree_merge: {len(patches)} input -> {len(merged_patches)} merged, "
            f"{len(dropped_patches)} dropped"
        )

        return (
            merged_patches,
            dropped_patches,
            conflict_count,
            conflict_patch_ids,
            conflicts,
            merge_reason,
        )

    # ------------------------------------------------------------------
    # 后置校验
    # ------------------------------------------------------------------

    def _post_merge_validate(
        self,
        merged_patches: list,
        prompt: StructuredPrompt,
        sample_set: SampleSet | None,
    ) -> list[str]:
        """对 merged patches 跑 PatchValidator，失败的 patch 标记 rejection_reason。

        Returns:
            校验过程中产生的 warning 列表。
        """
        warnings: list[str] = []
        if sample_set is None or not merged_patches:
            return warnings

        _, rejected = self.patch_validator.validate_batch(
            merged_patches, prompt, sample_set
        )
        for patch in rejected:
            patch.rejection_reason = "MERGED_PATCH_VALIDATION_FAILED"
            warnings.append(
                f"merged patch {getattr(patch, 'id', '?')} failed post-merge validation"
            )
        return warnings

    # ------------------------------------------------------------------
    # 数据结构转换
    # ------------------------------------------------------------------

    def _to_old_patch(self, patch: Any, prompt: StructuredPrompt) -> Any:
        """将 ExtractionPatch / AnalysisPatch 转换为老系统 Patch。"""
        assert _OldPatch is not None
        patch_type = "extraction" if isinstance(patch, ExtractionPatch) else "analysis"
        return _OldPatch(
            id=patch.id,
            type=patch_type,
            status="pending",
            target_prompt_type=patch_type,
            base_version_id=prompt.id,
            section_id=patch.target_section_id,
            operation_type=patch.operation_type,
            operation_mode=patch.operation_type,
            intent_name=patch.id,
            intent_description=patch.rationale,
            patch_text=patch.content,
            rationale=patch.rationale,
            source_sample_ids=list(patch.source_sample_ids),
        )

    def _from_old_patch(
        self,
        old_patch: Any,
        original_patch_class: type,
    ) -> ExtractionPatch | AnalysisPatch:
        """将老系统 Patch 转换回 ExtractionPatch / AnalysisPatch。"""
        return original_patch_class(
            id=old_patch.id,
            target_section_id=old_patch.section_id,
            operation_type=old_patch.operation_type,
            content=old_patch.patch_text,
            rationale=old_patch.rationale,
            source_sample_ids=list(old_patch.source_sample_ids),
            status="merged",
        )

    def _resolve_patch_class(self, old_patch: Any) -> type:
        """根据老系统 Patch 的 type 字段决定转换目标类。"""
        if getattr(old_patch, "type", "") == "analysis":
            return AnalysisPatch
        return ExtractionPatch

    def _patch_to_dict(self, patch: Any) -> dict[str, Any]:
        """将 patch 转换为字典（优先使用 to_dict，否则手动提取字段）。"""
        to_dict = getattr(patch, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return {
            "id": getattr(patch, "id", ""),
            "target_section_id": getattr(patch, "target_section_id", ""),
            "operation_type": getattr(patch, "operation_type", ""),
            "status": getattr(patch, "status", ""),
            "rejection_reason": getattr(patch, "rejection_reason", None),
        }


__all__ = ["MergeExecutor"]
