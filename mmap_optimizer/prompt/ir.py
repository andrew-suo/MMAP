from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mmap_optimizer.core.enums import PromptType


@dataclass
class PromptSection:
    id: str
    type: str
    content: str
    name: str | None = None
    scope: str = "task"
    priority: str = "medium"
    compressibility: str = "medium"
    mutability: str = "normal"
    rendering_enabled: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)

    def clone_with_content(self, content: str) -> "PromptSection":
        return replace(self, content=content)


@dataclass
class PromptIR:
    id: str
    prompt_type: PromptType | str
    version: int
    output_schema_contract_id: str
    sections: list[PromptSection]
    rendering_order: list[str] = field(default_factory=list)
    include_section_markers: bool = True
    global_constraints: dict[str, Any] = field(default_factory=dict)
    parent_prompt_ir_id: str | None = None
    applied_patch_ids: list[str] = field(default_factory=list)
    compression_patch_ids: list[str] = field(default_factory=list)

    def section_by_id(self, section_id: str) -> PromptSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def with_replaced_section(self, section_id: str, content: str) -> "PromptIR":
        sections = [s.clone_with_content(content) if s.id == section_id else s for s in self.sections]
        return replace(self, sections=sections)
