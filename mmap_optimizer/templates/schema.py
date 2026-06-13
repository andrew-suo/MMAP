from __future__ import annotations

from dataclasses import dataclass, field
from string import Formatter
from typing import Any


@dataclass(frozen=True)
class PromptTemplateSpec:
    id: str
    version: str
    purpose: str
    input_variables: list[str]
    output_contract: dict[str, Any]
    template: str
    risk_level: str = "medium"
    tags: list[str] = field(default_factory=list)

    def render(self, **values: Any) -> str:
        missing = [name for name in self.input_variables if name not in values]
        if missing:
            raise ValueError("Missing template variables: " + ", ".join(missing))
        return self.template.format(**values)

    def undeclared_placeholders(self) -> list[str]:
        placeholders = [field_name for _, field_name, _, _ in Formatter().parse(self.template) if field_name]
        return sorted({name for name in placeholders if name not in self.input_variables})
