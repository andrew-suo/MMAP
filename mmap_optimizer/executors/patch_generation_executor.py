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

            suggestions, cited_sections = self._call_patch_generation_model(
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
                    cited_sections=cited_sections,
                )
                draft_patches.append(patch)

        validated, rejected = self.patch_validator.validate_batch_with_calibration(
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

            suggestions, cited_sections = self._call_patch_generation_model(
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
                    cited_sections=cited_sections,
                )
                draft_patches.append(patch)

        validated, rejected = self.patch_validator.validate_batch_with_calibration(
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
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """调用模型生成 patch suggestions。

        Args:
            prompt_type: "extraction" 或 "analysis"。
            extraction_result: 抽取结果（extraction patch 时使用）。
            analysis_result: 分析结果（extraction patch 时使用）。
            reflection_result: 反思结果（analysis patch 时使用）。
            ground_truth: 标准答案。
            current_prompt: 当前 prompt。

        Returns:
            (patches, cited_sections) 元组。
        """
        try:
            system_content = self._load_patch_generation_prompt()
        except Exception:
            return [], []

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
            raw_output = response.raw_output
        except Exception:
            return [], []

        parsed_output, status = repair_json_output(
            raw_output=raw_output,
            expected_schema={"patches": [], "cited_sections": []},
            model_client=self.model_client,
            model_config=self.model_config,
        )

        if parsed_output is None:
            return [], []

        # 兼容两种输出格式：
        # - dict: {"patches": [...], "cited_sections": [...]}（标准格式）
        # - list: [...]（模型直接返回 patch 数组，视为 patches）
        if isinstance(parsed_output, list):
            return parsed_output, []

        if not isinstance(parsed_output, dict):
            return [], []

        patches = parsed_output.get("patches", [])
        if not isinstance(patches, list):
            patches = []

        cited_sections = parsed_output.get("cited_sections", [])
        if not isinstance(cited_sections, list):
            cited_sections = []

        return patches, cited_sections

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

        # 1. Prompt Structure
        if current_prompt:
            parts.append("# Prompt Structure")
            parts.append(self._render_prompt_structure(current_prompt))
            parts.append("")

        # 2. Current Prompt
        if current_prompt:
            parts.append("# Current Prompt")
            parts.append(current_prompt.to_markdown())
            parts.append("")

        # 3. Case Execution
        if prompt_type == "extraction":
            if extraction_result:
                parts.append("# Case Execution")
                parts.append(f"- **Sample ID**: {extraction_result.sample_id}")
                parts.append(f"- **Status**: {extraction_result.status}")
                if extraction_result.raw_output:
                    parts.append(f"- **Raw Output**: {extraction_result.raw_output}")
                if extraction_result.parsed_output:
                    parts.append(f"- **Parsed Output**: {json.dumps(extraction_result.parsed_output, ensure_ascii=False)}")

            if analysis_result:
                parts.append("\n# Analysis Result")
                judgement = analysis_result.judgement
                parts.append(f"- **Judgement**: {json.dumps(judgement, ensure_ascii=False)}")
                parts.append(f"- **Analysis Correct**: {analysis_result.analysis_correct}")
                if analysis_result.error_reason:
                    parts.append(f"- **Error Reason**: {analysis_result.error_reason}")
                if analysis_result.confirmed_facts:
                    parts.append(f"- **Confirmed Facts**: {json.dumps(analysis_result.confirmed_facts, ensure_ascii=False)}")
                if analysis_result.hypothesized_error_causes:
                    parts.append(f"- **Hypothesized Error Causes**: {json.dumps(analysis_result.hypothesized_error_causes, ensure_ascii=False)}")

        elif prompt_type == "analysis":
            if reflection_result:
                parts.append("# Case Execution")
                parts.append(f"- **Sample ID**: {reflection_result.sample_id}")
                parts.append(f"- **Status**: {'INCORRECT' if reflection_result.reflection_success else 'CORRECT'}")
                if reflection_result.error_reason:
                    parts.append(f"- **Error Reason**: {reflection_result.error_reason}")
                if reflection_result.patch_suggestion:
                    parts.append(f"- **Patch Suggestion**: {json.dumps(reflection_result.patch_suggestion, ensure_ascii=False)}")
                if reflection_result.notes:
                    parts.append(f"- **Notes**: {json.dumps(reflection_result.notes, ensure_ascii=False)}")

            if hasattr(reflection_result, 'analysis_result') and reflection_result.analysis_result:
                ar = reflection_result.analysis_result
                parts.append("\n# Original Analysis Result")
                parts.append(f"- **Judgement**: {json.dumps(ar.judgement, ensure_ascii=False)}")
                parts.append(f"- **Analysis Correct**: {ar.analysis_correct}")

        # 4. Ground Truth
        if ground_truth:
            parts.append("\n# Ground Truth")
            parts.append(json.dumps(ground_truth, ensure_ascii=False))

        return "\n".join(parts)

    def _render_prompt_structure(self, prompt: StructuredPrompt) -> str:
        """渲染 prompt 结构（section id、title、level、mutable 状态）。"""

        def render_section(section: PromptSection, indent: str = "") -> list[str]:
            lines: list[str] = []
            mutable_tag = "" if section.mutable else " [PROTECTED]"
            lines.append(f"{indent}- {section.id}: {section.title} (level={section.level}){mutable_tag}")
            for child in section.children:
                lines.extend(render_section(child, indent + "  "))
            return lines

        all_lines: list[str] = []
        for section in prompt.sections:
            all_lines.extend(render_section(section))
        return "\n".join(all_lines)

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

            if analysis_result.patch_suggestion is not None:
                suggestion = dict(analysis_result.patch_suggestion)
                if "operation" in suggestion:
                    suggestion["op"] = suggestion.pop("operation")
                if "rationale" in suggestion:
                    suggestion["reasoning"] = suggestion.pop("rationale")
                if "op" not in suggestion:
                    suggestion["op"] = "append_to_section"
            else:
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
                    "op": "append_to_section",
                    "content": content,
                    "reasoning": rationale,
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

            # 确保使用新的操作格式
            if "operation" in suggestion:
                suggestion["op"] = suggestion.pop("operation")
            if "rationale" in suggestion:
                suggestion["reasoning"] = suggestion.pop("rationale")
            if "op" not in suggestion:
                suggestion["op"] = "append_to_section"

            if not suggestion.get("content"):
                suggestion["content"] = error_reason
            if not suggestion.get("reasoning"):
                suggestion["reasoning"] = error_reason

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
        cited_sections: list[str] | None = None,
    ) -> ExtractionPatch | AnalysisPatch:
        """从 patch suggestion 构建 patch 对象。"""
        target_section_id = suggestion.get("target_section", "section_1")
        operation_type = self._normalize_operation(suggestion.get("op", "append_to_section"))
        content = suggestion.get("content", "")
        rationale = suggestion.get("reasoning", "")
        target_text = suggestion.get("target_text")
        old_text = suggestion.get("old_text")
        new_text = suggestion.get("new_text")
        new_header = suggestion.get("new_header")

        metadata: dict[str, Any] = {}
        if cited_sections:
            metadata["cited_sections"] = cited_sections

        return patch_class(
            id=f"{patch_id_prefix}_{sample_id}",
            target_section_id=target_section_id,
            operation_type=operation_type,
            content=content,
            rationale=rationale,
            source_sample_ids=[sample_id],
            status="draft",
            target_text=target_text,
            old_text=old_text,
            new_text=new_text,
            new_header=new_header,
            metadata=metadata,
        )

    def _normalize_operation(self, operation: Any) -> str:
        """Normalize legacy suggestion operation names to patch operation types."""
        aliases = {
            "append": "append_to_section",
            "append_to_section": "append_to_section",
            "insert_after": "insert_after",
            "insert_before": "insert_before",
            "replace": "replace_section",
            "replace_section": "replace_section",
            "replace_in_section": "replace_in_section",
            "add_after_section": "add_after_section",
            "delete": "delete_section",
            "delete_section": "delete_section",
        }
        return aliases.get(str(operation), "append_to_section")

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
