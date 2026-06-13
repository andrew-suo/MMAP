from __future__ import annotations

from dataclasses import dataclass, field

from .schema import PromptTemplateSpec


@dataclass
class PromptTemplateRegistry:
    _templates: dict[str, PromptTemplateSpec] = field(default_factory=dict)

    def register(self, template: PromptTemplateSpec) -> None:
        if template.undeclared_placeholders():
            raise ValueError(f"Template {template.id} has undeclared placeholders: {template.undeclared_placeholders()}")
        self._templates[template.id] = template

    def get(self, template_id: str) -> PromptTemplateSpec:
        try:
            return self._templates[template_id]
        except KeyError as exc:
            raise KeyError(f"Unknown prompt template: {template_id}") from exc

    def ids(self) -> list[str]:
        return sorted(self._templates)

    def by_tag(self, tag: str) -> list[PromptTemplateSpec]:
        return [template for template in self._templates.values() if tag in template.tags]
