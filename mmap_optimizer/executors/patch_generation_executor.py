"""PatchGenerationExecutor - Patch 生成执行器。

基于模型生成 extraction 和 analysis 的 patch。输入包括：
- Extraction Patch：分析结果（抽取结果、分析过程、分析结果、GT）
- Analysis Patch：反思结果（analysis的完整分析结果和反思结果）

生成后使用 PatchValidator 校验，返回
(draft_patches, validated_patches, rejected_patches)。

当模型不可用时，回退到代码合成模式。
"""

from __future__ import annotations

import json
from typing import Any

from ..stages.extraction_prompt_optimization import AnalysisResult, ExtractionResult
from ..patch.types import AnalysisPatch, ExtractionPatch
from ..data.sample import SampleSet
from ..prompt.structured_prompt import PromptSection, StructuredPrompt
from ..prompt.output_repair import repair_json_output
from .patch_validator import PatchValidator


class PatchGenerationExecutor:
    """Patch 生成执行器。

    Extraction patch：基于模型分析结果生成。
    Analysis patch：基于模型反思结果生成。

    生成后使用 PatchValidator 校验，返回
    (draft_patches, validated_patches, rejected_patches)。

    当 model_client 可用时，优先使用模型生成模式；否则回退到代码合成模式。
    """

    def __init__(
        self,
        model_client: Any = None,
        model_config: dict[str, Any] | None = None,
        patch_generation_prompt_path: str = "prompts/patch_generation.txt",
        patch_validator: PatchValidator | None = None,
    ) -> None:
        """初始化 patch 生成执行器。

        Args:
            model_client: 模型客户端实例。如果提供，优先使用模型生成模式。
            model_config: 模型配置参数。
            patch_generation_prompt_path: patch 生成提示词文件路径。
            patch_validator: 可选的 PatchValidator 实例。如果未提供，
                内部创建默认实例。
        """
        self.model_client = model_client
        self.model_config = model_config or {}
        self.patch_generation_prompt_path = patch_generation_prompt_path
        self.patch_validator = patch_validator or PatchValidator()

    def generate_extraction_patches(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[ExtractionPatch], list[ExtractionPatch], list[ExtractionPatch]]:
        """生成 extraction patch。

        当 model_client 可用时，调用模型生成 patch；否则回退到代码合成模式。

        Args:
            analysis_results: 分析结果列表。
            extraction_results: 抽取结果列表。
            extraction_prompt: 目标 extraction prompt。
            sample_set: 样本集合。

        Returns:
            (draft_patches, validated_patches, rejected_patches) 元组。
        """
        if self.model_client is not None:
            return self._generate_extraction_patches_with_model(
                analysis_results, extraction_results, extraction_prompt, sample_set
            )
        return self._generate_extraction_patches_by_code(
            analysis_results, extraction_results, extraction_prompt, sample_set
        )

    def generate_analysis_patches(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[AnalysisPatch], list[AnalysisPatch], list[AnalysisPatch]]:
        """生成 analysis patch。

        当 model_client 可用时，调用模型生成 patch；否则回退到代码合成模式。

        Args:
            reflection_results: 反思结果列表。
            analysis_prompt: 目标 analysis prompt。
            sample_set: 样本集合。

        Returns:
            (draft_patches, validated_patches, rejected_patches) 元组。
        """
        if self.model_client is not None:
            return self._generate_analysis_patches_with_model(
                reflection_results, analysis_prompt, sample_set
            )
        return self._generate_analysis_patches_by_code(
            reflection_results, analysis_prompt, sample_set
        )

    def _generate_extraction_patches_with_model(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[ExtractionPatch], list[ExtractionPatch], list[ExtractionPatch]]:
        """调用模型生成 extraction patch。

        输入包含：原抽取结果、分析过程、分析结果、GT。
        """
        draft_patches: list[ExtractionPatch] = []
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

            sample_spec = sample_set.specs.get(sample_id)
            if sample_spec is None:
                continue

            ground_truth = sample_spec.ground_truth

            suggestions = self._call_patch_generation_model(
                prompt_type="extraction",
                extraction_result=extraction_result,
                analysis_result=analysis_result,
                ground_truth=ground_truth,
                current_prompt=extraction_prompt,
            )

            for suggestion in suggestions:
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

    def _generate_analysis_patches_with_model(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[AnalysisPatch], list[AnalysisPatch], list[AnalysisPatch]]:
        """调用模型生成 analysis patch。

        输入包含：analysis的完整分析结果和反思结果。
        """
        from ..stages.analysis_prompt_optimization import ReflectionResult

        draft_patches: list[AnalysisPatch] = []

        for reflection in reflection_results:
            if not isinstance(reflection, ReflectionResult):
                continue
            if not reflection.reflection_success:
                continue

            sample_id = reflection.sample_id
            sample_spec = sample_set.specs.get(sample_id)
            if sample_spec is None:
                continue

            ground_truth = sample_spec.ground_truth

            suggestions = self._call_patch_generation_model(
                prompt_type="analysis",
                reflection_result=reflection,
                ground_truth=ground_truth,
                current_prompt=analysis_prompt,
            )

            for suggestion in suggestions:
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

    def _call_patch_generation_model(
        self,
        prompt_type: str,
        extraction_result: ExtractionResult | None = None,
        analysis_result: AnalysisResult | None = None,
        reflection_result: Any = None,
        ground_truth: dict[str, Any] | None = None,
        current_prompt: StructuredPrompt | None = None,
    ) -> list[dict[str, Any]]:
        """调用模型生成 patch suggestions。

        Args:
            prompt_type: "extraction" 或 "analysis"。
            extraction_result: 抽取结果（extraction patch 时使用）。
            analysis_result: 分析结果（extraction patch 时使用）。
            reflection_result: 反思结果（analysis patch 时使用）。
            ground_truth: 标准答案。
            current_prompt: 当前 prompt。

        Returns:
            patch_suggestions 列表。
        """
        try:
            system_content = self._load_patch_generation_prompt()
        except Exception:
            return []

        user_content = self._build_patch_generation_user_message(
            prompt_type=prompt_type,
            extraction_result=extraction_result,
            analysis_result=analysis_result,
            reflection_result=reflection_result,
            ground_truth=ground_truth,
            current_prompt=current_prompt,
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        try:
            response = self.model_client.complete(
                messages=messages,
                model_config=self.model_config,
            )
            raw_output = response.get("content", "") if isinstance(response, dict) else str(response)
        except Exception:
            return []

        parsed_output, status = repair_json_output(
            raw_output=raw_output,
            expected_schema={"patch_suggestions": []},
            model_client=self.model_client,
            model_config=self.model_config,
        )

        if parsed_output is None:
            return []

        suggestions = parsed_output.get("patch_suggestions", [])
        if not isinstance(suggestions, list):
            suggestions = []

        return suggestions

    def _load_patch_generation_prompt(self) -> str:
        """加载 patch 生成提示词文件。"""
        from pathlib import Path

        path = Path(self.patch_generation_prompt_path)
        return path.read_text(encoding="utf-8")

    def _build_patch_generation_user_message(
        self,
        prompt_type: str,
        extraction_result: ExtractionResult | None = None,
        analysis_result: AnalysisResult | None = None,
        reflection_result: Any = None,
        ground_truth: dict[str, Any] | None = None,
        current_prompt: StructuredPrompt | None = None,
    ) -> str:
        """构建 patch 生成的用户消息。"""
        parts: list[str] = []

        if prompt_type == "extraction":
            if extraction_result:
                parts.append("# Extraction Result")
                parts.append(f"sample_id: {extraction_result.sample_id}")
                parts.append(f"status: {extraction_result.status}")
                parts.append(f"raw_output: {extraction_result.raw_output}")
                if extraction_result.parsed_output:
                    parts.append(f"parsed_output: {json.dumps(extraction_result.parsed_output, ensure_ascii=False)}")

            if analysis_result:
                parts.append("\n# Analysis Result")
                judgement = analysis_result.judgement
                parts.append(f"judgement: {json.dumps(judgement, ensure_ascii=False)}")
                parts.append(f"analysis_correct: {analysis_result.analysis_correct}")
                if analysis_result.error_reason:
                    parts.append(f"error_reason: {analysis_result.error_reason}")
                if analysis_result.confirmed_facts:
                    parts.append(f"confirmed_facts: {json.dumps(analysis_result.confirmed_facts, ensure_ascii=False)}")
                if analysis_result.hypothesized_error_causes:
                    parts.append(f"hypothesized_error_causes: {json.dumps(analysis_result.hypothesized_error_causes, ensure_ascii=False)}")

        elif prompt_type == "analysis":
            if reflection_result:
                parts.append("# Reflection Result")
                parts.append(f"sample_id: {reflection_result.sample_id}")
                parts.append(f"reflection_success: {reflection_result.reflection_success}")
                if reflection_result.error_reason:
                    parts.append(f"error_reason: {reflection_result.error_reason}")
                if reflection_result.patch_suggestion:
                    parts.append(f"patch_suggestion: {json.dumps(reflection_result.patch_suggestion, ensure_ascii=False)}")
                if reflection_result.notes:
                    parts.append(f"notes: {json.dumps(reflection_result.notes, ensure_ascii=False)}")

            if hasattr(reflection_result, 'analysis_result') and reflection_result.analysis_result:
                ar = reflection_result.analysis_result
                parts.append("\n# Original Analysis Result")
                parts.append(f"judgement: {json.dumps(ar.judgement, ensure_ascii=False)}")
                parts.append(f"analysis_correct: {ar.analysis_correct}")

        if ground_truth:
            parts.append("\n# Ground Truth")
            parts.append(json.dumps(ground_truth, ensure_ascii=False))

        if current_prompt:
            parts.append("\n# Current Prompt")
            parts.append(current_prompt.to_markdown())

        parts.append("\n# Task")
        parts.append("Generate patch suggestions to fix the identified issues.")
        parts.append("Output a JSON object with patch_suggestions array.")

        return "\n".join(parts)

    def _generate_extraction_patches_by_code(
        self,
        analysis_results: list[AnalysisResult],
        extraction_results: list[ExtractionResult],
        extraction_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[ExtractionPatch], list[ExtractionPatch], list[ExtractionPatch]]:
        """通过代码合成生成 extraction patch（回退模式）。"""
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

    def _generate_analysis_patches_by_code(
        self,
        reflection_results: list,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[list[AnalysisPatch], list[AnalysisPatch], list[AnalysisPatch]]:
        """通过代码合成生成 analysis patch（回退模式）。"""
        from ..stages.analysis_prompt_optimization import ReflectionResult

        draft_patches: list[AnalysisPatch] = []

        for reflection in reflection_results:
            if not isinstance(reflection, ReflectionResult):
                continue
            if not reflection.reflection_success:
                continue
            if reflection.patch_suggestion is None:
                continue

            sample_id = reflection.sample_id
            error_reason = reflection.error_reason or ""
            suggestion: dict[str, Any] = dict(reflection.patch_suggestion)

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
        """基于分析结果构造 extraction patch 的 content 和 rationale（回退模式）。"""
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
        """从 patch_suggestion 构建 patch 对象。"""
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
        """获取 prompt 中所有 mutable section 的 id（递归 children）。"""

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