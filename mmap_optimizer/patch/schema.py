from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Patch:
    id: str
    type: str
    status: str
    target_prompt_type: str
    base_version_id: str
    section_id: str
    operation_type: str
    operation_mode: str
    intent_name: str
    intent_description: str
    patch_text: str
    rationale: str
    old_text: str | None = None
    target_text: str | None = None
    new_text: str | None = None
    source_sample_ids: list[str] = field(default_factory=list)
    source_analysis_ids: list[str] = field(default_factory=list)
    risk_level: str = "unknown"
    possible_side_effects: list[str] = field(default_factory=list)
    fixed_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    toxicity_result: str = "not_tested"
    effectiveness_result: str = "not_tested"
    rejection_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
