from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.core.enums import PromptType


@dataclass
class OutputSchemaContract:
    id: str
    prompt_type: PromptType | str
    version: int
    schema: dict[str, Any]
    primary_answer_fields: list[str]
    immutable: bool = True
    schema_format: str = "json_schema"
    validation_policy: dict[str, Any] = field(default_factory=lambda: {
        "extra_fields_allowed": False,
        "missing_required_fields_allowed": False,
        "require_schema_valid_for_correct": True,
    })

    @property
    def target_section_id(self) -> str:
        return "analysis_output_schema" if self.prompt_type == PromptType.ANALYSIS or self.prompt_type == "analysis" else "output_schema"
