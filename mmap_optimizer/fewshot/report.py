from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FewShotOptimizationReport:
    id: str
    round_id: str
    prompt_version_before_id: str
    triggered: bool
    reason: str
    slot_count_before: int = 0
    slot_count_after: int = 0
    max_slots: int = 0
    candidate_count: int = 0
    accepted: bool = False
    prompt_version_after_id: str | None = None
    fewshot_set_version_id: str | None = None
    selected_candidate_id: str | None = None
    selected_sample_id: str | None = None
    baseline_accuracy: float = 0.0
    candidate_accuracy: float = 0.0
    accuracy_delta: float = 0.0
    broken_sample_ids: list[str] = field(default_factory=list)
    schema_violation_sample_ids: list[str] = field(default_factory=list)
    rejected_candidates: list[dict] = field(default_factory=list)
    failure_reason: str | None = None
