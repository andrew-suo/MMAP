"""PatchValidator - Patch 校验器。

在 patch 进入合并/应用流程前，对 patch 进行结构性校验，
过滤掉无效、占位符、或针对不可变 section 的 patch。
支持模型校准：当定位文本匹配失败时，可调用模型进行校准。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..patch.types import AnalysisPatch, ExtractionPatch
from ..data.sample import SampleSet
from ..prompt.structured_prompt import PromptSection, StructuredPrompt


# 可校准的 rejection reason（定位文本匹配失败）
_CALIBRABLE_REASONS: frozenset[str] = frozenset({
    "TARGET_TEXT_NOT_FOUND",
    "OLD_TEXT_NOT_FOUND",
})


class PatchValidator:
    """Patch 校验器。

    在 patch 进入合并/应用流程前进行结构性校验：
    - target section 是否存在且可变
    - operation_type 是否合法
    - content 是否非空且非占位符
    - 定位文本（target_text/old_text）是否在 section 中可匹配
    - source_sample_ids 是否非空且都存在于 sample_set

    校验通过的 patch 会被标记为 ``candidate``，
    校验失败的 patch 会被标记为 ``rejected`` 并填写 ``rejection_reason``。

    当配置了 model_client 时，支持 ``validate_batch_with_calibration`` 方法：
    对定位文本匹配失败的 patch 调用模型校准，校准后重新校验。
    """

    SUPPORTED_OPERATIONS: frozenset[str] = frozenset({
        "append_to_section",
        "insert_after",
        "insert_before",
        "replace_in_section",
        "replace_section",
        "add_after_section",
        "delete_section",
    })
    PLACEHOLDER_MARKERS: tuple[str, ...] = ("mock patch content", "todo", "n/a", "mock")

    def __init__(
        self,
        allow_delete: bool = False,
        model_client: Any = None,
        model_config: dict[str, Any] | None = None,
        calibration_prompt_path: str | None = None,
    ) -> None:
        """初始化校验器。

        Args:
            allow_delete: 是否允许 delete 操作，默认 False。
            model_client: 模型客户端（可选），用于定位文本校准。
            model_config: 模型配置（可选）。
            calibration_prompt_path: 校准 prompt 文件路径（可选）。
        """
        self.allow_delete = allow_delete
        self.model_client = model_client
        self.model_config = model_config
        self.calibration_prompt_path = calibration_prompt_path

    def validate(
        self,
        patch: ExtractionPatch | AnalysisPatch,
        prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[ExtractionPatch | AnalysisPatch, bool]:
        """校验单个 patch。

        按顺序检查各项校验规则，第一个失败即拒绝。

        Args:
            patch: 待校验的 patch（ExtractionPatch 或 AnalysisPatch）。
            prompt: 目标 StructuredPrompt。
            sample_set: 样本集合，用于校验 source_sample_ids。

        Returns:
            (patch, is_valid) 元组。校验通过时 patch.status="candidate"，
            失败时 patch.status="rejected" 且 patch.rejection_reason 已填写。
        """
        # 1. target_section_id 是否存在
        section = self._find_section(prompt, patch.target_section_id)
        if section is None:
            return self._reject(patch, "UNKNOWN_SECTION"), False

        # 2. target section 是否 mutable
        if not section.mutable:
            return self._reject(patch, "IMMUTABLE_SECTION"), False

        # 3. operation_type 是否合法
        if patch.operation_type not in self.SUPPORTED_OPERATIONS:
            return self._reject(patch, "UNSUPPORTED_OPERATION"), False

        # 4. delete 是否允许
        if patch.operation_type == "delete_section" and not self.allow_delete:
            return self._reject(patch, "DELETE_DISABLED"), False

        # 5. content 是否为空或纯空白
        if not patch.content or not patch.content.strip():
            return self._reject(patch, "EMPTY_CONTENT"), False

        # 6. content 是否为占位符
        if self._is_placeholder_content(patch.content):
            return self._reject(patch, "PLACEHOLDER_CONTENT"), False

        # 7. 定位文本校验（insert_after/insert_before 检查 target_text）
        if patch.operation_type in ("insert_after", "insert_before"):
            if not patch.target_text:
                return self._reject(patch, "TARGET_TEXT_NOT_FOUND"), False
            if patch.target_text not in section.content:
                return self._reject(patch, "TARGET_TEXT_NOT_FOUND"), False

        # 7.1 定位文本校验（replace_in_section 检查 old_text）
        if patch.operation_type == "replace_in_section":
            if not patch.old_text:
                return self._reject(patch, "OLD_TEXT_NOT_FOUND"), False
            if patch.old_text not in section.content:
                return self._reject(patch, "OLD_TEXT_NOT_FOUND"), False

        # 8. source_sample_ids 是否为空
        if not patch.source_sample_ids:
            return self._reject(patch, "EMPTY_SOURCE_SAMPLE_IDS"), False

        # 9. source_sample_ids 是否都存在于 sample_set.specs 中
        for sample_id in patch.source_sample_ids:
            if sample_id not in sample_set.specs:
                return self._reject(patch, f"UNKNOWN_SOURCE_SAMPLE_ID:{sample_id}"), False

        # 校验通过
        patch.status = "candidate"
        patch.rejection_reason = None
        return patch, True

    def validate_batch(
        self,
        patches: list[ExtractionPatch | AnalysisPatch],
        prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[
        list[ExtractionPatch | AnalysisPatch],
        list[ExtractionPatch | AnalysisPatch],
    ]:
        """批量校验 patch。

        Args:
            patches: 待校验的 patch 列表。
            prompt: 目标 StructuredPrompt。
            sample_set: 样本集合。

        Returns:
            (validated_patches, rejected_patches) 元组。
        """
        validated: list[ExtractionPatch | AnalysisPatch] = []
        rejected: list[ExtractionPatch | AnalysisPatch] = []
        for patch in patches:
            _, is_valid = self.validate(patch, prompt, sample_set)
            if is_valid:
                validated.append(patch)
            else:
                rejected.append(patch)
        return validated, rejected

    def validate_batch_with_calibration(
        self,
        patches: list[ExtractionPatch | AnalysisPatch],
        prompt: StructuredPrompt,
        sample_set: SampleSet,
    ) -> tuple[
        list[ExtractionPatch | AnalysisPatch],
        list[ExtractionPatch | AnalysisPatch],
    ]:
        """批量校验 patch，对定位文本失败的 patch 进行模型校准。

        流程：
        1. 常规 validate_batch 校验。
        2. 对 rejected 中定位文本失败的 patch，调用模型校准。
        3. 校准后重新校验。
        4. 返回最终 validated/rejected。

        当 model_client 不可用时，回退到普通 validate_batch。

        Args:
            patches: 待校验的 patch 列表。
            prompt: 目标 StructuredPrompt。
            sample_set: 样本集合。

        Returns:
            (validated_patches, rejected_patches) 元组。
        """
        # 1. 常规校验
        validated, rejected = self.validate_batch(patches, prompt, sample_set)

        # 2. 如果没有 model_client 或没有可校准的 patch，直接返回
        if self.model_client is None or self.calibration_prompt_path is None:
            return validated, rejected

        calibrable: list[ExtractionPatch | AnalysisPatch] = []
        not_calibrable: list[ExtractionPatch | AnalysisPatch] = []
        for patch in rejected:
            reason = self._extract_rejection_reason(patch)
            if reason in _CALIBRABLE_REASONS:
                calibrable.append(patch)
            else:
                not_calibrable.append(patch)

        if not calibrable:
            return validated, rejected

        # 3. 首次校准
        calibrated = self._calibrate_patches(calibrable, prompt, failure_info="")

        # 4. 重新校验校准后的 patch
        re_validated, still_rejected = self.validate_batch(calibrated, prompt, sample_set)

        # 5. 对仍失败的 patch 进行一次重试（带 failure_info）
        retry_calibrable: list[ExtractionPatch | AnalysisPatch] = []
        for patch in still_rejected:
            reason = self._extract_rejection_reason(patch)
            if reason in _CALIBRABLE_REASONS:
                retry_calibrable.append(patch)

        if retry_calibrable:
            # 构建失败信息
            failure_parts: list[str] = []
            for patch in retry_calibrable:
                reason = self._extract_rejection_reason(patch)
                failure_parts.append(
                    f"Patch {patch.id} failed: {reason}"
                )
            failure_info = "; ".join(failure_parts)

            retry_calibrated = self._calibrate_patches(
                retry_calibrable, prompt, failure_info=failure_info
            )
            retry_validated, retry_rejected = self.validate_batch(
                retry_calibrated, prompt, sample_set
            )
            re_validated.extend(retry_validated)
            not_calibrable.extend(retry_rejected)
        else:
            not_calibrable.extend(still_rejected)

        validated.extend(re_validated)
        return validated, not_calibrable

    def _calibrate_patches(
        self,
        patches: list[ExtractionPatch | AnalysisPatch],
        prompt: StructuredPrompt,
        failure_info: str = "",
    ) -> list[ExtractionPatch | AnalysisPatch]:
        """调用模型校准 patch 的定位字段。

        Args:
            patches: 待校准的 patch 列表。
            prompt: 目标 StructuredPrompt。
            failure_info: 上轮失败信息（空字符串表示首次校准）。

        Returns:
            校准后的 patch 列表（与输入数量一致）。
        """
        if not patches:
            return patches

        try:
            # 加载校准 prompt
            calibration_prompt = Path(self.calibration_prompt_path).read_text(
                encoding="utf-8"
            )

            # 构建消息
            user_message = self._build_calibration_message(
                patches, prompt, failure_info
            )
            messages = [
                {"role": "system", "content": calibration_prompt},
                {"role": "user", "content": user_message},
            ]

            # 调用模型
            response = self.model_client.complete(
                messages, model_config=self.model_config
            )
            raw_output = response.raw_output.strip()

            # 解析校准结果
            calibrated_data = self._parse_calibration_output(raw_output)
            if calibrated_data is None:
                return patches

            # 更新 patch 字段
            return self._apply_calibration(patches, calibrated_data)

        except Exception:
            # 任何异常都返回原 patch
            return patches

    def _build_calibration_message(
        self,
        patches: list[ExtractionPatch | AnalysisPatch],
        prompt: StructuredPrompt,
        failure_info: str,
    ) -> str:
        """构建校准请求消息。"""
        # Prompt 结构骨架
        structure_lines: list[str] = []
        for section in prompt.sections:
            self._collect_section_structure(section, structure_lines, indent=0)
        prompt_structure = "\n".join(structure_lines)

        # Prompt 实际全文
        current_prompt = prompt.to_markdown()

        # Patches JSON
        patches_json = json.dumps(
            [self._patch_to_calibration_dict(p) for p in patches],
            ensure_ascii=False,
            indent=2,
        )

        # Failure info
        failure_section = failure_info if failure_info else "（首次校准，无上轮失败信息）"

        return (
            f"# Prompt Structure\n{prompt_structure}\n\n"
            f"# Current Prompt\n{current_prompt}\n\n"
            f"# Patches to Calibrate\n{patches_json}\n\n"
            f"# Failure Info\n{failure_section}"
        )

    def _collect_section_structure(
        self,
        section: PromptSection,
        lines: list[str],
        indent: int,
    ) -> None:
        """递归收集 section 结构骨架。"""
        prefix = "  " * indent
        mutable_tag = "" if section.mutable else " [PROTECTED]"
        lines.append(f"{prefix}{section.title} (id={section.id}){mutable_tag}")
        for child in section.children:
            self._collect_section_structure(child, lines, indent + 1)

    def _patch_to_calibration_dict(
        self,
        patch: ExtractionPatch | AnalysisPatch,
    ) -> dict[str, Any]:
        """将 patch 转换为校准用的字典（只包含校准相关字段）。"""
        result: dict[str, Any] = {
            "id": patch.id,
            "op": patch.operation_type,
            "target_section": patch.target_section_id,
        }
        if patch.target_text is not None:
            result["target_text"] = patch.target_text
        if patch.old_text is not None:
            result["old_text"] = patch.old_text
        if patch.new_text is not None:
            result["new_text"] = patch.new_text
        if patch.new_header is not None:
            result["new_header"] = patch.new_header
        result["content"] = patch.content
        result["reasoning"] = patch.rationale
        return result

    def _parse_calibration_output(
        self,
        raw_output: str,
    ) -> list[dict[str, Any]] | None:
        """解析模型校准输出。

        Args:
            raw_output: 模型原始输出。

        Returns:
            校准后的 patch 字典列表，或 None（解析失败）。
        """
        import re

        # 移除 markdown 代码块标记
        cleaned = re.sub(r"^```json\s*\n?", "", raw_output, flags=re.MULTILINE)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*\n?", "", cleaned, flags=re.MULTILINE)
        cleaned = cleaned.strip()

        # 尝试直接解析
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "patches" in parsed:
                return parsed["patches"]
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试提取 JSON 数组
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and start < end:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    def _apply_calibration(
        self,
        patches: list[ExtractionPatch | AnalysisPatch],
        calibrated_data: list[dict[str, Any]],
    ) -> list[ExtractionPatch | AnalysisPatch]:
        """将校准结果应用到 patch 列表。

        根据 id 匹配，只更新定位字段（target_section_id, target_text, old_text），
        保护其他字段不被篡改。

        Args:
            patches: 原 patch 列表。
            calibrated_data: 校准后的字典列表。

        Returns:
            更新后的 patch 列表（与输入数量一致）。
        """
        # 构建 id → calibrated_data 映射
        calibration_map: dict[str, dict[str, Any]] = {}
        for item in calibrated_data:
            item_id = item.get("id")
            if item_id is not None:
                calibration_map[str(item_id)] = item

        result: list[ExtractionPatch | AnalysisPatch] = []
        for patch in patches:
            calibrated = calibration_map.get(patch.id)
            if calibrated is not None:
                # 只更新定位字段，保护其他字段
                new_section = calibrated.get("target_section")
                if new_section and isinstance(new_section, str):
                    patch.target_section_id = new_section

                new_target_text = calibrated.get("target_text")
                if new_target_text and isinstance(new_target_text, str):
                    patch.target_text = new_target_text

                new_old_text = calibrated.get("old_text")
                if new_old_text and isinstance(new_old_text, str):
                    patch.old_text = new_old_text

            result.append(patch)

        return result

    def _extract_rejection_reason(
        self,
        patch: ExtractionPatch | AnalysisPatch,
    ) -> str:
        """提取 rejection_reason 中的原因代码。

        rejection_reason 格式为 "VALIDATION_FAILED:REASON_CODE"，
        提取 REASON_CODE 部分。
        """
        if not patch.rejection_reason:
            return ""
        reason = patch.rejection_reason
        if ":" in reason:
            return reason.split(":", 1)[1]
        return reason

    def _find_section(
        self,
        prompt: StructuredPrompt,
        section_id: str,
    ) -> PromptSection | None:
        """递归查找 section（包括 children）。"""
        for section in prompt.sections:
            found = self._find_section_recursive(section, section_id)
            if found is not None:
                return found
        return None

    def _find_section_recursive(
        self,
        section: PromptSection,
        section_id: str,
    ) -> PromptSection | None:
        """在 section 及其 children 中递归查找。"""
        if section.id == section_id:
            return section
        for child in section.children:
            found = self._find_section_recursive(child, section_id)
            if found is not None:
                return found
        return None

    def _is_placeholder_content(self, content: str) -> bool:
        """检查是否为占位符内容。

        检查 content（不区分大小写）是否包含常见的占位符标记，
        如 "Mock patch content"、"TODO"、"N/A"、"mock" 等。
        """
        normalized = content.strip().lower()
        if not normalized:
            return False
        for marker in self.PLACEHOLDER_MARKERS:
            if marker in normalized:
                return True
        return False

    @staticmethod
    def _reject(
        patch: ExtractionPatch | AnalysisPatch,
        reason: str,
    ) -> ExtractionPatch | AnalysisPatch:
        """将 patch 标记为 rejected 并返回。"""
        patch.status = "rejected"
        patch.rejection_reason = f"VALIDATION_FAILED:{reason}"
        return patch


__all__ = ["PatchValidator"]
