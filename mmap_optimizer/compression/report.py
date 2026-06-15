from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompressionReport:
    id: str
    round_id: str
    prompt_type: str
    prompt_version_before_id: str
    triggered: bool
    reason: str
    candidate_sections: list[dict] = field(default_factory=list)
    accepted: bool = False
    compression_patch_id: str | None = None
    line_count_before: int = 0
    line_count_after: int | None = None
    prompt_version_after_id: str | None = None
    line_budget: int | None = None
    compressed_section_id: str | None = None
    line_reduction: int = 0
    semantic_check_passed: bool = False
    behavior_check_passed: bool = False
    rejected_sections: list[dict] = field(default_factory=list)
    failure_reason: str | None = None
