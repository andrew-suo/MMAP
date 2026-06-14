"""Contract tests for :mod:`mmap_optimizer.patch.merge_ranking`.

These tests verify the behavior of the risk-aware patch merge candidate
scoring, ranking, and selection helpers. No test references compression,
semantic compression, or the optimizer pipeline — see module docstring for
scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from mmap_optimizer.patch.merge_ranking import (
    PatchMergeCandidate,
    build_merge_candidates_from_patches,
    merge_candidates_to_dict,
    merge_candidates_to_json,
    rank_patch_merge_candidates,
    score_patch_merge_candidate,
    select_top_merge_candidates,
    write_merge_ranking_report,
)
from mmap_optimizer.patch.schema import Patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    patch_id: str,
    *,
    section_id: str = "rules",
    risk_score: float = 0.0,
    contribution_delta: float = 0.0,
    conflict_count: int = 0,
    side_effect_risk: float = 0.0,
    repair_needed: bool = False,
) -> PatchMergeCandidate:
    return PatchMergeCandidate(
        patch_id=patch_id,
        section_id=section_id,
        risk_score=risk_score,
        contribution_delta=contribution_delta,
        conflict_count=conflict_count,
        side_effect_risk=side_effect_risk,
        repair_needed=repair_needed,
    )


# ---------------------------------------------------------------------------
# Score: individual candidate behavior
# ---------------------------------------------------------------------------


class TestScorePatchMergeCandidate:
    def test_positive_contribution_improves_score(self):
        base = score_patch_merge_candidate(_candidate("p1", contribution_delta=0.0))
        improved = score_patch_merge_candidate(_candidate("p2", contribution_delta=0.5))
        assert improved.merge_score > base.merge_score

    def test_high_risk_lowers_score(self):
        safe = score_patch_merge_candidate(_candidate("p1", risk_score=0.0))
        risky = score_patch_merge_candidate(_candidate("p2", risk_score=0.9))
        assert risky.merge_score < safe.merge_score

    def test_conflict_count_lowers_score(self):
        p1 = score_patch_merge_candidate(_candidate("p1", conflict_count=0))
        p2 = score_patch_merge_candidate(_candidate("p2", conflict_count=3))
        assert p2.merge_score < p1.merge_score

    def test_side_effect_risk_lowers_score(self):
        p1 = score_patch_merge_candidate(_candidate("p1", side_effect_risk=0.0))
        p2 = score_patch_merge_candidate(_candidate("p2", side_effect_risk=0.8))
        assert p2.merge_score < p1.merge_score

    def test_repair_needed_lowers_score(self):
        p1 = score_patch_merge_candidate(_candidate("p1", repair_needed=False))
        p2 = score_patch_merge_candidate(_candidate("p2", repair_needed=True))
        assert p2.merge_score < p1.merge_score

    def test_scoring_returns_new_object(self):
        original = _candidate("p1", risk_score=0.5)
        result = score_patch_merge_candidate(original)
        assert result is not original
        # merge_score was updated on the returned copy
        assert result.merge_score != 0.0

    def test_scoring_accepts_dict_input(self):
        candidate = {
            "patch_id": "p1",
            "section_id": "rules",
            "risk_score": 0.1,
            "contribution_delta": 0.2,
            "conflict_count": 0,
            "side_effect_risk": 0.0,
            "repair_needed": False,
        }
        result = score_patch_merge_candidate(candidate)
        assert result.patch_id == "p1"
        assert result.section_id == "rules"
        assert result.merge_score > 0.0  # positive contribution
        assert result.merge_score < 0.25  # well below raw 0.5*0.2 with risk

    def test_risk_score_is_clamped_to_unit_interval(self):
        # Values above 1.0 or below 0.0 should not explode the score.
        high = score_patch_merge_candidate(_candidate("p1", risk_score=5.0))
        low = score_patch_merge_candidate(_candidate("p1", risk_score=-5.0))
        # Clamped to [0, 1] means risk contribution differs by at most 0.30.
        assert high.merge_score >= -1.0
        assert low.merge_score <= 1.0
        assert high.risk_score == pytest.approx(1.0)
        assert low.risk_score == pytest.approx(0.0)

    def test_conflict_penalty_is_capped(self):
        few = score_patch_merge_candidate(_candidate("p1", conflict_count=3))
        many = score_patch_merge_candidate(_candidate("p2", conflict_count=100))
        # conflict penalty is capped at 1.0 * CONFLICT_WEIGHT — the two should
        # differ but not explode.
        assert few.merge_score - many.merge_score <= 0.21

    def test_reasons_are_populated_for_significant_signals(self):
        high_risk = score_patch_merge_candidate(
            _candidate("p1", risk_score=0.7, contribution_delta=0.3, conflict_count=2)
        )
        assert "high_sample_risk" in high_risk.reasons
        assert "positive_section_contribution" in high_risk.reasons
        assert "conflicts_detected" in high_risk.reasons

    def test_repair_needed_in_reasons_when_true(self):
        candidate = score_patch_merge_candidate(
            _candidate("p1", repair_needed=True, side_effect_risk=0.5)
        )
        assert "repair_needed" in candidate.reasons
        assert "side_effect_risk" in candidate.reasons


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRankPatchMergeCandidates:
    def test_highest_score_ranks_first(self):
        candidates = [
            _candidate("p1", contribution_delta=0.5, risk_score=0.1),
            _candidate("p2", contribution_delta=0.1, risk_score=0.8),
            _candidate("p3", contribution_delta=0.9, risk_score=0.0),
        ]
        ranked = rank_patch_merge_candidates(candidates)
        assert ranked[0].patch_id == "p3"
        assert ranked[-1].patch_id == "p2"

    def test_ties_broken_by_risk_score_then_section_then_patch_id(self):
        # Same contribution + risk → tie by ASCII order.
        candidates = [
            _candidate("z", contribution_delta=0.3),
            _candidate("a", contribution_delta=0.3),
        ]
        ranked = rank_patch_merge_candidates(candidates)
        assert ranked[0].patch_id == "a"
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_ties_on_score_use_risk_score(self):
        # Same contribution → lower risk wins.
        candidates = [
            _candidate("risky", contribution_delta=0.5, risk_score=0.8),
            _candidate("safe", contribution_delta=0.5, risk_score=0.1),
        ]
        ranked = rank_patch_merge_candidates(candidates)
        assert ranked[0].patch_id == "safe"

    def test_empty_input_returns_empty(self):
        assert rank_patch_merge_candidates([]) == []

    def test_does_not_mutate_input(self):
        candidates = [_candidate("p1", contribution_delta=0.3)]
        original_merge_score = candidates[0].merge_score
        original_rank = candidates[0].rank
        rank_patch_merge_candidates(candidates)
        # Original object unchanged — scoring produces new objects.
        assert candidates[0].merge_score == original_merge_score
        assert candidates[0].rank == original_rank

    def test_score_first_false_uses_existing_scores(self):
        candidates = [
            PatchMergeCandidate(
                patch_id="manual", section_id="rules", merge_score=1.0
            ),
            PatchMergeCandidate(
                patch_id="other", section_id="rules", merge_score=0.5
            ),
        ]
        ranked = rank_patch_merge_candidates(candidates, score_first=False)
        assert ranked[0].patch_id == "manual"

    def test_single_candidate_has_rank_one(self):
        ranked = rank_patch_merge_candidates(
            [_candidate("only", contribution_delta=0.5)]
        )
        assert ranked[0].rank == 1

    def test_ranking_is_deterministic(self):
        candidates = [
            _candidate(f"p{i}", contribution_delta=0.1 * (i % 3))
            for i in range(12)
        ]
        first = rank_patch_merge_candidates(candidates)
        second = rank_patch_merge_candidates(candidates)
        assert [c.patch_id for c in first] == [c.patch_id for c in second]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestSelectTopMergeCandidates:
    def test_respects_max_patches(self):
        candidates = [_candidate(f"p{i}", contribution_delta=0.3) for i in range(10)]
        top = select_top_merge_candidates(candidates, max_patches=3)
        assert len(top) == 3

    def test_zero_max_returns_empty(self):
        assert select_top_merge_candidates([], max_patches=0) == []

    def test_negative_max_returns_empty(self):
        candidates = [_candidate("p1", contribution_delta=0.5)]
        assert select_top_merge_candidates(candidates, max_patches=-1) == []

    def test_returns_all_when_fewer_than_max(self):
        candidates = [_candidate(f"p{i}") for i in range(3)]
        top = select_top_merge_candidates(candidates, max_patches=10)
        assert len(top) == 3

    def test_selects_highest_score_first(self):
        candidates = [
            _candidate("low", contribution_delta=0.1),
            _candidate("high", contribution_delta=0.9),
            _candidate("mid", contribution_delta=0.5),
        ]
        top = select_top_merge_candidates(candidates, max_patches=2)
        assert [c.patch_id for c in top] == ["high", "mid"]


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestMergeCandidateSerialization:
    def test_to_dict_is_json_serializable(self):
        candidate = score_patch_merge_candidate(
            _candidate(
                "p1",
                risk_score=0.4,
                contribution_delta=0.6,
                conflict_count=1,
                side_effect_risk=0.2,
            )
        )
        data = candidate.to_dict()
        restored = json.loads(json.dumps(data))
        assert restored["patch_id"] == "p1"
        assert restored["merge_score"] == pytest.approx(data["merge_score"])
        assert restored["rank"] == 0

    def test_merge_candidates_to_json(self):
        candidates = [
            score_patch_merge_candidate(
                _candidate("p1", contribution_delta=0.5, risk_score=0.2)
            ),
            score_patch_merge_candidate(
                _candidate("p2", contribution_delta=0.1, risk_score=0.8)
            ),
        ]
        payload = merge_candidates_to_json(candidates)
        parsed = json.loads(payload)
        assert "p1" in parsed
        assert "p2" in parsed
        assert parsed["p1"]["merge_score"] > parsed["p2"]["merge_score"]

    def test_write_merge_ranking_report(self, tmp_path: Path):
        candidates = [
            score_patch_merge_candidate(_candidate("p1", contribution_delta=0.5))
        ]
        path = Path(write_merge_ranking_report(candidates, tmp_path / "ranking.json"))
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "p1" in data

    def test_merge_candidates_to_dict_preserves_ids(self):
        candidates = [
            score_patch_merge_candidate(_candidate("p1")),
            score_patch_merge_candidate(_candidate("p2", section_id="intro")),
        ]
        data = merge_candidates_to_dict(candidates)
        assert data["p1"]["section_id"] == "rules"
        assert data["p2"]["section_id"] == "intro"


# ---------------------------------------------------------------------------
# Convenience: build from patches
# ---------------------------------------------------------------------------


@dataclass
class FakePatch:
    id: str
    section_id: str
    risk_level: str = "unknown"
    possible_side_effects: list[str] = None  # type: ignore[assignment]


class TestBuildMergeCandidatesFromPatches:
    def test_builds_one_candidate_per_patch(self):
        patches = [
            FakePatch(id="p1", section_id="rules", risk_level="low"),
            FakePatch(id="p2", section_id="examples", risk_level="high"),
        ]
        candidates = build_merge_candidates_from_patches(patches)
        assert {c.patch_id for c in candidates} == {"p1", "p2"}
        assert {c.section_id for c in candidates} == {"rules", "examples"}

    def test_uses_external_signals_when_provided(self):
        patches = [
            FakePatch(id="p1", section_id="rules", risk_level="low"),
        ]
        candidates = build_merge_candidates_from_patches(
            patches,
            section_contributions={"rules": 0.7},
            risk_signals={"p1": 0.2},
            conflict_counts={"p1": 2},
        )
        assert candidates[0].contribution_delta == pytest.approx(0.7)
        assert candidates[0].risk_score == pytest.approx(0.2)
        assert candidates[0].conflict_count == 2
        assert candidates[0].merge_score < 0.5 * 0.7  # positive but penalized

    def test_falls_back_to_risk_level_when_no_signal(self):
        patches = [
            FakePatch(id="p1", section_id="rules", risk_level="high"),
        ]
        candidates = build_merge_candidates_from_patches(patches)
        # high → risk score 0.7 (as mapped inside the module).
        assert candidates[0].risk_score > 0.5

    def test_side_effects_are_counted(self):
        patches = [
            FakePatch(
                id="p1",
                section_id="rules",
                possible_side_effects=["may_break_X", "may_regress_Y"],
            ),
        ]
        candidates = build_merge_candidates_from_patches(patches)
        assert candidates[0].side_effect_risk > 0.0

    def test_accepts_dict_patches(self):
        patches = [{"id": "d1", "section_id": "rules", "risk_level": "medium"}]
        candidates = build_merge_candidates_from_patches(patches)
        assert candidates[0].patch_id == "d1"

    def test_repair_needed_flagged_for_high_risk_or_conflicts(self):
        # High external risk score triggers repair_needed.
        patches = [FakePatch(id="p1", section_id="rules")]
        candidates_high = build_merge_candidates_from_patches(
            patches, risk_signals={"p1": 0.9}
        )
        assert candidates_high[0].repair_needed is True

        # Low risk score without conflicts does not.
        candidates_low = build_merge_candidates_from_patches(
            [FakePatch(id="p2", section_id="rules")], risk_signals={"p2": 0.2}
        )
        assert candidates_low[0].repair_needed is False

    def test_empty_patches_produce_empty_list(self):
        assert build_merge_candidates_from_patches([]) == []


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


class TestMergeRankingEndToEnd:
    def test_scoring_ranking_selection_pipeline(self):
        # Build candidates from patches.
        patches = [
            FakePatch(id="p1", section_id="rules", risk_level="low"),
            FakePatch(id="p2", section_id="rules", risk_level="high"),
            FakePatch(id="p3", section_id="examples", risk_level="medium"),
            FakePatch(id="p4", section_id="intro", risk_level="low"),
        ]
        candidates = build_merge_candidates_from_patches(
            patches,
            section_contributions={
                "rules": 0.5,
                "examples": 0.3,
                "intro": -0.1,
            },
            conflict_counts={"p2": 1},
        )

        ranked = rank_patch_merge_candidates(candidates)
        # Best should be p1 (high positive contribution + low risk).
        assert ranked[0].patch_id == "p1"
        assert ranked[0].rank == 1

        # Select top 2.
        top = select_top_merge_candidates(candidates, max_patches=2)
        assert len(top) == 2
        assert top[0].patch_id == "p1"

    def test_output_preserves_all_required_schema_fields(self):
        candidates = [
            score_patch_merge_candidate(
                _candidate(
                    "p1",
                    risk_score=0.4,
                    contribution_delta=0.3,
                    conflict_count=1,
                    side_effect_risk=0.1,
                    repair_needed=True,
                )
            )
        ]
        payload = candidates[0].to_dict()
        # Schema must always include these fields (per module design).
        for key in (
            "patch_id",
            "section_id",
            "risk_score",
            "contribution_delta",
            "conflict_count",
            "side_effect_risk",
            "repair_needed",
            "merge_score",
            "rank",
            "reasons",
            "metadata",
        ):
            assert key in payload, f"Missing schema field: {key}"


# ---------------------------------------------------------------------------
# Scope guards
# ---------------------------------------------------------------------------


class TestScopeGuards:
    def test_no_compression_or_pipeline_imports(self):
        import inspect
        import mmap_optimizer.patch.merge_ranking as module

        source = inspect.getsource(module)
        forbidden = [
            "compression.engine",
            "compression_engine",
            "prompt_artifact",
            "runner",
            "orchestration",
        ]
        for token in forbidden:
            assert token not in source, f"Unexpected reference to '{token}'"

    def test_module_runs_without_side_effects(self):
        # Re-import should not raise and should not write files.
        import importlib

        importlib.reload(__import__("mmap_optimizer.patch.merge_ranking"))
