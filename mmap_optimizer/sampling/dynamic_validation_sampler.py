from __future__ import annotations

import random
from dataclasses import dataclass, field

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleState


@dataclass
class DynamicValidationBatch:
    id: str
    round_id: str
    sample_ids: list[str]
    composition: dict[str, dict[str, int]] = field(default_factory=dict)
    rolling_window_coverage_satisfied: bool = True
    overlap_ratio: float = 0.0


def _label(gt: GroundTruth | None) -> str:
    return str(gt.primary_answer if gt else "UNKNOWN")


def select_dynamic_validation_batch(
    *, round_id: str, samples: list[Sample], ground_truths: dict[str, GroundTruth], sample_states: dict[str, SampleState], batch_size: int, exclude_sample_ids: set[str] | None = None, seed: int = 0
) -> DynamicValidationBatch:
    rng = random.Random(seed)
    exclude_sample_ids = exclude_sample_ids or set()
    candidates = [s for s in samples if s.active and s.id not in exclude_sample_ids]
    scored: list[tuple[float, Sample]] = []
    for sample in candidates:
        state = sample_states.get(sample.id, SampleState(sample_id=sample.id))
        weight = 1.0
        if state.difficulty_ema < 0.05 and state.consecutive_correct_count >= 5 and state.fragility_score == 0:
            weight *= 0.2
        if state.difficulty_ema >= 0.5 and state.selected_count_recent_window >= 2:
            weight *= 0.1
        scored.append((rng.random() * weight, sample))
    selected = [sample for _, sample in sorted(scored, key=lambda x: x[0], reverse=True)[:batch_size]]
    by_label: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    for sample in selected:
        gt = ground_truths.get(sample.ground_truth_id)
        by_label[_label(gt)] = by_label.get(_label(gt), 0) + 1
        bin_name = sample_states.get(sample.id, SampleState(sample_id=sample.id)).difficulty_bin
        by_difficulty[bin_name] = by_difficulty.get(bin_name, 0) + 1
    return DynamicValidationBatch(
        id=f"dval_{round_id}", round_id=round_id, sample_ids=[s.id for s in selected], composition={"by_label": by_label, "by_difficulty": by_difficulty}
    )
