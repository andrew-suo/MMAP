"""PatchGenerationExecutor - Patch 生成执行器。

基于 AnalysisResult 中的 error_reason、confirmed_facts、
hypothesized_error_causes 构建 ExtractionPatch，
并通过 PatchValidator 进行结构性校验，返回
(draft_patches, validated_patches, rejected_patches)。

Analysis 阶段的 patch 生成则基于 ReflectionResult 中的 patch_suggestion。
"""

from __future__ import annotations

from typing import Any

from ..stages.extraction_prompt_optimization import AnalysisResult, ExtractionResult
from ..patch.types import AnalysisPatch, ExtractionPatch
from ..data.sample import SampleSet
from ..prompt.structured_prompt import PromptSection, StructuredPrompt
from .patch_validator import PatchValidator


class PatchGenerationExecutor:
    """Patch 生成执行器。

    Extraction patch：基于 AnalysisResult 中的 error_reason、
    confirmed_facts、hypothesized_error_causes 构造 patch。

    Analysis patch：基于 ReflectionResult 中的 patch_suggestion 构造。

    生成后使用 PatchValidator 校验，返回
    (draft_patches, validated_patches, rejected_patches)。
    """

    def __init__(self, patch_validator: PatchValidator | None = None) -> None:
        """初始化 patch 生成执行器。

        Args:
            patch_validator: 可选的 PatchValidator 实例。如果未提供，
                内部创建默认实例。
        """
        self.patch_validator = patch_validator or PatchValidator()

    def generate_extraction_patches(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[ExtractionPatch], list[ExtractionPatch], list[ExtractionPatch]]:
        """生成 extraction patch。

        只从 analysis_correct=true 且 extraction 确实错误的样本生成 patch。
        基于 error_reason + confirmed_facts + hypothesized_error_causes
        构造 patch，不依赖模型直接生成的 patch_suggestion。

        Args:
            analysis_results: 分析结果列表。
            extraction_results: 抽取结果列表（用于上下文参考）。
            extraction_prompt: 目标 extraction prompt。
            sample_set: 样本集合。

        Returns:
            (draft_patches, validated_patches, rejected_patches) 元组。
        """
        draft_patches: list[ExtractionPatch] = []
        mutable_section_ids = self._get_mutable_section_ids(extraction_prompt)
        default_section_id = mutable_section_ids[0] if mutable_section_ids else "section_1"
        extraction_result_map = {r.sample_id: r for r in extraction_results}

        for analysis_result in analysis_results:
            if not analysis_result.analysis_correct:
                continue

            sample_id = analysis_result.sample_id
            extraction_result = extraction_result_map.get(sample_id)
            if extraction_result is None:
                continue

            extraction_correct = analysis_result.judgement.get("judgement", {}).get(
                "is_correct", False
            )
            if extraction_correct:
                continue

            error_reason = analysis_result.error_reason or ""
            confirmed_facts = analysis_result.confirmed_facts
            hypothesized_error_causes = analysis_result.hypothesized_error_causes

            content, rationale = self._compose_extraction_patch_content(
                error_reason=error_reason,
                confirmed_facts=confirmed_facts,
                hypothesized_error_causes=hypothesized_error_causes,
            )

            if not content:
                continue

            suggestion = {
                "target_section": default_section_id,
                "operation": "append",
                "content": content,
                "rationale": rationale,
            }

            patch = self._build_patch_from_suggestion(
                sample_id=sample_id,
                suggestion=suggestion,
                patch_class=ExtractionPatch,
                patch_id_prefix="patch_extraction",
            )
            draft_patches.append(patch)

        validated, rejected = self.patch_validator.validate_batch(
            draft_patches, extraction_prompt, sample_set
        )
        return draft_patches, validated, rejected

    def generate_analysis_patches(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[AnalysisPatch], list[AnalysisPatch], list[AnalysisPatch]]:
        """生成 analysis patch。

        只从 reflection_success=true 且 patch_suggestion 不为 None 的样本
        生成 patch。从 patch_suggestion 中提取 patch 信息。生成后用
        PatchValidator 校验。

        Args:
            reflection_results: 反思结果列表。
            analysis_prompt: 目标 analysis prompt。
            sample_set: 样本集合。

        Returns:
            (draft_patches, validated_patches, rejected_patches) 元组。
        """
        # 延迟导入以避免循环依赖
        from ..stages.analysis_prompt_optimization import ReflectionResult

        draft_patches: list[AnalysisPatch] = []

        for reflection in reflection_results:
            if not reflection.reflection_success:
                continue
            if reflection.patch_suggestion is None:
                continue

            sample_id = reflection.sample_id
            error_reason = reflection.error_reason or ""
            suggestion: dict[str, Any] = dict(reflection.patch_suggestion)

            # content / rationale 缺失时回退到 error_reason
            if not suggestion.get("content"):
                suggestion["content"] = error_reason
            if not suggestion.get("rationale"):
                suggestion["rationale"] = error_reason

            patch = self._build_patch_from_suggestion(
                sample_id=sample_id,
                suggestion=suggestion,
                patch_class=AnalysisPatch,
                patch_id_prefix="patch_analysis",
            )
            draft_patches.append(patch)

        validated, rejected = self.patch_validator.validate_batch(
            draft_patches, analysis_prompt, sample_set
        )
        return draft_patches, validated, rejected

    def _compose_extraction_patch_content(
        self,
        error_reason: str,
        confirmed_facts: list[str],
        hypothesized_error_causes: list[str],
    ) -> tuple[str, str]:
        """基于分析结果构造 extraction patch 的 content 和 rationale。

        Args:
            error_reason: 错误原因。
            confirmed_facts: 确认的事实列表。
            hypothesized_error_causes: 假设的错误原因列表。

        Returns:
            (content, rationale) 元组。
        """
        content_parts: list[str] = []
        rationale_parts: list[str] = []

        if error_reason:
            content_parts.append(error_reason)
            rationale_parts.append(f"Error reason: {error_reason}")

        if hypothesized_error_causes:
            causes_text = "; ".join(hypothesized_error_causes[:3])
            if not content_parts:
                content_parts.append(causes_text)
            rationale_parts.append(f"Hypothesized causes: {causes_text}")

        if confirmed_facts:
            facts_text = "; ".join(confirmed_facts[:3])
            rationale_parts.append(f"Confirmed facts: {facts_text}")

        content = "\n".join(content_parts) if content_parts else ""
        rationale = " | ".join(rationale_parts) if rationale_parts else ""

        return content, rationale

    def _build_patch_from_suggestion(
        self,
        sample_id: str,
        suggestion: dict[str, Any],
        patch_class: type,
        patch_id_prefix: str,
    ) -> ExtractionPatch | AnalysisPatch:
        """从 patch_suggestion 构建 patch 对象。

        Args:
            sample_id: 来源样本 ID。
            suggestion: patch_suggestion 字典，可能包含 target_section、
                operation、content、rationale。
            patch_class: patch 类（ExtractionPatch 或 AnalysisPatch）。
            patch_id_prefix: patch ID 前缀。

        Returns:
            patch 对象（ExtractionPatch 或 AnalysisPatch）。
        """
        target_section_id = suggestion.get("target_section", "section_1")
        operation_type = suggestion.get("operation", "replace")
        content = suggestion.get("content", "")
        rationale = suggestion.get("rationale", "")

        return patch_class(
            id=f"{patch_id_prefix}_{sample_id}",
            target_section_id=target_section_id,
            operation_type=operation_type,
            content=content,
            rationale=rationale,
            source_sample_ids=[sample_id],
            status="draft",
        )

    def _get_mutable_section_ids(self, prompt: StructuredPrompt) -> list[str]:
        """获取 prompt 中所有 mutable section 的 id（递归 children）。

        Args:
            prompt: 目标 StructuredPrompt。

        Returns:
            所有 mutable section 的 id 列表。
        """

        def collect(section: PromptSection) -> list[str]:
            result: list[str] = []
            if section.mutable:
                result.append(section.id)
            for child in section.children:
                result.extend(collect(child))
            return result

        ids: list[str] = []
        for section in prompt.sections:
            ids.extend(collect(section))
        return ids


__all__ = ["PatchGenerationExecutor"]
