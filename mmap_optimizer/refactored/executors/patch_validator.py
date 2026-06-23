"""PatchValidator - Patch 校验器。

在 patch 进入合并/应用流程前，对 patch 进行结构性校验，
过滤掉无效、占位符、或针对不可变 section 的 patch。
"""

from __future__ import annotations

from ..patch import AnalysisPatch, ExtractionPatch
from ..sample import SampleSet
from ..structured_prompt import PromptSection, StructuredPrompt


class PatchValidator:
    """Patch 校验器。

    在 patch 进入合并/应用流程前进行结构性校验：
    - target section 是否存在且可变
    - operation_type 是否合法
    - content 是否非空且非占位符
    - source_sample_ids 是否非空且都存在于 sample_set

    校验通过的 patch 会被标记为 ``candidate``，
    校验失败的 patch 会被标记为 ``rejected`` 并填写 ``rejection_reason``。
    """

    SUPPORTED_OPERATIONS: frozenset[str] = frozenset({"replace", "append", "delete"})
    PLACEHOLDER_MARKERS: tuple[str, ...] = ("mock patch content", "todo", "n/a", "mock")

    def __init__(self, allow_delete: bool = False) -> None:
        """初始化校验器。

        Args:
            allow_delete: 是否允许 delete 操作，默认 False。
        """
        self.allow_delete = allow_delete

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
        if patch.operation_type == "delete" and not self.allow_delete:
            return self._reject(patch, "DELETE_DISABLED"), False

        # 5. content 是否为空或纯空白
        if not patch.content or not patch.content.strip():
            return self._reject(patch, "EMPTY_CONTENT"), False

        # 6. content 是否为占位符
        if self._is_placeholder_content(patch.content):
            return self._reject(patch, "PLACEHOLDER_CONTENT"), False

        # 7. source_sample_ids 是否为空
        if not patch.source_sample_ids:
            return self._reject(patch, "EMPTY_SOURCE_SAMPLE_IDS"), False

        # 8. source_sample_ids 是否都存在于 sample_set.specs 中
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
