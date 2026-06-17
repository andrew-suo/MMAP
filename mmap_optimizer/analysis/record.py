from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalysisRecord:
    id: str
    round_id: str
    extraction_run_id: str
    evaluation_record_id: str
    sample_id: str
    analysis_prompt_version_id: str
    judgement: dict[str, Any]
    patch_candidate_ids: list[str] = field(default_factory=list)
    judgement_matches_evaluator: bool = True
    parse_success: bool = True
    schema_valid: bool = True
    parse_error: str | None = None
    schema_errors: list[str] = field(default_factory=list)
    repaired: bool = False
    repair_actions: list[str] = field(default_factory=list)
    generated_patch_count: int = 0
    invalid_patch_count: int = 0
    invalid_patch_candidate_count: int = 0
    prompt_section_attribution: list = field(default_factory=list)
