"""MergeExecutor - Patch 合并执行器。

将多个 patch 合并为更少的 patch，并在合并后通过 PatchValidator 进行校验。

当 model_client 可用时，使用 ``ParallelPatchMerger``（基于 LLM 的并行合并）；
当 model_client 不可用或合并抛异常时，回退到 passthrough（原样返回输入 patch）。
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.progress import NullProgressReporter, ProgressReporter
from ..patch.types import ExtractionPatch, PatchMergeReport
from ..data.sample import SampleSet
from ..prompt.structured_prompt import StructuredPrompt
from ..patch.tree_reduce import ParallelPatchMerger
from .patch_validator import PatchValidator

logger = logging.getLogger(__name__)


class MergeExecutor:
    """Patch 合并执行器。

    合并策略：
    - 有 model_client 时使用 ``ParallelPatchMerger`` 进行 LLM 并行合并；
    - 无 model_client 或合并抛异常时回退到 passthrough（原样返回输入 patch）。

    合并完成后，如果传入 ``sample_set``，会对 merged patches 跑一次
    ``PatchValidator.validate_batch``，校验失败的 patch 会被标记
    ``rejection_reason="MERGED_PATCH_VALIDATION_FAILED"``。
    """

    PROVENANCE_SCHEMA_VERSION = "v3"

    def __init__(
        self,
        patch_validator: PatchValidator | None = None,
        model_client: Any = None,
        model_config: Any = None,
        merge_prompt_path: str | None = None,
        root_merge_prompt_path: str | None = None,
    ) -> None:
        """初始化合并执行器。

        Args:
            patch_validator: 可选的 PatchValidator 实例。如果未提供，
                内部创建默认实例。
            model_client: 模型客户端，用于 ParallelPatchMerger。
                为 None 时回退到 passthrough。
            model_config: 模型配置。
            merge_prompt_path: patch_merge.txt 路径。
            root_merge_prompt_path: patch_root_merge.txt 路径。
        """
        self.patch_validator = patch_validator or PatchValidator()
        self.model_client = model_client
        self.model_config = model_config
        self.merge_prompt_path = merge_prompt_path or "prompts/patch_merge.txt"
        self.root_merge_prompt_path = root_merge_prompt_path or "prompts/patch_root_merge.txt"
        self.progress_reporter: ProgressReporter = NullProgressReporter()

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
            merge_strategy: 合并策略（保留参数以兼容调用方，实际统一走 parallel_merge / passthrough）。
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

        # 尝试 parallel_merge（需要 model_client）→ passthrough
        merged_patches: list
        dropped_patches: list
        conflict_count: int
        conflict_patch_ids: list[str]
        conflicts: list[dict[str, Any]]
        fallback_used: bool = False
        merge_reason: str = ""
        invalid_provenance_patch_ids: list[str] = []
        pre_validation_merged_snapshot: list[dict[str, Any]] = []

        self.progress_reporter.step(
            f"    [Merge] strategy={merge_strategy} input_patches={len(patches)}"
        )

        if self.model_client is not None and merge_strategy == "tree_merge":
            try:
                merged_patches, dropped_patches, conflict_count, conflict_patch_ids, conflicts, merge_reason, invalid_provenance_patch_ids, pre_validation_merged_snapshot = (
                    self._parallel_merge(patches, prompt)
                )
            except Exception as exc:
                logger.warning("parallel_merge failed, using passthrough: %s", exc)
                warnings.append(f"parallel_merge failed: {exc}")
                merged_patches = list(patches)
                dropped_patches = []
                conflict_count = 0
                conflict_patch_ids = []
                conflicts = []
                fallback_used = True
                merge_reason = f"parallel_merge failed: {exc}"
        else:
            merged_patches = list(patches)
            dropped_patches = []
            conflict_count = 0
            conflict_patch_ids = []
            conflicts = []
            fallback_used = True
            merge_reason = "passthrough (no model_client or strategy != tree_merge)"

        # 合并后校验：如果提供 sample_set，对 merged patches 跑 PatchValidator
        validation_warnings, validation_rejected_patches = self._post_merge_validate(
            merged_patches, prompt, sample_set
        )
        warnings.extend(validation_warnings)
        if validation_rejected_patches:
            rejected_ids = {getattr(p, "id", "") for p in validation_rejected_patches}
            merged_patches = [
                p for p in merged_patches
                if getattr(p, "id", "") not in rejected_ids
            ]
            dropped_patches.extend(validation_rejected_patches)

        deduped_dropped: list[Any] = []
        seen_dropped_ids: set[str] = set()
        for patch in dropped_patches:
            patch_id = getattr(patch, "id", "")
            if patch_id and patch_id in seen_dropped_ids:
                continue
            if patch_id:
                seen_dropped_ids.add(patch_id)
            deduped_dropped.append(patch)
        dropped_patches = deduped_dropped

        merged_patch_ids = [getattr(p, "id", "") for p in merged_patches]
        merged_patch_id_set = {patch_id for patch_id in merged_patch_ids if patch_id}
        dropped_patch_ids = [
            getattr(p, "id", "")
            for p in dropped_patches
            if getattr(p, "id", "") not in merged_patch_id_set
        ]

        report = PatchMergeReport(
            id=f"merge_report_{prompt.id}",
            input_patch_count=len(patches),
            merged_patch_count=len(merged_patches),
            conflict_count=conflict_count,
            merged_patches=[self._patch_to_dict(p) for p in merged_patches],
            conflicts=conflicts,
            metadata={
                "strategy": merge_strategy,
                "provenance_schema_version": self.PROVENANCE_SCHEMA_VERSION,
                "pre_validation_merged_snapshot": pre_validation_merged_snapshot,
            },
            strategy=merge_strategy,
            dropped_patch_count=len(dropped_patches),
            input_patch_ids=input_patch_ids,
            merged_patch_ids=merged_patch_ids,
            dropped_patch_ids=dropped_patch_ids,
            conflict_patch_ids=conflict_patch_ids,
            invalid_provenance_patch_ids=invalid_provenance_patch_ids,
            merge_reason=merge_reason,
            fallback_used=fallback_used,
            warnings=warnings,
        )

        self.progress_reporter.step(
            "    [Merge] done "
            f"merged={len(merged_patches)} dropped={len(dropped_patches)} "
            f"invalid_provenance={len(invalid_provenance_patch_ids)}"
        )

        return merged_patches, report

    # ------------------------------------------------------------------
    # parallel_merge 实现（基于 LLM 的并行合并）
    # ------------------------------------------------------------------

    def _parallel_merge(
        self,
        patches: list,
        prompt: StructuredPrompt,
    ) -> tuple[list, list, int, list[str], list[dict[str, Any]], str, list[str], list[dict[str, Any]]]:
        """调用 ParallelPatchMerger 进行 LLM 并行合并。

        Returns:
            (merged_patches, dropped_patches, conflict_count,
             conflict_patch_ids, conflicts, merge_reason,
             invalid_provenance_patch_ids) 元组。
        """
        # 生成 prompt_structure 字符串
        prompt_structure = self._build_prompt_structure(prompt)

        # 将 patches 转换为 dict 列表
        patch_dicts = [self._patch_to_merge_dict(p) for p in patches]

        # 创建 ParallelPatchMerger 并执行合并
        merger = ParallelPatchMerger(
            model_client=self.model_client,
            model_config=self.model_config,
            merge_prompt_path=self.merge_prompt_path,
            root_merge_prompt_path=self.root_merge_prompt_path,
            progress_reporter=self.progress_reporter,
        )

        merged_dicts = merger.merge(patch_dicts, prompt_structure)

        # 将 dict 转换回 ExtractionPatch / AnalysisPatch
        patch_class_map: dict[str, type] = {}
        patch_by_id: dict[str, Any] = {}
        for p in patches:
            patch_class_map[getattr(p, "id", "")] = type(p)
            patch_by_id[getattr(p, "id", "")] = p

        input_patch_ids = {getattr(p, "id", "") for p in patches}

        merged_patches: list = []
        dropped_patches: list = []
        invalid_provenance_patch_ids: list[str] = []
        pre_validation_merged_snapshot: list[dict[str, Any]] = []
        for d in merged_dicts:
            pre_validation_merged_snapshot.append(self._merge_debug_snapshot(d))
            source_patch_ids = self._normalize_source_patch_ids(
                d.get("source_patch_ids"),
                fallback_patch_id=d.get("id", ""),
            )
            if (
                not source_patch_ids
                or any(source_patch_id not in input_patch_ids for source_patch_id in source_patch_ids)
            ):
                invalid_provenance_patch_ids.extend(source_patch_ids or [str(d.get("id", ""))])
                mapped_any = False
                for source_patch_id in source_patch_ids:
                    original_patch = patch_by_id.get(source_patch_id)
                    if original_patch is None:
                        continue
                    mapped_any = True
                    original_patch.status = "rejected"
                    original_patch.rejection_reason = "MERGE_PROVENANCE_INVALID"
                    dropped_patches.append(original_patch)
                if not mapped_any:
                    for original_patch in patches:
                        if original_patch in dropped_patches:
                            continue
                        original_patch.status = "rejected"
                        original_patch.rejection_reason = "MERGE_PROVENANCE_INVALID"
                        dropped_patches.append(original_patch)
                continue
            patch_id = d.get("id", "") or source_patch_ids[0]
            patch_class = patch_class_map.get(source_patch_ids[0], ExtractionPatch)
            merged_patches.append(self._dict_to_patch(d, patch_class, patch_id, source_patch_ids))

        conflict_count = 0
        conflict_patch_ids: list[str] = []
        conflicts: list[dict[str, Any]] = []

        merge_reason = (
            f"parallel_merge: {len(patches)} input -> {len(merged_patches)} merged"
        )

        return (
            merged_patches,
            dropped_patches,
            conflict_count,
            conflict_patch_ids,
            conflicts,
            merge_reason,
            invalid_provenance_patch_ids,
            pre_validation_merged_snapshot,
        )

    def _build_prompt_structure(self, prompt: StructuredPrompt) -> str:
        """构建 prompt 结构骨架字符串。"""
        lines: list[str] = []
        for section in prompt.sections:
            mutable_tag = "" if section.mutable else " [PROTECTED]"
            lines.append(f"{section.title}{mutable_tag}")
        return "\n".join(lines)

    def _patch_to_merge_dict(self, patch: Any) -> dict[str, Any]:
        """将 ExtractionPatch / AnalysisPatch 转换为合并用的 dict。"""
        patch_id = getattr(patch, "id", "")
        metadata = getattr(patch, "metadata", {}) or {}
        upstream_source_patch_ids = metadata.get(
            "upstream_source_patch_ids",
            metadata.get("source_patch_ids", [patch_id]),
        )
        parent_patch_ids = metadata.get("parent_patch_ids", [patch_id])
        if not isinstance(upstream_source_patch_ids, list):
            upstream_source_patch_ids = [patch_id]
        if not isinstance(parent_patch_ids, list):
            parent_patch_ids = [patch_id]
        return {
            "id": patch_id,
            "op": getattr(patch, "operation_type", ""),
            "target_section": getattr(patch, "target_section_id", ""),
            "content": getattr(patch, "content", ""),
            "rationale": getattr(patch, "rationale", ""),
            "source_sample_ids": list(getattr(patch, "source_sample_ids", [])),
            "source_patch_ids": [patch_id] if patch_id else [],
            "parent_patch_ids": [str(item) for item in parent_patch_ids if str(item)],
            "upstream_source_patch_ids": [
                str(item) for item in upstream_source_patch_ids if str(item)
            ],
        }

    def _dict_to_patch(
        self,
        d: dict[str, Any],
        patch_class: type,
        patch_id: str,
        source_patch_ids: list[str],
    ) -> Any:
        """将合并后的 dict 转换回 patch 对象。"""
        metadata = dict(d.get("metadata", {}))
        metadata["source_patch_ids"] = list(source_patch_ids)
        parent_patch_ids = d.get("parent_patch_ids")
        if isinstance(parent_patch_ids, list) and parent_patch_ids:
            metadata["parent_patch_ids"] = [
                str(item) for item in parent_patch_ids if str(item)
            ]
        upstream_source_patch_ids = d.get("upstream_source_patch_ids")
        if isinstance(upstream_source_patch_ids, list) and upstream_source_patch_ids:
            metadata["upstream_source_patch_ids"] = [
                str(item) for item in upstream_source_patch_ids if str(item)
            ]
        return patch_class(
            id=patch_id,
            target_section_id=d.get("target_section", d.get("target_section_id", "")),
            operation_type=d.get("op", d.get("operation_type", "append_to_section")),
            content=d.get("content", ""),
            rationale=d.get("rationale", d.get("reasoning", "")),
            source_sample_ids=d.get("source_sample_ids", []),
            status="merged",
            metadata=metadata,
        )

    def _normalize_source_patch_ids(
        self,
        source_patch_ids: Any,
        fallback_patch_id: str,
    ) -> list[str]:
        if isinstance(source_patch_ids, list):
            normalized = [str(item) for item in source_patch_ids if str(item)]
            if normalized:
                return normalized
        fallback = str(fallback_patch_id or "")
        return [fallback] if fallback else []

    # ------------------------------------------------------------------
    # 后置校验
    # ------------------------------------------------------------------

    def _post_merge_validate(
        self,
        merged_patches: list,
        prompt: StructuredPrompt,
        sample_set: SampleSet | None,
    ) -> tuple[list[str], list]:
        """对 merged patches 跑 PatchValidator，失败的 patch 标记 rejection_reason。

        Returns:
            (warning 列表, post-merge 校验失败 patch 列表)。
        """
        warnings: list[str] = []
        rejected_patches: list = []
        if sample_set is None or not merged_patches:
            return warnings, rejected_patches

        _, rejected = self.patch_validator.validate_batch(
            merged_patches, prompt, sample_set
        )
        for patch in rejected:
            patch.status = "rejected"
            patch.rejection_reason = "MERGED_PATCH_VALIDATION_FAILED"
            rejected_patches.append(patch)
            warnings.append(
                f"merged patch {getattr(patch, 'id', '?')} failed post-merge validation"
            )
        return warnings, rejected_patches

    # ------------------------------------------------------------------
    # 数据结构转换
    # ------------------------------------------------------------------

    def _patch_to_dict(self, patch: Any) -> dict[str, Any]:
        """将 patch 转换为字典（优先使用 to_dict，否则手动提取字段）。"""
        to_dict = getattr(patch, "to_dict", None)
        if callable(to_dict):
            result: Any = to_dict()
            return result if isinstance(result, dict) else dict(result)
        return {
            "id": getattr(patch, "id", ""),
            "target_section_id": getattr(patch, "target_section_id", ""),
            "operation_type": getattr(patch, "operation_type", ""),
            "status": getattr(patch, "status", ""),
            "rejection_reason": getattr(patch, "rejection_reason", None),
        }

    def _merge_debug_snapshot(self, merged_dict: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(merged_dict.get("id", "")),
            "source_patch_ids": self._list_str_field(merged_dict.get("source_patch_ids")),
            "parent_patch_ids": self._list_str_field(merged_dict.get("parent_patch_ids")),
            "upstream_source_patch_ids": self._list_str_field(
                merged_dict.get("upstream_source_patch_ids")
            ),
            "source_sample_ids": self._list_str_field(merged_dict.get("source_sample_ids")),
            "target_section": str(
                merged_dict.get("target_section", merged_dict.get("target_section_id", ""))
            ),
        }

    @staticmethod
    def _list_str_field(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item)]


__all__ = ["MergeExecutor"]
