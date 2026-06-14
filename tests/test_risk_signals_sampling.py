"""Contract tests for :mod:`mmap_optimizer.sampling.risk_signals`.

These tests focus on the behavior of the lightweight risk signal helpers:

* sample-level risk score computation from ``SampleState``-like inputs
* deterministic risk level bucketing
* EMA update stability (difficulty_ema and fragility_score)
* section-level risk scoring (PR #3 formula, absorbed as a helper)
* deterministic ranking (risk_score desc, last_selected_round asc/missing-first,
  sample_id ASCII tie break)
* risk-weighted batch selection respecting batch_size / exclusion
* JSON serialization round-tripping

No test references compression, patch merging, executors, runners, prompts or
other PR #3 functionality that is explicitly out of scope for this integration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.dataset.sample import Sample, SampleState
from mmap_optimizer.sampling.risk_signals import (
    RISK_LEVEL_HIGH,
    RISK_LEVEL_HIGH_THRESHOLD,
    RISK_LEVEL_LOW,
    RISK_LEVEL_LOW_THRESHOLD,
    RISK_LEVEL_MEDIUM,
    RISK_ARTIFACT_FILENAME,
    SampleRiskSignal,
    build_sample_risk_signal,
    compute_risk_signals,
    compute_sample_risk_level,
    compute_sample_risk_score,
    compute_section_risk_score,
    rank_samples_by_risk,
    sample_risk_signals_to_json,
    select_risk_weighted_batch,
    update_difficulty_ema,
    update_fragility_score,
    write_sample_risk_artifact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample(sample_id: str, *, active: bool = True) -> Sample:
    return Sample(id=sample_id, ground_truth_id=f"gt_{sample_id}", active=active)


def _state(
    sample_id: str,
    *,
    difficulty_ema: float = 0.0,
    fragility_score: float = 0.0,
    consecutive_wrong_count: int = 0,
    toxic_trigger: bool = False,
    historical_fixed: bool = False,
    last_selected_round: int | None = None,
) -> SampleState:
    state = SampleState(sample_id=sample_id)
    state.difficulty_ema = difficulty_ema
    state.fragility_score = fragility_score
    state.consecutive_wrong_count = consecutive_wrong_count
    state.toxic_trigger = toxic_trigger
    state.historical_fixed = historical_fixed
    state.last_selected_round = last_selected_round
    return state


# ---------------------------------------------------------------------------
# Risk score computation
# ---------------------------------------------------------------------------


class TestComputeSampleRiskScore:
    def test_zero_state_returns_zero(self):
        score, reasons = compute_sample_risk_score(_state("s1"))
        assert score == pytest.approx(0.0, abs=1e-6)
        assert reasons == []

    def test_high_difficulty_ema_increases_score(self):
        score, reasons = compute_sample_risk_score(_state("s1", difficulty_ema=1.0))
        assert score >= 0.4
        assert "high_difficulty_ema" in reasons

    def test_high_fragility_increases_score(self):
        score, reasons = compute_sample_risk_score(_state("s1", fragility_score=1.0))
        assert score >= 0.3
        assert "high_fragility_score" in reasons

    def test_consecutive_wrong_increases_score(self):
        score, reasons = compute_sample_risk_score(
            _state("s1", consecutive_wrong_count=10)
        )
        assert score >= 0.2
        assert "consecutive_wrong_responses" in reasons

    def test_toxic_trigger_increases_score(self):
        score, reasons = compute_sample_risk_score(_state("s1", toxic_trigger=True))
        assert score >= 0.1
        assert "toxic_trigger" in reasons

    def test_historical_fixed_increases_score(self):
        score, reasons = compute_sample_risk_score(_state("s1", historical_fixed=True))
        assert score > 0.0
        assert "historical_fixed_sample" in reasons

    def test_score_is_clamped_to_unit_interval(self):
        """Multiple high-risk flags must be clamped to ``[0, 1]``."""

        score, _ = compute_sample_risk_score(
            _state(
                "s1",
                difficulty_ema=1.0,
                fragility_score=1.0,
                consecutive_wrong_count=10,
                toxic_trigger=True,
                historical_fixed=True,
            )
        )
        assert 0.0 <= score <= 1.0

    def test_accepts_dict_input(self):
        score, reasons = compute_sample_risk_score(
            {"difficulty_ema": 1.0, "fragility_score": 0.0, "consecutive_wrong_count": 0}
        )
        assert score == pytest.approx(0.4, abs=1e-6)
        assert "high_difficulty_ema" in reasons


class TestRiskLevelBucketing:
    def test_low_below_threshold(self):
        assert compute_sample_risk_level(0.0) == RISK_LEVEL_LOW
        assert compute_sample_risk_level(RISK_LEVEL_LOW_THRESHOLD - 0.01) == RISK_LEVEL_LOW

    def test_medium_between_thresholds(self):
        assert compute_sample_risk_level(RISK_LEVEL_LOW_THRESHOLD) == RISK_LEVEL_MEDIUM
        assert compute_sample_risk_level(0.5) == RISK_LEVEL_MEDIUM
        assert compute_sample_risk_level(RISK_LEVEL_HIGH_THRESHOLD - 0.01) == RISK_LEVEL_MEDIUM

    def test_high_at_or_above_threshold(self):
        assert compute_sample_risk_level(RISK_LEVEL_HIGH_THRESHOLD) == RISK_LEVEL_HIGH
        assert compute_sample_risk_level(1.0) == RISK_LEVEL_HIGH


# ---------------------------------------------------------------------------
# EMA updates
# ---------------------------------------------------------------------------


class TestDifficultyEmaUpdate:
    def test_correct_response_pulls_down(self):
        new_val = update_difficulty_ema(0.8, True, alpha=0.5)
        assert new_val < 0.8

    def test_wrong_response_pulls_up(self):
        new_val = update_difficulty_ema(0.2, False, alpha=0.5)
        assert new_val > 0.2

    def test_converges_to_zero_with_repeated_correct(self):
        val = 1.0
        for _ in range(50):
            val = update_difficulty_ema(val, True, alpha=0.35)
        assert val < 0.05

    def test_converges_to_one_with_repeated_wrong(self):
        val = 0.0
        for _ in range(50):
            val = update_difficulty_ema(val, False, alpha=0.35)
        assert val > 0.95

    def test_alpha_one_replaces_value(self):
        assert update_difficulty_ema(0.3, True, alpha=1.0) == pytest.approx(0.0)
        assert update_difficulty_ema(0.3, False, alpha=1.0) == pytest.approx(1.0)

    def test_stays_within_unit_interval(self):
        for val in (0.0, 0.5, 1.0):
            for flag in (True, False):
                out = update_difficulty_ema(val, flag)
                assert 0.0 <= out <= 1.0

    def test_stable_on_repeated_zero(self):
        """Multiple consecutive correct on a zero EMA stays near zero."""

        val = 0.0
        for _ in range(10):
            val = update_difficulty_ema(val, True, alpha=0.35)
        assert val == pytest.approx(0.0, abs=1e-4)


class TestFragilityScoreUpdate:
    def test_correct_decays_fragility(self):
        val = update_fragility_score(0.8, True, alpha=0.25)
        assert val < 0.8

    def test_wrong_increases_fragility(self):
        val = update_fragility_score(0.2, False, alpha=0.25)
        assert val > 0.2

    def test_converges_to_zero_over_time(self):
        val = 1.0
        for _ in range(50):
            val = update_fragility_score(val, True, alpha=0.25)
        assert val < 0.01

    def test_converges_to_one_over_time(self):
        val = 0.0
        for _ in range(50):
            val = update_fragility_score(val, False, alpha=0.25)
        assert val > 0.9

    def test_stays_within_unit_interval(self):
        for val in (0.0, 0.5, 1.0):
            for flag in (True, False):
                out = update_fragility_score(val, flag)
                assert 0.0 <= out <= 1.0

    def test_asymmetric_learning(self):
        """Fragility should increase faster on wrong than it decays on correct."""

        # Starting from 0.1, a wrong increases more than a correct decreases.
        after_wrong = update_fragility_score(0.1, False, alpha=0.25)
        after_correct = update_fragility_score(0.1, True, alpha=0.25)
        delta_wrong = after_wrong - 0.1
        delta_correct = 0.1 - after_correct
        assert delta_wrong > delta_correct


# ---------------------------------------------------------------------------
# Section risk
# ---------------------------------------------------------------------------


class TestSectionRiskScore:
    def test_zero_parasite_and_max_accuracy_yields_low_risk(self):
        score = compute_section_risk_score(cited=0.0, parasite=0.0, accuracy=1.0)
        assert score == pytest.approx(0.0)

    def test_high_parasite_yields_high_risk(self):
        score = compute_section_risk_score(cited=0.0, parasite=1.0, accuracy=1.0)
        assert score >= 0.4

    def test_low_accuracy_yields_medium_risk(self):
        score = compute_section_risk_score(cited=0.0, parasite=0.0, accuracy=0.0)
        assert score == pytest.approx(0.2)

    def test_values_clamped_to_unit(self):
        score = compute_section_risk_score(cited=10.0, parasite=10.0, accuracy=-5.0)
        assert 0.0 <= score <= 1.0

    def test_combined_signals(self):
        score = compute_section_risk_score(cited=1.0, parasite=1.0, accuracy=0.0)
        assert score >= 0.8


# ---------------------------------------------------------------------------
# Build sample risk signal
# ---------------------------------------------------------------------------


class TestBuildSampleRiskSignal:
    def test_basic_sample_risk_signal(self):
        sample = _sample("s1")
        state = _state("s1", difficulty_ema=0.8, toxic_trigger=True)
        signal = build_sample_risk_signal(sample, state)
        assert signal.sample_id == "s1"
        assert signal.risk_score > 0.3
        assert signal.risk_level in (RISK_LEVEL_MEDIUM, RISK_LEVEL_HIGH)
        assert signal.difficulty_ema == pytest.approx(0.8)
        assert "high_difficulty_ema" in signal.reasons
        assert "toxic_trigger" in signal.reasons

    def test_accepts_dict_samples(self):
        signal = build_sample_risk_signal(
            {"id": "s2"}, {"difficulty_ema": 0.2, "fragility_score": 0.1}
        )
        assert signal.sample_id == "s2"
        assert signal.risk_level == RISK_LEVEL_LOW

    def test_section_risk_nudge(self):
        sample = _sample("s1")
        # Attach section info via metadata so section_risk_scores can nudge.
        sample.metadata = {"section_ids": ["rules"]}
        state = _state("s1", difficulty_ema=0.5)
        baseline = build_sample_risk_signal(sample, state)
        nudged = build_sample_risk_signal(
            sample, state, section_risk_scores={"rules": 0.8}
        )
        assert nudged.risk_score > baseline.risk_score

    def test_metadata_contains_components(self):
        signal = build_sample_risk_signal(
            _sample("s1"), _state("s1", difficulty_ema=0.6, fragility_score=0.2)
        )
        assert "components" in signal.metadata

    def test_to_dict_round_trips(self):
        signal = build_sample_risk_signal(
            _sample("s1"), _state("s1", difficulty_ema=0.3, last_selected_round=5)
        )
        payload = signal.to_dict()
        restored = json.loads(json.dumps(payload))
        assert restored["sample_id"] == "s1"
        assert restored["risk_score"] == pytest.approx(signal.risk_score)
        assert restored["risk_level"] == signal.risk_level
        assert restored["last_selected_round"] == 5


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRankSamplesByRisk:
    def test_ranks_highest_risk_first(self):
        samples = [_sample("s1"), _sample("s2"), _sample("s3")]
        states = {
            "s1": _state("s1", difficulty_ema=0.0),
            "s2": _state("s2", difficulty_ema=1.0),
            "s3": _state("s3", difficulty_ema=0.5),
        }
        ranked = rank_samples_by_risk(samples, states)
        assert [s.sample_id for s in ranked] == ["s2", "s3", "s1"]
        assert ranked[0].risk_score > ranked[-1].risk_score

    def test_tie_on_risk_uses_last_selected_round(self):
        samples = [_sample("s1"), _sample("s2")]
        states = {
            "s1": _state("s1", difficulty_ema=0.5, last_selected_round=10),
            "s2": _state("s2", difficulty_ema=0.5, last_selected_round=None),
        }
        ranked = rank_samples_by_risk(samples, states)
        # Never-selected sample should come before recently-selected one when
        # risk scores tie.
        assert ranked[0].last_selected_round is None
        assert ranked[1].last_selected_round == 10

    def test_final_tie_breaker_is_sample_id(self):
        samples = [_sample("z"), _sample("a"), _sample("m")]
        # All identical (zero-risk) states.
        states = {
            "z": _state("z"),
            "a": _state("a"),
            "m": _state("m"),
        }
        ranked = rank_samples_by_risk(samples, states)
        assert [s.sample_id for s in ranked] == ["a", "m", "z"]

    def test_missing_state_is_treated_as_low_risk(self):
        samples = [_sample("known"), _sample("missing")]
        states = {"known": _state("known", difficulty_ema=1.0)}
        ranked = rank_samples_by_risk(samples, states)
        assert ranked[0].sample_id == "known"
        assert ranked[1].sample_id == "missing"
        assert ranked[1].risk_score == 0.0

    def test_empty_input_returns_empty(self):
        assert rank_samples_by_risk([], {}) == []

    def test_does_not_mutate_input_samples(self):
        sample = _sample("s1")
        state = _state("s1", difficulty_ema=0.3)
        # Ensure the input objects are not changed by the ranking call.
        before_id = sample.id
        before_difficulty = state.difficulty_ema
        rank_samples_by_risk([sample], {"s1": state})
        assert sample.id == before_id
        assert state.difficulty_ema == before_difficulty


# ---------------------------------------------------------------------------
# Batch selection
# ---------------------------------------------------------------------------


class TestSelectRiskWeightedBatch:
    def test_respects_batch_size(self):
        samples = [_sample(f"s{i}") for i in range(10)]
        states = {s.id: _state(s.id) for s in samples}
        batch = select_risk_weighted_batch(samples, states, batch_size=3)
        assert len(batch) == 3

    def test_returns_all_when_batch_larger_than_input(self):
        samples = [_sample(f"s{i}") for i in range(3)]
        states = {s.id: _state(s.id) for s in samples}
        batch = select_risk_weighted_batch(samples, states, batch_size=20)
        assert len(batch) == 3

    def test_zero_batch_size_returns_empty(self):
        samples = [_sample("s1")]
        assert select_risk_weighted_batch(samples, {"s1": _state("s1")}, 0) == []

    def test_excludes_ids(self):
        samples = [_sample("s1"), _sample("s2"), _sample("s3")]
        states = {
            "s1": _state("s1", difficulty_ema=1.0),
            "s2": _state("s2", difficulty_ema=0.5),
            "s3": _state("s3", difficulty_ema=0.0),
        }
        batch = select_risk_weighted_batch(
            samples, states, 2, exclude_sample_ids={"s1"}
        )
        assert all(s.sample_id != "s1" for s in batch)
        assert "s2" in [s.sample_id for s in batch]

    def test_selects_high_risk_first(self):
        samples = [_sample(f"s{i}") for i in range(5)]
        states = {
            "s0": _state("s0", difficulty_ema=0.1),
            "s1": _state("s1", difficulty_ema=0.9),
            "s2": _state("s2", difficulty_ema=0.2),
            "s3": _state("s3", difficulty_ema=1.0),
            "s4": _state("s4", difficulty_ema=0.0),
        }
        batch = select_risk_weighted_batch(samples, states, batch_size=2)
        assert [s.sample_id for s in batch] == ["s3", "s1"]


# ---------------------------------------------------------------------------
# Serialization + compute_risk_signals
# ---------------------------------------------------------------------------


class TestRiskSignalSerialization:
    def test_sample_risk_signals_to_json(self):
        signals = [
            SampleRiskSignal(
                sample_id="s1",
                risk_score=0.8,
                risk_level=RISK_LEVEL_HIGH,
                difficulty_ema=0.7,
                fragility_score=0.6,
                last_selected_round=5,
                reasons=["high_difficulty_ema"],
                metadata={"source": "unit-test"},
            )
        ]
        text = sample_risk_signals_to_json(signals)
        restored = json.loads(text)
        assert len(restored) == 1
        assert restored[0]["sample_id"] == "s1"
        assert restored[0]["risk_score"] == pytest.approx(0.8)
        assert restored[0]["risk_level"] == RISK_LEVEL_HIGH
        assert restored[0]["last_selected_round"] == 5
        assert restored[0]["reasons"] == ["high_difficulty_ema"]

    def test_write_sample_risk_artifact(self, tmp_path: Path):
        signals = [
            SampleRiskSignal(
                sample_id="s1",
                risk_score=0.5,
                risk_level=RISK_LEVEL_MEDIUM,
                difficulty_ema=0.5,
                fragility_score=0.1,
            )
        ]
        path = write_sample_risk_artifact(signals, tmp_path)
        assert Path(path).name == RISK_ARTIFACT_FILENAME
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data[0]["sample_id"] == "s1"


class TestComputeRiskSignalsOrderPreservation:
    def test_preserves_input_order(self):
        samples = [_sample(f"s{i}") for i in range(5)]
        states = {s.id: _state(s.id, difficulty_ema=0.1 * i) for i, s in enumerate(samples)}
        signals = compute_risk_signals(samples, states)
        assert [s.sample_id for s in signals] == ["s0", "s1", "s2", "s3", "s4"]


# ---------------------------------------------------------------------------
# Scope guards (no coupling to out-of-scope modules)
# ---------------------------------------------------------------------------


class TestScopeGuards:
    def test_source_file_does_not_reference_compression_or_merging(self):
        import inspect
        import mmap_optimizer.sampling.risk_signals as module

        source = inspect.getsource(module)
        # Explicitly-out-of-scope tokens from PR #3's plan.
        forbidden = [
            "compression.engine",
            "compression_engine",
            "tree_reduce_patch_merger",
            "patch_merger",
            "risk_aware_merging",
            "prompt_artifact",
            "PromptSection",
        ]
        for token in forbidden:
            assert token not in source, f"Unexpected reference to '{token}' in risk_signals.py"

    def test_constants_are_defined(self):
        assert RISK_LEVEL_LOW == "low"
        assert RISK_LEVEL_MEDIUM == "medium"
        assert RISK_LEVEL_HIGH == "high"
        assert RISK_ARTIFACT_FILENAME == "sample_risk_signals.json"
