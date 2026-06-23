"""结构化 Prompt 模型。

根据设计文档，Prompt Structuring Phase 负责将初始 Markdown prompt
转换为结构化的 section-based prompt。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class PromptSection:
    """Prompt Section，结构化 prompt 的一个章节。"""
    id: str
    title: str
    level: int  # 1, 2, 3 对应 #, ##, ###
    content: str
    bullets: list[str] = field(default_factory=list)
    children: list["PromptSection"] = field(default_factory=list)
    mutable: bool = True  # 是否可以被 patch 修改
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "content": self.content,
            "bullets": list(self.bullets),
            "children": [child.to_dict() for child in self.children],
            "mutable": self.mutable,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptSection":
        """从字典格式创建。"""
        children = [cls.from_dict(child) for child in data.get("children", [])]
        return cls(
            id=data["id"],
            title=data["title"],
            level=data["level"],
            content=data["content"],
            bullets=data.get("bullets", []),
            children=children,
            mutable=data.get("mutable", True),
            metadata=data.get("metadata", {}),
        )


@dataclass
class StructuredPrompt:
    """结构化 Prompt。"""
    id: str
    prompt_type: Literal["extraction", "analysis"]
    sections: list[PromptSection]
    raw_markdown: str
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "prompt_type": self.prompt_type,
            "sections": [section.to_dict() for section in self.sections],
            "raw_markdown": self.raw_markdown,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredPrompt":
        """从字典格式创建。"""
        sections = [PromptSection.from_dict(s) for s in data.get("sections", [])]
        return cls(
            id=data["id"],
            prompt_type=data["prompt_type"],
            sections=sections,
            raw_markdown=data["raw_markdown"],
            version=data.get("version", 1),
        )

    def to_markdown(self) -> str:
        """将结构化 prompt 转换回 Markdown 格式。"""
        lines = []

        for section in self.sections:
            # 添加标题
            prefix = "#" * section.level
            lines.append(f"{prefix} {section.title}")
            lines.append("")

            # 添加内容
            if section.content:
                lines.append(section.content)
                lines.append("")

            # 添加 bullets
            for bullet in section.bullets:
                lines.append(f"- {bullet}")
            lines.append("")

            # 添加子章节
            for child in section.children:
                self._render_section(child, lines)

        return "\n".join(lines).strip()

    def _render_section(self, section: PromptSection, lines: list[str]) -> None:
        """递归渲染章节。"""
        prefix = "#" * section.level
        lines.append(f"{prefix} {section.title}")
        lines.append("")

        if section.content:
            lines.append(section.content)
            lines.append("")

        for bullet in section.bullets:
            lines.append(f"- {bullet}")
        lines.append("")

        for child in section.children:
            self._render_section(child, lines)

    def get_section_by_id(self, section_id: str) -> PromptSection | None:
        """根据 ID 获取章节。"""
        for section in self.sections:
            if section.id == section_id:
                return section
            result = self._find_section_in_children(section, section_id)
            if result:
                return result
        return None

    def _find_section_in_children(self, section: PromptSection, section_id: str) -> PromptSection | None:
        """在子章节中查找。"""
        for child in section.children:
            if child.id == section_id:
                return child
            result = self._find_section_in_children(child, section_id)
            if result:
                return result
        return None

    def get_mutable_sections(self) -> list[PromptSection]:
        """获取所有可修改的章节。"""
        result = []
        for section in self.sections:
            if section.mutable:
                result.append(section)
            result.extend(self._get_mutable_children(section))
        return result

    def _get_mutable_children(self, section: PromptSection) -> list[PromptSection]:
        """获取子章节中可修改的章节。"""
        result = []
        for child in section.children:
            if child.mutable:
                result.append(child)
            result.extend(self._get_mutable_children(child))
        return result

    def render_to_model_prompt(self) -> str:
        """渲染为适合模型输入的纯文本格式。

        与 ``to_markdown`` 相比，本方法输出更紧凑的纯文本：
        - 保留章节层级结构（用缩进表达）
        - 保留代码块和表格原文
        - 去除多余空行，降低 token 消耗
        """
        lines: list[str] = []
        for section in self.sections:
            self._render_section_for_model(section, lines, indent_level=0)
        return "\n".join(lines).strip()

    def _render_section_for_model(
        self,
        section: PromptSection,
        lines: list[str],
        indent_level: int,
    ) -> None:
        """递归渲染章节为模型输入格式。"""
        indent = "  " * indent_level
        # 章节标题：用层级前缀表达，例如 "## Title"
        prefix = "#" * section.level
        lines.append(f"{indent}{prefix} {section.title}")

        if section.content:
            # 保留代码块和表格原文，按行追加
            for content_line in section.content.splitlines():
                lines.append(f"{indent}{content_line}" if indent else content_line)

        for bullet in section.bullets:
            lines.append(f"{indent}- {bullet}")

        for child in section.children:
            self._render_section_for_model(child, lines, indent_level + 1)

    def render_with_fewshot(self, fewshot_examples: list) -> str:
        """渲染带 few-shot 示例的 prompt。

        在 prompt 末尾追加 few-shot 示例 section。
        """
        base = self.to_markdown()
        if not fewshot_examples:
            return base

        lines: list[str] = [base, ""]
        lines.append("# Few-shot Examples")
        lines.append("")

        for idx, example in enumerate(fewshot_examples, start=1):
            lines.append(f"## Example {idx}")
            lines.append("")

            # 兼容 dict 和 dataclass 两种形式
            input_text = _get_attr(example, "input_text", "")
            output_text = _get_attr(example, "output_text", "")
            input_images = _get_attr(example, "input_images", []) or []
            output_data = _get_attr(example, "output_data", {}) or {}

            if input_text:
                lines.append("Input:")
                lines.append(input_text)
                lines.append("")

            if input_images:
                lines.append("Input Images:")
                for img in input_images:
                    lines.append(f"- {img}")
                lines.append("")

            if output_text:
                lines.append("Output:")
                lines.append(output_text)
                lines.append("")

            if output_data:
                lines.append("Output Data:")
                lines.append(_format_data(output_data))
                lines.append("")

        return "\n".join(lines).strip()


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """从 dict 或对象中获取属性。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _format_data(data: Any) -> str:
    """将数据格式化为字符串。"""
    if isinstance(data, str):
        return data
    try:
        import json

        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)


class StructuredPromptRenderer:
    """将 StructuredPrompt 渲染成模型输入字符串。"""

    def render(self, prompt: StructuredPrompt) -> str:
        """渲染为完整 Markdown。"""
        return prompt.to_markdown()

    def render_with_fewshot(self, prompt: StructuredPrompt, fewshot_examples: list) -> str:
        """渲染带 few-shot 的 prompt。"""
        return prompt.render_with_fewshot(fewshot_examples)

    def render_system_message(self, prompt: StructuredPrompt) -> str:
        """渲染为 system message 格式。"""
        return self.render(prompt)

    def render_to_model_prompt(self, prompt: StructuredPrompt) -> str:
        """渲染为适合模型输入的纯文本格式。"""
        return prompt.render_to_model_prompt()