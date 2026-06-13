from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleState
from mmap_optimizer.sampling.dynamic_validation_sampler import select_dynamic_validation_batch


def _sample(sample_id: str, label: str) -> tuple[Sample, GroundTruth]:
    gt_id = f"gt_{sample_id}"
    return Sample(id=sample_id, ground_truth_id=gt_id), GroundTruth(
        id=gt_id,
        sample_id=sample_id,
        value={"result": label},
        primary_answer=label,
    )


def test_dynamic_validation_sampler_covers_labels_and_difficulty_bins():
    pairs = [_sample("s_easy_ok", "OK"), _sample("s_medium_ng", "NG"), _sample("s_hard_uncertain", "UNCERTAIN")]
    samples = [sample for sample, _ in pairs]
    ground_truths = {gt.id: gt for _, gt in pairs}
    states = {
        "s_easy_ok": SampleState(sample_id="s_easy_ok", difficulty_ema=0.0),
        "s_medium_ng": SampleState(sample_id="s_medium_ng", difficulty_ema=0.2),
        "s_hard_uncertain": SampleState(sample_id="s_hard_uncertain", difficulty_ema=0.8),
    }

    batch = select_dynamic_validation_batch(
        round_id="round_000001",
        samples=samples,
        ground_truths=ground_truths,
        sample_states=states,
        batch_size=3,
        seed=1,
        round_index=1,
    )

    assert set(batch.sample_ids) == {"s_easy_ok", "s_medium_ng", "s_hard_uncertain"}
    assert batch.composition["by_label"] == {"OK": 1, "NG": 1, "UNCERTAIN": 1}
    assert batch.composition["by_difficulty"] == {"easy": 1, "medium": 1, "hard": 1}
    assert batch.coverage_targets == {"labels": ["NG", "OK", "UNCERTAIN"], "difficulty_bins": ["easy", "medium", "hard"]}
    assert batch.rolling_window_coverage_satisfied is True
    assert batch.overlap_ratio == 0.0


def test_dynamic_validation_sampler_avoids_recent_overselected_samples_when_possible():
    pairs = [_sample("recent_a", "OK"), _sample("recent_b", "OK"), _sample("cold_a", "OK"), _sample("cold_b", "OK")]
    samples = [sample for sample, _ in pairs]
    ground_truths = {gt.id: gt for _, gt in pairs}
    states = {
        "recent_a": SampleState(sample_id="recent_a", difficulty_ema=0.7, last_selected_round=4, selected_count_recent_window=2),
        "recent_b": SampleState(sample_id="recent_b", difficulty_ema=0.7, last_selected_round=4, selected_count_recent_window=2),
        "cold_a": SampleState(sample_id="cold_a", difficulty_ema=0.1),
        "cold_b": SampleState(sample_id="cold_b", difficulty_ema=0.1),
    }

    batch = select_dynamic_validation_batch(
        round_id="round_000005",
        samples=samples,
        ground_truths=ground_truths,
        sample_states=states,
        batch_size=2,
        seed=5,
        round_index=5,
        cover_difficulty_bins=False,
        recent_window_rounds=3,
        max_recent_selections=1,
    )

    assert set(batch.sample_ids) == {"cold_a", "cold_b"}
    assert batch.recent_sample_ids == []
    assert batch.overlap_ratio == 0.0
