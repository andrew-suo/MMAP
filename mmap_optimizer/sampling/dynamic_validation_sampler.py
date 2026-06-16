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
    coverage_targets: dict[str, list[str]] = field(default_factory=dict)
    coverage_warnings: list[str] = field(default_factory=list)
    recent_sample_ids: list[str] = field(default_factory=list)


def _label(gt: GroundTruth | None) -> str:
    return str(gt.primary_answer if gt else "UNKNOWN")


def _state(sample: Sample, sample_states: dict[str, SampleState]) -> SampleState:
    return sample_states.get(sample.id, SampleState(sample_id=sample.id))


def _recently_selected(state: SampleState, *, round_index: int | None, recent_window_rounds: int) -> bool:
    if round_index is None or state.last_selected_round is None:
        return False
    return 0 <= round_index - state.last_selected_round <= recent_window_rounds


def _sample_score(
    sample: Sample,
    *,
    state: SampleState,
    rng: random.Random,
    round_index: int | None,
    recent_window_rounds: int,
    max_recent_selections: int,
) -> float:
    score = rng.random()
    score += min(max(state.difficulty_ema, 0.0), 1.0)
    score += min(max(state.fragility_score, 0.0), 1.0) * 0.5
    if state.difficulty_ema < 0.05 and state.consecutive_correct_count >= 5 and state.fragility_score == 0:
        score -= 0.75
    if _recently_selected(state, round_index=round_index, recent_window_rounds=recent_window_rounds):
        score -= 1.0
        if state.selected_count_recent_window >= max_recent_selections:
            score -= 2.0
    if state.difficulty_ema >= 0.5 and state.selected_count_recent_window >= max_recent_selections:
        score -= 0.5
    return score


def _add_best_from_group(
    *,
    selected: list[Sample],
    selected_ids: set[str],
    group: list[Sample],
    scores: dict[str, float],
    batch_size: int,
) -> None:
    if len(selected) >= batch_size:
        return
    available = [sample for sample in group if sample.id not in selected_ids]
    if not available:
        return
    best = max(available, key=lambda sample: (scores[sample.id], sample.id))
    selected.append(best)
    selected_ids.add(best.id)


def select_dynamic_validation_batch(
    *,
    round_id: str,
    samples: list[Sample],
    ground_truths: dict[str, GroundTruth],
    sample_states: dict[str, SampleState],
    batch_size: int,
    exclude_sample_ids: set[str] | None = None,
    seed: int = 0,
    round_index: int | None = None,
    min_label_count: int = 1,
    cover_difficulty_bins: bool = True,
    recent_window_rounds: int = 3,
    max_recent_selections: int = 1,
) -> DynamicValidationBatch:
    rng = random.Random(seed)
    exclude_sample_ids = exclude_sample_ids or set()
    coverage_warnings: list[str] = []
    if batch_size <= 0:
        return DynamicValidationBatch(id=f"dval_{round_id}", round_id=round_id, sample_ids=[])

    candidates = [sample for sample in samples if sample.active and sample.id not in exclude_sample_ids]

    # Handle empty candidate pool
    if not candidates:
        coverage_warnings.append("NO_CANDIDATES_AVAILABLE")
        return DynamicValidationBatch(
            id=f"dval_{round_id}",
            round_id=round_id,
            sample_ids=[],
            rolling_window_coverage_satisfied=False,
            coverage_warnings=coverage_warnings,
        )

    # Warn when candidates are insufficient
    if len(candidates) < batch_size:
        coverage_warnings.append(f"CANDIDATES_INSUFFICIENT:{len(candidates)}<batch_size({batch_size})")
    scores = {
        sample.id: _sample_score(
            sample,
            state=_state(sample, sample_states),
            rng=rng,
            round_index=round_index,
            recent_window_rounds=recent_window_rounds,
            max_recent_selections=max_recent_selections,
        )
        for sample in candidates
    }
    by_label_samples: dict[str, list[Sample]] = {}
    by_difficulty_samples: dict[str, list[Sample]] = {}
    for sample in candidates:
        by_label_samples.setdefault(_label(ground_truths.get(sample.ground_truth_id)), []).append(sample)
        by_difficulty_samples.setdefault(_state(sample, sample_states).difficulty_bin, []).append(sample)

    selected: list[Sample] = []
    selected_ids: set[str] = set()
    labels_to_cover = sorted(by_label_samples)
    difficulty_bins_to_cover = [bin_name for bin_name in ["easy", "medium", "hard"] if bin_name in by_difficulty_samples]

    for label in labels_to_cover:
        for _ in range(max(0, min_label_count)):
            if len(selected) >= batch_size:
                coverage_warnings.append("LABEL_COVERAGE_TRUNCATED_BY_BATCH_SIZE")
                break
            _add_best_from_group(
                selected=selected,
                selected_ids=selected_ids,
                group=by_label_samples[label],
                scores=scores,
                batch_size=batch_size,
            )

    if cover_difficulty_bins:
        for bin_name in difficulty_bins_to_cover:
            if len(selected) >= batch_size:
                coverage_warnings.append("DIFFICULTY_COVERAGE_TRUNCATED_BY_BATCH_SIZE")
                break
            if any(_state(sample, sample_states).difficulty_bin == bin_name for sample in selected):
                continue
            _add_best_from_group(
                selected=selected,
                selected_ids=selected_ids,
                group=by_difficulty_samples[bin_name],
                scores=scores,
                batch_size=batch_size,
            )

    remaining = [sample for sample in candidates if sample.id not in selected_ids]
    remaining.sort(key=lambda sample: (scores[sample.id], sample.id), reverse=True)
    for sample in remaining[: max(0, batch_size - len(selected))]:
        selected.append(sample)
        selected_ids.add(sample.id)

    by_label: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    recent_sample_ids: list[str] = []
    for sample in selected:
        gt = ground_truths.get(sample.ground_truth_id)
        label = _label(gt)
        by_label[label] = by_label.get(label, 0) + 1
        state = _state(sample, sample_states)
        by_difficulty[state.difficulty_bin] = by_difficulty.get(state.difficulty_bin, 0) + 1
        if _recently_selected(state, round_index=round_index, recent_window_rounds=recent_window_rounds):
            recent_sample_ids.append(sample.id)

    missing_labels = [label for label in labels_to_cover if by_label.get(label, 0) < min_label_count]
    missing_bins = [
        bin_name
        for bin_name in difficulty_bins_to_cover
        if cover_difficulty_bins and by_difficulty.get(bin_name, 0) == 0
    ]
    if missing_labels:
        coverage_warnings.append(f"MISSING_LABELS:{','.join(missing_labels)}")
    if missing_bins:
        coverage_warnings.append(f"MISSING_DIFFICULTY_BINS:{','.join(missing_bins)}")
    rolling_window_coverage_satisfied = not missing_labels and not missing_bins
    overlap_ratio = (len(recent_sample_ids) / len(selected)) if selected else 0.0
    return DynamicValidationBatch(
        id=f"dval_{round_id}",
        round_id=round_id,
        sample_ids=[sample.id for sample in selected],
        composition={"by_label": by_label, "by_difficulty": by_difficulty},
        rolling_window_coverage_satisfied=rolling_window_coverage_satisfied,
        overlap_ratio=overlap_ratio,
        coverage_targets={"labels": labels_to_cover, "difficulty_bins": difficulty_bins_to_cover},
        coverage_warnings=coverage_warnings,
        recent_sample_ids=recent_sample_ids,
    )
