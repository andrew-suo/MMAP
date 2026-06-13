from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.fewshot.schema import FewShotCandidate


@dataclass
class FewShotCandidateState:
    candidate_id: str
    sample_id: str
    source_round_id: str
    status: str = "active"
    difficulty_ema_at_mining: float = 0.0
    candidate_score: float = 0.0
    last_tested_round_id: str | None = None
    best_accuracy_delta: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    accepted_round_id: str | None = None


@dataclass
class FewShotCandidatePool:
    id: str = "fewshot_candidate_pool"
    candidates: dict[str, FewShotCandidateState] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "FewShotCandidatePool":
        if not data:
            return cls()
        candidates: dict[str, FewShotCandidateState] = {}
        raw_candidates = data.get("candidates", {}) if isinstance(data, dict) else {}
        for candidate_id, raw in raw_candidates.items():
            if isinstance(raw, dict):
                candidates[candidate_id] = FewShotCandidateState(**raw)
        return cls(id=data.get("id", "fewshot_candidate_pool"), candidates=candidates)

    def add_mined(self, *, round_id: str, candidate: FewShotCandidate, difficulty_ema: float = 0.0) -> None:
        existing = self.candidates.get(candidate.id)
        if existing is None:
            self.candidates[candidate.id] = FewShotCandidateState(
                candidate_id=candidate.id,
                sample_id=candidate.sample_id,
                source_round_id=round_id,
                difficulty_ema_at_mining=difficulty_ema,
                candidate_score=candidate.candidate_score,
            )
            return
        existing.candidate_score = max(existing.candidate_score, candidate.candidate_score)
        if existing.status == "rejected_retryable":
            existing.status = "active"

    def eligible_candidates(self) -> list[FewShotCandidate]:
        eligible_statuses = {"active", "rejected_retryable"}
        states = [state for state in self.candidates.values() if state.status in eligible_statuses]
        states.sort(key=lambda state: (state.best_accuracy_delta, state.candidate_score, state.difficulty_ema_at_mining), reverse=True)
        return [FewShotCandidate(id=state.candidate_id, sample_id=state.sample_id, candidate_score=state.candidate_score, status=state.status) for state in states]

    def mark_tested(
        self,
        *,
        candidate_id: str,
        round_id: str,
        accuracy_delta: float,
        accepted: bool,
        rejection_reason: str | None = None,
        broken_sample_ids: list[str] | None = None,
    ) -> None:
        state = self.candidates.get(candidate_id)
        if state is None:
            return
        state.last_tested_round_id = round_id
        state.best_accuracy_delta = max(state.best_accuracy_delta, accuracy_delta)
        state.broken_sample_ids = broken_sample_ids or []
        if accepted:
            state.status = "accepted"
            state.accepted_round_id = round_id
            return
        state.status = "rejected_retryable" if not broken_sample_ids else "rejected"
        if rejection_reason:
            state.rejection_reasons.append(rejection_reason)
