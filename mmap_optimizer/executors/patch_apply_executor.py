"""PatchApplyExecutor - Patch 应用执行器。

将 patch 列表应用到 StructuredPrompt，生成新的 prompt 版本。
支持 7 种操作：append_to_section / insert_after / insert_before /
replace_in_section / replace_section / add_after_section / delete_section。

当 old_text 或 target_text 精确匹配失败时，启用三级降级匹配：
1. 精确匹配 → 2. difflib 模糊匹配 → 3. LLM 语义匹配。
"""

from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from ..prompt.structured_prompt import PromptSection, StructuredPrompt
from ..patch.text_matcher import match_text_with_fallback

logger = logging.getLogger(__name__)


@dataclass
class PatchApplyReport:
    """Patch 应用报告。

    记录一次 patch 应用过程的结果，包括应用/拒绝的 patch 列表、
    修改的 section 列表、前后内容 hash 以及变更标记。
    """

    id: str
    base_prompt_id: str
    new_prompt_id: str
    applied_patch_ids: list[str]
    rejected_patch_ids: list[str]
    modified_section_ids: list[str]
    before_hash: str
    after_hash: str
    changed: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "base_prompt_id": self.base_prompt_id,
            "new_prompt_id": self.new_prompt_id,
            "applied_patch_ids": list(self.applied_patch_ids),
            "rejected_patch_ids": list(self.rejected_patch_ids),
            "modified_section_ids": list(self.modified_section_ids),
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "changed": self.changed,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchApplyReport":
        """从字典格式创建。"""
        return cls(
            id=data["id"],
            base_prompt_id=data["base_prompt_id"],
            new_prompt_id=data["new_prompt_id"],
            applied_patch_ids=data.get("applied_patch_ids", []),
            rejected_patch_ids=data.get("rejected_patch_ids", []),
            modified_section_ids=data.get("modified_section_ids", []),
            before_hash=data["before_hash"],
            after_hash=data["after_hash"],
            changed=data["changed"],
            warnings=data.get("warnings", []),
        )


class PatchApplyExecutor:
    """Patch 应用执行器。

    将 patch 列表应用到 StructuredPrompt，生成新的 prompt 版本。
    支持 7 种操作：``append_to_section`` / ``insert_after`` / ``insert_before`` /
    ``replace_in_section`` / ``replace_section`` / ``add_after_section`` / ``delete_section``。
    """

    def __init__(
        self,
        allow_delete: bool = False,
        model_client: Any = None,
        model_config: Any = None,
        text_match_prompt_path: str = "prompts/patch_text_match.txt",
        fuzzy_threshold: float = 0.6,
    ) -> None:
        """初始化执行器。

        Args:
            allow_delete: 是否允许 delete 操作，默认 False。
            model_client: 模型客户端，用于 LLM 文本匹配降级。
            model_config: 模型配置。
            text_match_prompt_path: 文本匹配 LLM prompt 路径。
            fuzzy_threshold: 模糊匹配相似度阈值。
        """
        self.allow_delete = allow_delete
        self.model_client = model_client
        self.model_config = model_config
        self.text_match_prompt_path = text_match_prompt_path
        self.fuzzy_threshold = fuzzy_threshold

    def apply(
        self,
        base_prompt: StructuredPrompt,
        patches: list,
    ) -> tuple[StructuredPrompt, PatchApplyReport]:
        """应用 patch 列表到 prompt。

        流程：
        1. 深拷贝 base_prompt 作为工作副本，避免修改原对象。
        2. 计算 before_hash（基于 to_markdown() 输出）。
        3. 遍历 patches，依次检查 section 存在性、可变性、操作类型，
           应用合法 patch，拒绝非法 patch。
        4. 计算 after_hash，判断是否发生变更。
        5. 更新 new_prompt 的 version / parent_id / metadata / raw_markdown。
        6. 生成 PatchApplyReport 并返回。

        Args:
            base_prompt: 基础 StructuredPrompt。
            patches: 待应用的 patch 列表（ExtractionPatch 或 AnalysisPatch）。

        Returns:
            (new_prompt, report) 元组。
        """
        # 深拷贝 base_prompt 作为工作副本
        new_prompt = self._deep_copy_prompt(base_prompt)

        # 计算 before_hash
        before_hash = self._compute_hash(new_prompt)

        applied_patch_ids: list[str] = []
        rejected_patch_ids: list[str] = []
        modified_section_ids: list[str] = []
        warnings: list[str] = []

        if not patches:
            warnings.append("No patches provided to apply")

        for patch in patches:
            # 1. 检查 target_section_id 是否存在（递归查找包括 children）
            section = self._find_section(new_prompt, patch.target_section_id)
            if section is None:
                rejected_patch_ids.append(patch.id)
                patch.status = "rejected"
                patch.rejection_reason = "UNKNOWN_SECTION"
                warnings.append(
                    f"Patch {patch.id} rejected: target section "
                    f"{patch.target_section_id} not found"
                )
                continue

            # 2. 检查 target section 是否 mutable
            if not section.mutable:
                rejected_patch_ids.append(patch.id)
                patch.status = "rejected"
                patch.rejection_reason = "IMMUTABLE_SECTION"
                warnings.append(
                    f"Patch {patch.id} rejected: target section "
                    f"{patch.target_section_id} is immutable"
                )
                continue

            # 3. 检查 operation_type 并应用
            op = patch.operation_type
            if op == "append_to_section":
                section.content = section.content + "\n" + patch.content
            elif op == "replace_section":
                section.content = patch.content
            elif op == "delete_section":
                if self.allow_delete:
                    section.content = ""
                else:
                    rejected_patch_ids.append(patch.id)
                    patch.status = "rejected"
                    patch.rejection_reason = "DELETE_DISABLED"
                    warnings.append(
                        f"Patch {patch.id} rejected: delete operation not allowed"
                    )
                    continue
            elif op == "insert_after":
                target_text = patch.target_text or ""
                if not target_text or target_text not in section.content:
                    # 降级匹配：fuzzy → LLM
                    target_text = self._try_fallback_match(
                        section.content, target_text, "target_text", patch.id
                    )
                if not target_text:
                    rejected_patch_ids.append(patch.id)
                    patch.status = "rejected"
                    patch.rejection_reason = "TARGET_TEXT_NOT_FOUND"
                    warnings.append(
                        f"Patch {patch.id} rejected: target_text not found in section (all fallbacks failed)"
                    )
                    continue
                section.content = section.content.replace(
                    target_text,
                    target_text + "\n" + patch.content,
                    1,
                )
            elif op == "insert_before":
                target_text = patch.target_text or ""
                if not target_text or target_text not in section.content:
                    # 降级匹配：fuzzy → LLM
                    target_text = self._try_fallback_match(
                        section.content, target_text, "target_text", patch.id
                    )
                if not target_text:
                    rejected_patch_ids.append(patch.id)
                    patch.status = "rejected"
                    patch.rejection_reason = "TARGET_TEXT_NOT_FOUND"
                    warnings.append(
                        f"Patch {patch.id} rejected: target_text not found in section (all fallbacks failed)"
                    )
                    continue
                section.content = section.content.replace(
                    target_text,
                    patch.content + "\n" + target_text,
                    1,
                )
            elif op == "replace_in_section":
                old_text = patch.old_text or ""
                if not old_text or old_text not in section.content:
                    # 降级匹配：fuzzy → LLM
                    old_text = self._try_fallback_match(
                        section.content, old_text, "old_text", patch.id
                    )
                if not old_text:
                    rejected_patch_ids.append(patch.id)
                    patch.status = "rejected"
                    patch.rejection_reason = "OLD_TEXT_NOT_FOUND"
                    warnings.append(
                        f"Patch {patch.id} rejected: old_text not found in section (all fallbacks failed)"
                    )
                    continue
                section.content = section.content.replace(
                    old_text, patch.new_text or "", 1
                )
            elif op == "add_after_section":
                new_section = PromptSection(
                    id=f"{section.id}_patch_{patch.id}",
                    title=patch.new_header or "New Section",
                    level=section.level,
                    content=patch.content,
                    mutable=True,
                )
                self._insert_section_after(new_prompt, section.id, new_section)
            else:
                rejected_patch_ids.append(patch.id)
                patch.status = "rejected"
                patch.rejection_reason = "UNSUPPORTED_OPERATION"
                warnings.append(
                    f"Patch {patch.id} rejected: unknown operation {op}"
                )
                continue

            # 记录成功应用的 patch
            applied_patch_ids.append(patch.id)
            if section.id not in modified_section_ids:
                modified_section_ids.append(section.id)
            patch.status = "accepted"
            patch.rejection_reason = None

        # 计算 after_hash
        after_hash = self._compute_hash(new_prompt)
        changed = before_hash != after_hash

        # 设置 new_prompt 属性
        new_prompt.version = base_prompt.version + 1
        new_prompt.parent_id = base_prompt.id  # 动态属性
        new_prompt.metadata = {"applied_patch_ids": list(applied_patch_ids)}  # 动态属性

        # 重新生成 raw_markdown
        new_prompt.raw_markdown = new_prompt.to_markdown()

        # 生成 report
        report = PatchApplyReport(
            id=f"patch_apply_report_{base_prompt.id}",
            base_prompt_id=base_prompt.id,
            new_prompt_id=new_prompt.id,
            applied_patch_ids=applied_patch_ids,
            rejected_patch_ids=rejected_patch_ids,
            modified_section_ids=modified_section_ids,
            before_hash=before_hash,
            after_hash=after_hash,
            changed=changed,
            warnings=warnings,
        )

        return new_prompt, report

    def _find_section(
        self,
        prompt: StructuredPrompt,
        section_id: str,
    ) -> PromptSection | None:
        """递归查找 section（包括 children）。"""
        return self._find_section_recursive(prompt.sections, section_id)

    def _find_section_recursive(
        self,
        sections: list,
        section_id: str,
    ) -> PromptSection | None:
        """在 sections 列表中递归查找（包括 children）。"""
        for section in sections:
            if section.id == section_id:
                return section
            found = self._find_section_recursive(section.children, section_id)
            if found is not None:
                return found
        return None

    def _insert_section_after(
        self,
        prompt: StructuredPrompt,
        target_section_id: str,
        new_section: PromptSection,
    ) -> bool:
        """在 target_section 之后插入 new_section（递归查找包括 children）。

        Returns:
            True 如果插入成功，False 如果未找到 target_section。
        """
        return self._insert_section_after_recursive(
            prompt.sections, target_section_id, new_section
        )

    def _insert_section_after_recursive(
        self,
        sections: list,
        target_section_id: str,
        new_section: PromptSection,
    ) -> bool:
        """递归在 sections 列表中查找并插入。"""
        for i, section in enumerate(sections):
            if section.id == target_section_id:
                sections.insert(i + 1, new_section)
                return True
            if self._insert_section_after_recursive(
                section.children, target_section_id, new_section
            ):
                return True
        return False

    def _compute_hash(self, prompt: StructuredPrompt) -> str:
        """计算 prompt 内容 hash（基于 to_markdown() 输出）。"""
        content = prompt.to_markdown()
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _try_fallback_match(
        self,
        section_content: str,
        intent_text: str,
        field_type: str,
        patch_id: str,
    ) -> str:
        """降级匹配：fuzzy match → LLM match。

        当精确匹配失败时调用，依次尝试 difflib 模糊匹配和 LLM 语义匹配。

        Args:
            section_content: 目标 section 的实际内容。
            intent_text: 待匹配的文本（可能是模糊引用）。
            field_type: 字段类型（"old_text" 或 "target_text"）。
            patch_id: patch ID，用于日志记录。

        Returns:
            匹配到的原文子串，如果所有降级方案都失败则返回空字符串。
        """
        if not intent_text:
            return ""

        matched = match_text_with_fallback(
            section_content=section_content,
            intent_text=intent_text,
            field_type=field_type,
            model_client=self.model_client,
            model_config=self.model_config,
            prompt_path=self.text_match_prompt_path,
            fuzzy_threshold=self.fuzzy_threshold,
        )

        if matched:
            logger.info(
                "Patch %s: %s 降级匹配成功，使用实际原文替代",
                patch_id,
                field_type,
            )
            return matched

        return ""

    def _deep_copy_prompt(self, prompt: StructuredPrompt) -> StructuredPrompt:
        """深拷贝 prompt。"""
        return copy.deepcopy(prompt)


__all__ = ["PatchApplyExecutor", "PatchApplyReport"]
