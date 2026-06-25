"""Trace2Skill-inspired sampling strategy tests."""

from __future__ import annotations

from pathlib import Path

from mmap_optimizer.data.sample import SampleSet, SampleSpec, SampleState
from mmap_optimizer.data.sampler import SamplerConfig, create_sampler
from mmap_optimizer.phases.prompt_optimization import MultiSeedConfig, PromptOptimizationConfig, PromptOptimizationPhase
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


def test_phase_builds_multi_seed_candidate_batches(tmp_path: Path):
    config = PromptOptimizationConfig(
        rounds=1,
        initial_batch_size=3,
        min_batch_size=3,
        max_batch_size=3,
        multi_seed=MultiSeedConfig(enabled=True, seed_count=2),
    )
    phase = PromptOptimizationPhase(
        config=config,
        extraction_prompt=_prompt(),
        analysis_prompt=_prompt(),
        sample_set=_sample_set(),
        output_dir=tmp_path,
        seed=11,
        executors={},
    )
    optimization_batch = phase._sampling_stage(1)

    candidate_batches = phase._candidate_sampling_stage(optimization_batch, 1)

    assert len(candidate_batches) == 2
    assert candidate_batches[0].metadata["seed_index"] == 1
    assert candidate_batches[1].metadata["seed_index"] == 2
    assert all(batch.phase == "prompt_optimization_candidate" for batch in candidate_batches)
