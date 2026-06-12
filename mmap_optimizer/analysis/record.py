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
    generated_patch_count: int = 0
    invalid_patch_count: int = 0
    schema_violation_patch_count: int = 0
    frozen_target_patch_count: int = 0
