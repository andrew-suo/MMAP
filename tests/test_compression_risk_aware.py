"""Contract tests for :mod:`mmap_optimizer.compression.risk_aware`.

These tests verify scoring, safety gating, deterministic ranking,
selection, and JSON serialization for the risk-aware compression decision
helpers. They intentionally do **not** import or exercise
:class:`CompressionEngine`, :class:`SemanticCompressionEngine`, model
clients, optimizer loop, or other out-of-scope systems.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmap_optimizer.compression.risk_aware import (
    COMPRESSION_RATIO_WEIGHT,
    CONTRIBUTION_WEIGHT,
    CompressionDecision,
    HIGH_RISK_THRESHOLD,
    HIGH_TOXICITY_THRESHOLD,
    LARGE_NEGATIVE_CONTRIBUTION_THRESHOLD,
    RISK_INVERTED_WEIGHT,
    SEVERE_SEMANTIC_LOSS_THRESHOLD,
    build_compression_candidates_from_sections,
    compression_decision_to_dict,
    compression_decisions_to_json,
    rank_compression_candidates,
    score_compression_candidate,
    select_top_compression_candidates,
    should_accept_compression,
    write_compression_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(**fields: object) -> CompressionDecision:
    base: dict[str, object] = {
        "candidate_id": str(fields.pop("candidate_id", "default")),
        "section_id": str(fields.pop("section_id", "rules")),
        "compression_ratio": float(fields.pop("compression_ratio", 0.2)),
        "contribution_delta": float(fields.pop("contribution_delta", 0.0)),
        "risk_score": float(fields.pop("risk_score", 0.0)),
        "toxicity_risk": float(fields.pop("toxicity_risk", 0.0)),
        "broken_sample_count": int(fields.pop("broken_sample_count", 0)),
        "semantic_loss_risk": float(fields.pop("semantic_loss_risk", 0.0)),
        "candidate_sample_count": int(fields.pop("candidate_sample_count", 3)),
    }
    base.update(fields)  # allow caller to override
    return CompressionDecision(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Score computation
# ---------------------------------------------------------------------------


class TestScoreCompressionCandidate:
    def test_high_compression_ratio_increases_score(self):
        low = score_compression_candidate(_decision(compression_ratio=0.05))
        high = score_compression_candidate(_decision(compression_ratio=0.5))
        assert high.compression_score > low.compression_score

    def test_low_risk_increases_score(self):
        low = score_compression_candidate(_decision(risk_score=0.1))
        high = score_compression_candidate(_decision(risk_score=0.9))
        assert low.compression_score > high.compression_score

    def test_positive_contribution_increases_score(self):
        pos = score_compression_candidate(_decision(contribution_delta=0.4))
        zero = score_compression_candidate(_decision(contribution_delta=0.0))
        assert pos.compression_score > zero.compression_score

    def test_negative_contribution_does_not_pull_score_below_zero(self):
        neg = score_compression_candidate(
            _decision(contribution_delta=-0.5, risk_score=0.1)
        )
        # Still clamped to [0, 1].
        assert 0.0 <= neg.compression_score <= 1.0

    def test_toxicity_lowers_score(self):
        clean = score_compression_candidate(_decision(toxicity_risk=0.0))
        toxic = score_compression_candidate(_decision(toxicity_risk=0.8))
        assert toxic.compression_score < clean.compression_score

    def test_semantic_loss_lowers_score(self):
        low = score_compression_candidate(_decision(semantic_loss_risk=0.1))
        high = score_compression_candidate(_decision(semantic_loss_risk=0.9))
        assert high.compression_score < low.compression_score

    def test_broken_samples_lower_score(self):
        baseline = score_compression_candidate(_decision(broken_sample_count=0))
        broken = score_compression_candidate(_decision(broken_sample_count=5))
        assert broken.compression_score < baseline.compression_score

    def test_score_is_clamped_to_unit_interval(self):
        # Maximum raw score: ratio=1 (weight 0.45), low_risk bonus +0.30,
        # positive contribution +0.15 → raw 0.90.
        best = score_compression_candidate(
            _decision(compression_ratio=1.0, risk_score=0.0,
                      contribution_delta=1.0)
        )
        assert best.compression_score <= 1.0
        worst = score_compression_candidate(
            _decision(compression_ratio=0.0, risk_score=1.0,
                      toxicity_risk=1.0, semantic_loss_risk=1.0,
                      broken_sample_count=100)
        )
        assert worst.compression_score >= 0.0

    def test_scoring_returns_new_object(self):
        candidate = _decision(compression_ratio=0.3)
        original = candidate.compression_score
        result = score_compression_candidate(candidate)
        assert result is not candidate
        # The original is untouched.
        assert candidate.compression_score == original

    def test_accepts_dict_input(self):
        result = score_compression_candidate(
            {
                "candidate_id": "dict_candidate",
                "section_id": "rules",
                "compression_ratio": 0.3,
                "contribution_delta": 0.2,
                "risk_score": 0.1,
                "toxicity_risk": 0.0,
                "broken_sample_count": 0,
                "semantic_loss_risk": 0.0,
                "candidate_sample_count": 5,
            }
        )
        assert result.candidate_id == "dict_candidate"
        assert result.compression_score > 0.0
        assert result.accepted is True

    def test_score_is_deterministic_on_equal_inputs(self):
        a = score_compression_candidate(_decision(compression_ratio=0.4))
        b = score_compression_candidate(_decision(compression_ratio=0.4))
        assert a.compression_score == pytest.approx(b.compression_score)


# ---------------------------------------------------------------------------
# Safety gating
# ---------------------------------------------------------------------------


class TestSafetyGating:
    def test_high_risk_section_is_rejected(self):
        scored = score_compression_candidate(
            _decision(risk_score=HIGH_RISK_THRESHOLD)
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "HIGH_RISK_SECTION"
        assert "high_risk_section" in scored.reasons

    def test_high_toxicity_is_rejected(self):
        scored = score_compression_candidate(
            _decision(toxicity_risk=HIGH_TOXICITY_THRESHOLD)
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "HIGH_TOXICITY_RISK"

    def test_severe_semantic_loss_is_rejected(self):
        scored = score_compression_candidate(
            _decision(semantic_loss_risk=SEVERE_SEMANTIC_LOSS_THRESHOLD)
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "SEVERE_SEMANTIC_LOSS_RISK"

    def test_large_negative_contribution_is_rejected(self):
        scored = score_compression_candidate(
            _decision(
                contribution_delta=LARGE_NEGATIVE_CONTRIBUTION_THRESHOLD - 0.01,
            )
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "LARGE_NEGATIVE_CONTRIBUTION"

    def test_broken_samples_without_improvement_is_rejected(self):
        scored = score_compression_candidate(
            _decision(broken_sample_count=2, contribution_delta=0.0)
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "BROKEN_SAMPLES_WITHOUT_IMPROVEMENT"

    def test_broken_samples_with_improvement_may_accept(self):
        # Positive contribution delta + no other breaches → accepted even
        # with some broken samples (the gate only rejects when delta <= 0).
        scored = score_compression_candidate(
            _decision(
                broken_sample_count=2,
                contribution_delta=0.2,
                risk_score=0.1,
                toxicity_risk=0.0,
                semantic_loss_risk=0.2,
            )
        )
        assert scored.accepted is True
        assert scored.rejection_reason is None

    def test_no_behavior_samples_is_rejected(self):
        scored = score_compression_candidate(
            _decision(candidate_sample_count=0)
        )
        assert scored.accepted is False
        assert scored.rejection_reason == "NO_BEHAVIOR_SAMPLES"

    def test_clean_low_risk_input_is_accepted(self):
        scored = score_compression_candidate(
            _decision(
                compression_ratio=0.4,
                contribution_delta=0.2,
                risk_score=0.1,
                toxicity_risk=0.0,
                semantic_loss_risk=0.1,
                broken_sample_count=0,
                candidate_sample_count=5,
            )
        )
        assert scored.accepted is True
        assert scored.rejection_reason is None
        assert "accepted" in scored.reasons

    def test_multiple_gates_record_all_reasons(self):
        scored = score_compression_candidate(
            _decision(
                risk_score=0.9,
                toxicity_risk=0.9,
                semantic_loss_risk=0.9,
                contribution_delta=-0.5,
                broken_sample_count=3,
            )
        )
        assert scored.accepted is False
        # Each failing gate should be represented in reasons.
        assert "high_risk_section" in scored.reasons
        assert "high_toxicity_risk" in scored.reasons
        assert "severe_semantic_loss_risk" in scored.reasons
        assert "large_negative_contribution" in scored.reasons
        assert "broken_samples_without_improvement" in scored.reasons
        # rejection_reason is the first gate fired (priority order).
        assert scored.rejection_reason == "HIGH_TOXICITY_RISK"

    def test_should_accept_helper_matches_scoring(self):
        accepted, reason = should_accept_compression(
            _decision(risk_score=0.9, toxicity_risk=0.0)
        )
        assert accepted is False
        assert reason == "HIGH_RISK_SECTION"

        accepted2, reason2 = should_accept_compression(
            _decision(risk_score=0.1, toxicity_risk=0.0,
                      candidate_sample_count=3)
        )
        assert accepted2 is True
        assert reason2 is None


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRankCompressionCandidates:
    def test_highest_score_ranks_first(self):
        candidates = [
            _decision(candidate_id="a", compression_ratio=0.1, risk_score=0.9),
            _decision(candidate_id="b", compression_ratio=0.5, risk_score=0.1),
            _decision(candidate_id="c", compression_ratio=0.3, risk_score=0.3),
        ]
        ranked = rank_compression_candidates(candidates)
        assert ranked[0].candidate_id == "b"
        assert ranked[-1].candidate_id == "a"

    def test_ties_broken_by_section_id_then_candidate_id(self):
        # Two candidates with identical scoring inputs → deterministic order.
        candidates = [
            _decision(candidate_id="z", section_id="examples"),
            _decision(candidate_id="a", section_id="examples"),
            _decision(candidate_id="m", section_id="analysis"),
        ]
        ranked = rank_compression_candidates(candidates)
        # Same score → sort by section_id asc, then candidate_id asc.
        assert ranked[0].section_id <= ranked[1].section_id
        assert ranked[1].section_id <= ranked[2].section_id
        # For the two "examples" entries, the candidate_id tie-breaker holds.
        section_examples = [d for d in ranked if d.section_id == "examples"]
        assert section_examples[0].candidate_id == "a"
        assert section_examples[1].candidate_id == "z"

    def test_empty_input_returns_empty(self):
        assert rank_compression_candidates([]) == []

    def test_does_not_mutate_input_candidates(self):
        candidates = [_decision(candidate_id="x", compression_ratio=0.2)]
        original_score = candidates[0].compression_score
        rank_compression_candidates(candidates)
        assert candidates[0].compression_score == original_score

    def test_score_first_false_uses_existing_scores(self):
        candidates = [
            CompressionDecision(
                candidate_id="manual_high",
                section_id="rules",
                compression_score=0.9,
                accepted=True,
            ),
            CompressionDecision(
                candidate_id="manual_low",
                section_id="rules",
                compression_score=0.2,
                accepted=False,
            ),
        ]
        ranked = rank_compression_candidates(candidates, score_first=False)
        assert ranked[0].candidate_id == "manual_high"
        assert ranked[1].candidate_id == "manual_low"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestSelectTopCompressionCandidates:
    def test_respects_max_candidates(self):
        candidates = [
            _decision(candidate_id=f"c{i}", compression_ratio=0.5, risk_score=0.0)
            for i in range(5)
        ]
        top = select_top_compression_candidates(candidates, max_candidates=2)
        assert len(top) == 2

    def test_zero_max_returns_empty(self):
        candidates = [_decision(candidate_id="x", compression_ratio=0.5)]
        assert select_top_compression_candidates(candidates, 0) == []

    def test_negative_max_returns_empty(self):
        candidates = [_decision(candidate_id="x")]
        assert select_top_compression_candidates(candidates, -1) == []

    def test_accepted_only_by_default(self):
        candidates = [
            _decision(candidate_id="good", risk_score=0.1),
            _decision(candidate_id="bad", risk_score=0.95),
            _decision(candidate_id="good2", risk_score=0.05),
        ]
        top = select_top_compression_candidates(candidates, max_candidates=10)
        assert all(decision.accepted for decision in top)
        assert not any(decision.candidate_id == "bad" for decision in top)

    def test_accepted_only_false_includes_rejected(self):
        candidates = [
            _decision(candidate_id="good", risk_score=0.1),
            _decision(candidate_id="bad", risk_score=0.95),
        ]
        top = select_top_compression_candidates(
            candidates, max_candidates=10, accepted_only=False
        )
        assert len(top) == 2
        # "good" should still rank higher because it scores higher.
        assert top[0].candidate_id == "good"

    def test_returns_all_when_max_exceeds_available(self):
        candidates = [
            _decision(candidate_id="x", risk_score=0.1),
            _decision(candidate_id="y", risk_score=0.2),
        ]
        top = select_top_compression_candidates(candidates, max_candidates=20)
        assert len(top) == 2


# ---------------------------------------------------------------------------
# Build from sections (integration with #41 / #42 data shapes)
# ---------------------------------------------------------------------------


class TestBuildCompressionCandidatesFromSections:
    def test_builds_scored_candidate(self):
        sections = [
            {
                "section_id": "rules",
                "line_count_before": 100,
                "line_count_after": 70,
                "candidate_sample_count": 3,
                "compressibility": "high",
                "priority": 1,
            }
        ]
        results = build_compression_candidates_from_sections(sections)
        assert len(results) == 1
        assert results[0].section_id == "rules"
        # compression_ratio = 1 - 70/100 = 0.3
        assert results[0].compression_ratio == pytest.approx(0.3, abs=1e-6)
        assert results[0].metadata["compressibility"] == "high"
        assert results[0].metadata["priority"] == 1
        assert results[0].compression_score > 0.0

    def test_uses_section_contributions_when_provided(self):
        sections = [{"section_id": "rules", "line_count_before": 100, "line_count_after": 60}]
        scored_with = build_compression_candidates_from_sections(
            sections, section_contributions={"rules": 0.5}
        )
        scored_without = build_compression_candidates_from_sections(
            [{"section_id": "rules", "line_count_before": 100, "line_count_after": 60}]
        )
        assert scored_with[0].contribution_delta == 0.5
        assert scored_with[0].compression_score > scored_without[0].compression_score

    def test_uses_risk_signals_when_provided(self):
        sections = [{"section_id": "examples", "line_count_before": 40, "line_count_after": 30}]
        scored_high_risk = build_compression_candidates_from_sections(
            sections, risk_signals={"examples": 0.8}
        )
        scored_low_risk = build_compression_candidates_from_sections(
            [{"section_id": "examples", "line_count_before": 40, "line_count_after": 30}],
            risk_signals={"examples": 0.1},
        )
        assert scored_high_risk[0].risk_score == 0.8
        assert scored_low_risk[0].risk_score == 0.1
        assert scored_low_risk[0].compression_score > scored_high_risk[0].compression_score

    def test_empty_sections_returns_empty_list(self):
        assert build_compression_candidates_from_sections([]) == []

    def test_zero_line_count_before_sets_zero_ratio(self):
        sections = [{"section_id": "rules", "line_count_before": 0, "line_count_after": 0}]
        result = build_compression_candidates_from_sections(sections)
        assert result[0].compression_ratio == 0.0

    def test_missing_section_contributions_default_to_zero(self):
        sections = [{"section_id": "other", "line_count_before": 40, "line_count_after": 20}]
        result = build_compression_candidates_from_sections(sections)
        assert result[0].contribution_delta == 0.0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestCompressionDecisionSerialization:
    def test_to_dict_round_trips(self):
        scored = score_compression_candidate(
            _decision(
                candidate_id="audit_01",
                section_id="rules",
                compression_ratio=0.4,
                risk_score=0.15,
                toxicity_risk=0.0,
                semantic_loss_risk=0.1,
                broken_sample_count=0,
                candidate_sample_count=5,
            )
        )
        payload = scored.to_dict()
        restored = json.loads(json.dumps(payload))
        assert restored["candidate_id"] == "audit_01"
        assert restored["section_id"] == "rules"
        assert restored["accepted"] is True
        assert restored["rejection_reason"] is None
        assert restored["compression_score"] == pytest.approx(scored.compression_score)
        assert isinstance(restored["reasons"], list)

    def test_rejected_decision_serializes_rejection_reason(self):
        scored = score_compression_candidate(_decision(risk_score=0.9))
        payload = scored.to_dict()
        restored = json.loads(json.dumps(payload))
        assert restored["accepted"] is False
        assert restored["rejection_reason"] == "HIGH_RISK_SECTION"

    def test_compression_decisions_to_json_contains_all_ids(self):
        decisions = [
            score_compression_candidate(_decision(candidate_id="x")),
            score_compression_candidate(_decision(candidate_id="y", risk_score=0.9)),
        ]
        text = compression_decisions_to_json(decisions)
        data = json.loads(text)
        ids = {entry["candidate_id"] for entry in data}
        assert ids == {"x", "y"}
        # "y" should record rejection_reason.
        y_entry = [entry for entry in data if entry["candidate_id"] == "y"][0]
        assert y_entry["rejection_reason"] == "HIGH_RISK_SECTION"

    def test_write_compression_report_produces_file(self, tmp_path: Path):
        decisions = [
            score_compression_candidate(_decision(candidate_id="r1")),
        ]
        path = Path(write_compression_report(decisions, tmp_path / "report.json"))
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["candidate_id"] == "r1"


# ---------------------------------------------------------------------------
# Module scope guards (no coupling to out-of-scope modules)
# ---------------------------------------------------------------------------


class TestModuleScopeGuards:
    def test_module_does_not_import_model_or_orchestration(self):
        import importlib
        import mmap_optimizer.compression.risk_aware as module

        # Re-importing should not import model_client / orchestration / prompts.
        importlib.reload(module)
        forbidden = ("model.client", "orchestration", "prompt.artifact", "runner")
        for token in forbidden:
            assert token not in module.__dict__

    def test_no_compression_engine_calls_in_scoring(self):
        # The module under test should only expose helpers, not modify the
        # existing engine. Verify it does not use engine symbols.
        import inspect
        import mmap_optimizer.compression.risk_aware as module

        source = inspect.getsource(module)
        forbidden_constructs = [
            "CompressionEngine(",
            "SemanticCompressionEngine(",
            "CompressionReport(",
            "model_client",
            "PromptTestRunner",
            "optimizer_loop",
            "orchestration",
        ]
        for token in forbidden_constructs:
            assert token not in source, f"Unexpected coupling to '{token}'"

    def test_constants_are_strictly_bounded(self):
        # All weights and thresholds must stay within sensible ranges so
        # future changes cannot silently break scoring.
        assert 0.0 < COMPRESSION_RATIO_WEIGHT <= 1.0
        assert 0.0 < RISK_INVERTED_WEIGHT <= 1.0
        assert 0.0 < CONTRIBUTION_WEIGHT <= 1.0
        assert 0.0 < HIGH_RISK_THRESHOLD <= 1.0
        assert 0.0 < HIGH_TOXICITY_THRESHOLD <= 1.0
        assert 0.0 < SEVERE_SEMANTIC_LOSS_THRESHOLD <= 1.0
        assert -1.0 <= LARGE_NEGATIVE_CONTRIBUTION_THRESHOLD < 0.0
