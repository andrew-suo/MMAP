from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SampleAsset:
    id: str
    sample_id: str
    type: str = "image"
    uri: str | None = None
    local_path: str | None = None
    mime_type: str | None = None
    hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundTruth:
    id: str
    sample_id: str
    value: dict[str, Any]
    primary_answer: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Sample:
    id: str
    ground_truth_id: str
    asset_ids: list[str] = field(default_factory=list)
    text_context: str | None = None
    structured_context: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    active: bool = True


@dataclass
class SampleState:
    sample_id: str
    difficulty_ema: float = 0.0
    fragility_score: float = 0.0
    selected_count_recent_window: int = 0
    last_selected_round: int | None = None
    historical_fixed: bool = False
    toxic_trigger: bool = False
    consecutive_correct_count: int = 0
    consecutive_wrong_count: int = 0

    @property
    def difficulty_bin(self) -> str:
        if self.difficulty_ema < 0.1:
            return "easy"
        if self.difficulty_ema < 0.5:
            return "medium"
        return "hard"
