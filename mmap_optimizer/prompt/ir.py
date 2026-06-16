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
    source_map: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def clone_with_content(self, content: str, *, rendering_enabled: bool | None = None) -> "PromptSection":
        return replace(self, content=content, rendering_enabled=self.rendering_enabled if rendering_enabled is None else rendering_enabled)


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
    initialization: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)

    def section_by_id(self, section_id: str) -> PromptSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def with_replaced_section(self, section_id: str, content: str) -> "PromptIR":
        sections = [s.clone_with_content(content, rendering_enabled=True) if s.id == section_id else s for s in self.sections]
        return replace(self, sections=sections)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptIR":
        section_fields = set(PromptSection.__dataclass_fields__.keys())
        sections = [
            PromptSection(**{k: v for k, v in s.items() if k in section_fields})
            for s in data.get("sections", [])
        ]
        ir_fields = set(cls.__dataclass_fields__.keys())
        ir_data = {k: v for k, v in data.items() if k in ir_fields and k != "sections"}
        ir_data["sections"] = sections
        return cls(**ir_data)
