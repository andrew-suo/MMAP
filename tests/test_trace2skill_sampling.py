"""Trace2Skill-inspired sampling strategy tests."""

from __future__ import annotations

from mmap_optimizer.data.sample import (
    SampleOutcomeHistoryItem,
    SampleOptimizationTrajectory,
    SamplePatchAttempt,
    SampleSet,
    SampleSpec,
    SampleState,
)
from mmap_optimizer.data.sampler import SamplerConfig, create_sampler
from mmap_optimizer.core.config import RefactoredConfig
from mmap_optimizer.prompt.structured_prompt import PromptSection, StructuredPrompt


def _sample_set() -> SampleSet:
    sample_set = SampleSet()
    for idx in range(8):
        sid = f"s{idx}"
        sample_set.add_spec(SampleSpec(id=sid, input={}, ground_truth={}))
        state = sample_set.states[sid]
        if idx < 3:
            state.last_extraction_status = "wrong"
            state.error_ema = 0.9 - idx * 0.1
            state.difficulty_score = state.error_ema
        elif idx < 5:
            state.last_extraction_status = "correct"
            state.frequency_score = 1.0
        else:
            state.frequency_score = 1.0 + idx * 0.1
    return sample_set


def _prompt() -> StructuredPrompt:
    return StructuredPrompt(
        id="p",
        prompt_type="extraction",
        sections=[
            PromptSection(
                id="task",
                title="Task",
                level=1,
                content="Extract.",
                mutable=True,
            )
        ],
        raw_markdown="# Task\nExtract.",
        version=1,
    )


def test_balanced_trace_sampler_records_pool_counts():
    sampler = create_sampler(
        SamplerConfig(
            type="balanced_trace",
            error_ratio=0.5,
            success_ratio=0.25,
            low_frequency_ratio=0.25,
        )
    )

    batch = sampler.sample(_sample_set(), batch_size=4, iteration=1, seed=7)

    assert len(batch.sample_ids) == 4
    assert batch.sampler_name == "balanced_trace"
    assert batch.metadata["pool_counts"]["error"] >= 1
    assert batch.metadata["pool_counts"]["success"] >= 1
    assert "requested_ratios" in batch.metadata


def test_validation_sampling_excludes_optimization_batch():
    sample_set = _sample_set()
    sampler = create_sampler(SamplerConfig(type="difficulty_frequency"))
    optimization_batch = sampler.sample(sample_set, batch_size=3, iteration=1, seed=1)
    validation_batch = sampler.sample_validation(
        sample_set,
        batch_size=3,
        iteration=1,
        seed=100,
        excluded_sample_ids=set(optimization_batch.sample_ids),
    )

    assert validation_batch.phase == "prompt_optimization_validation"
    assert set(validation_batch.sample_ids).isdisjoint(optimization_batch.sample_ids)


def test_sample_outcome_history_round_trips_and_trims_by_prompt_type():
    state = SampleState(sample_id="s1")
    for idx in range(25):
        state.add_outcome_history(
            SampleOutcomeHistoryItem(
                sample_id="s1",
                prompt_type="extraction",
                iteration=idx,
                status="pass" if idx % 2 == 0 else "fail",
            )
        )
    state.add_outcome_history(
        SampleOutcomeHistoryItem(
            sample_id="s1",
            prompt_type="analysis",
            iteration=1,
            status="fail",
        )
    )

    restored = SampleState.from_dict(state.to_dict())

    assert len(restored.get_outcome_history("extraction")) == 20
    assert restored.get_outcome_history("extraction")[0].iteration == 5
    assert restored.get_outcome_history("analysis")[0].status == "fail"


def test_apex_trace_sampler_prioritizes_mixed_fail_pool():
    sample_set = SampleSet()
    for sid in ("mixed", "hard", "easy", "unknown", "mixed2", "hard2"):
        sample_set.add_spec(SampleSpec(id=sid, input={}, ground_truth={}))

    for sid in ("mixed", "mixed2"):
        state = sample_set.states[sid]
        state.add_outcome_history(SampleOutcomeHistoryItem(sid, "extraction", 1, "pass"))
        state.add_outcome_history(SampleOutcomeHistoryItem(sid, "extraction", 2, "fail"))
        trajectory = SampleOptimizationTrajectory(
            sample_id=sid,
            prompt_type="extraction",
            iteration=2,
            sample_transition="fixed",
        )
        trajectory.add_patch_attempt(
            SamplePatchAttempt(
                patch_id=f"p-{sid}",
                prompt_type="extraction",
                iteration=2,
                target_section_id="task",
                operation_type="replace",
                final_decision="accepted",
                regression_effect="fixed",
            )
        )
        state.add_optimization_trajectory(trajectory)

    for sid in ("hard", "hard2"):
        state = sample_set.states[sid]
        state.add_outcome_history(SampleOutcomeHistoryItem(sid, "extraction", 1, "fail"))
        state.add_outcome_history(SampleOutcomeHistoryItem(sid, "extraction", 2, "fail"))
        state.difficulty_score = 0.9

    sample_set.states["easy"].add_outcome_history(
        SampleOutcomeHistoryItem("easy", "extraction", 1, "pass")
    )

    sampler = create_sampler(
        SamplerConfig(
            type="apex_trace",
            mixed_fail_ratio=0.5,
            hard_fail_ratio=0.25,
            unknown_ratio=0.25,
            easy_ratio=0.0,
            random_noise_scale=0.0,
        )
    )

    batch = sampler.sample(sample_set, batch_size=4, iteration=3, seed=1)

    assert batch.sampler_name == "apex_trace"
    assert batch.metadata["apex_pool_counts"]["mixed_fail"] == 2
    assert set(batch.sample_ids[:2]) == {"mixed", "mixed2"}
    assert batch.scores["mixed"]["apex_classification"] == "mixed_fail"
    assert "trajectory_score" in batch.scores["mixed"]
    assert batch.metadata["lookback_window"] == 5


def test_apex_trace_sampler_keeps_prompt_type_histories_separate():
    sample_set = SampleSet()
    for sid in ("mixed_extraction", "analysis_only"):
        sample_set.add_spec(SampleSpec(id=sid, input={}, ground_truth={}))

    extraction_state = sample_set.states["mixed_extraction"]
    extraction_state.add_outcome_history(
        SampleOutcomeHistoryItem("mixed_extraction", "extraction", 1, "pass")
    )
    extraction_state.add_outcome_history(
        SampleOutcomeHistoryItem("mixed_extraction", "extraction", 2, "fail")
    )

    analysis_state = sample_set.states["analysis_only"]
    analysis_state.add_outcome_history(
        SampleOutcomeHistoryItem("analysis_only", "analysis", 1, "pass")
    )
    analysis_state.add_outcome_history(
        SampleOutcomeHistoryItem("analysis_only", "analysis", 2, "fail")
    )

    sampler = create_sampler(
        SamplerConfig(
            type="apex_trace",
            apex_prompt_type="extraction",
            mixed_fail_ratio=1.0,
            hard_fail_ratio=0.0,
            unknown_ratio=0.0,
            easy_ratio=0.0,
            random_noise_scale=0.0,
        )
    )

    batch = sampler.sample(sample_set, batch_size=1, iteration=3, seed=1)

    assert batch.sample_ids == ["mixed_extraction"]
    assert batch.scores["mixed_extraction"]["apex_classification"] == "mixed_fail"
    assert batch.scores["mixed_extraction"]["recent_statuses_by_prompt_type"] == {
        "extraction": ["pass", "fail"]
    }


def test_apex_trace_sampler_trajectory_score_filters_prompt_type():
    state = SampleState(sample_id="s1")

    extraction_trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="extraction",
        iteration=1,
    )
    extraction_trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p-ext",
            prompt_type="extraction",
            iteration=1,
            regression_effect="fixed",
            final_decision="accepted",
        )
    )
    state.add_optimization_trajectory(extraction_trajectory)

    analysis_trajectory = SampleOptimizationTrajectory(
        sample_id="s1",
        prompt_type="analysis",
        iteration=1,
    )
    analysis_trajectory.add_patch_attempt(
        SamplePatchAttempt(
            patch_id="p-ana",
            prompt_type="analysis",
            iteration=1,
            regression_effect="broken",
            final_decision="rejected",
            toxicity_status="toxic",
        )
    )
    state.add_optimization_trajectory(analysis_trajectory)

    extraction_sampler = create_sampler(
        SamplerConfig(type="apex_trace", apex_prompt_type="extraction")
    )
    analysis_sampler = create_sampler(
        SamplerConfig(type="apex_trace", apex_prompt_type="analysis")
    )

    assert extraction_sampler._trajectory_score(state) > 0
    assert analysis_sampler._trajectory_score(state) < 0


def test_apex_trace_recency_bonus_prefers_less_recently_selected_sample():
    sample_set = SampleSet()
    for sid in ("old", "recent"):
        sample_set.add_spec(SampleSpec(id=sid, input={}, ground_truth={}))
        sample_set.states[sid].add_outcome_history(
            SampleOutcomeHistoryItem(sid, "extraction", 1, "fail")
        )
        sample_set.states[sid].difficulty_score = 0.5
        sample_set.states[sid].frequency_score = 0.5

    sample_set.states["old"].last_selected_iteration = 1
    sample_set.states["recent"].last_selected_iteration = 9

    sampler = create_sampler(
        SamplerConfig(
            type="apex_trace",
            apex_prompt_type="extraction",
            hard_fail_ratio=1.0,
            mixed_fail_ratio=0.0,
            unknown_ratio=0.0,
            easy_ratio=0.0,
            random_noise_scale=0.0,
        )
    )

    batch = sampler.sample(sample_set, batch_size=1, iteration=10, seed=1)

    assert batch.sample_ids == ["old"]


def test_top_level_sampling_random_noise_scale_config_is_honored():
    config = RefactoredConfig.from_dict({
        "sampling": {
            "type": "apex_trace",
            "random_noise_scale": 0.123,
            "apex_prompt_type": "analysis",
        }
    })

    assert config.sampling.random_noise_scale == 0.123
    assert config.sampling.apex_prompt_type == "analysis"
