from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FewShotCandidate:
    id: str
    sample_id: str
    candidate_score: float = 0.0
    rejection_reason: str | None = None
    status: str = "mined"


@dataclass
class FewShotExample:
    id: str
    candidate_id: str
    source_sample_id: str
    asset_ids: list[str]
    reasoning_text: str
    final_output: dict[str, Any]
    schema_valid: bool
    matches_ground_truth: bool
    visual_evidence_grounded: bool | None = None
    status: str = "draft"


@dataclass
class FewShotSetVersion:
    id: str
    base_text_prompt_version_id: str
    version: int
    slot_count: int
    slots: list[dict[str, Any]] = field(default_factory=list)
    status: str = "candidate"
