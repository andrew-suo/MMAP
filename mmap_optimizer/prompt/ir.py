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

    def section_by_id(self, section_id: str) -> PromptSection | None:
        return next((s for s in self.sections if s.id == section_id), None)

    @property
    def renderable_sections(self) -> list[PromptSection]:
        return [s for s in self.sections if s.rendering_enabled]

    def sections_by_type(self, type: str) -> list[PromptSection]:
        return [s for s in self.sections if s.type == type]

    def sections_by_scope(self, scope: str) -> list[PromptSection]:
        return [s for s in self.sections if s.scope == scope]

    def section_index(self, section_id: str) -> int | None:
        for i, s in enumerate(self.sections):
            if s.id == section_id:
                return i
        return None

    def has_section(self, section_id: str) -> bool:
        return any(s.id == section_id for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptIR":
        sections_data = data.get("sections", [])
        sections = [PromptSection(**{k: v for k, v in s.items() if k in PromptSection.__dataclass_fields__}) for s in sections_data]
        prompt_type_raw = data.get("prompt_type", "extraction")
        prompt_type = prompt_type_raw if isinstance(prompt_type_raw, PromptType) else PromptType(prompt_type_raw)
        return cls(
            id=data.get("id", ""),
            prompt_type=prompt_type,
            version=data.get("version", 1),
            output_schema_contract_id=data.get("output_schema_contract_id", ""),
            sections=sections,
            rendering_order=data.get("rendering_order", []),
            include_section_markers=data.get("include_section_markers", True),
            global_constraints=data.get("global_constraints", {}),
            parent_prompt_ir_id=data.get("parent_prompt_ir_id"),
            applied_patch_ids=data.get("applied_patch_ids", []),
            compression_patch_ids=data.get("compression_patch_ids", []),
        )

    def with_replaced_section(self, section_id: str, content: str) -> "PromptIR":
        sections = [s.clone_with_content(content, rendering_enabled=True) if s.id == section_id else s for s in self.sections]
        return replace(self, sections=sections)
