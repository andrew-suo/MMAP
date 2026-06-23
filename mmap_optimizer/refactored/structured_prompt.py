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