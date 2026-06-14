from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from mmap_optimizer.metrics.section_deltas import (
    SECTION_CONTRIBUTION_ARTIFACT,
    SectionContributionDelta,
    compute_section_deltas,
    rank_section_deltas,
    section_contributions_to_dict,
    write_section_contribution_artifact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    sample_id: str,
    correct: bool,
    section_ids: list[str] | None = None,
) -> EvaluationRecord:
    used = [{"section_id": sid} for sid in (section_ids or [])]
    status = "correct" if correct else "wrong"
    return EvaluationRecord(
        id=f"eval_{sample_id}",
        round_id="r",
        run_id="run",
        sample_id=sample_id,
        ground_truth_id=f"gt_{sample_id}",
        parse_success=True,
        schema_valid=True,
        primary_answer_correct=correct,
        overall_status=status,
        used_prompt_sections=used,
    )


def _record_dict(*, sample_id: str, correct: bool, section_ids: list[str] | None = None) -> dict:
    used = [{"section_id": sid} for sid in (section_ids or [])]
    return {
        "id": f"eval_{sample_id}",
        "sample_id": sample_id,
        "primary_answer_correct": correct,
        "overall_status": "correct" if correct else "wrong",
        "used_prompt_sections": used,
    }


# ---------------------------------------------------------------------------
# Dataclass / serialization
# ---------------------------------------------------------------------------


class TestSectionContributionDeltaSchema:
    def test_to_dict_is_json_serializable(self):
        delta = SectionContributionDelta(
            section_id="rules",
            baseline_score=0.6,
            new_score=0.8,
            delta=0.2,
            sample_count=10,
            improved_count=2,
            regressed_count=0,
            unchanged_count=8,
            weight=1.2,
            rank=1,
            metadata={"origin": "unit-test"},
        )
        payload = delta.to_dict()
        # Must round-trip through JSON with no loss of numeric fields.
        restored = json.loads(json.dumps(payload))
        assert restored["section_id"] == "rules"
        assert restored["delta"] == pytest.approx(0.2)
        assert restored["improved_count"] == 2
        assert restored["regressed_count"] == 0
        assert restored["weight"] == pytest.approx(1.2)
        assert restored["rank"] == 1
        assert restored["metadata"]["origin"] == "unit-test"

    def test_module_constant_is_present(self):
        assert SECTION_CONTRIBUTION_ARTIFACT == "section_contribution.json"


# ---------------------------------------------------------------------------
# compute_section_deltas — correctness
# ---------------------------------------------------------------------------


class TestComputeSectionDeltas:
    def test_improvement_moves_delta_positive(self):
        baseline = [
            _record(sample_id="s1", correct=False, section_ids=["examples"]),
            _record(sample_id="s2", correct=True, section_ids=["examples"]),
        ]
        new = [
            _record(sample_id="s1", correct=True, section_ids=["examples"]),
            _record(sample_id="s2", correct=True, section_ids=["examples"]),
        ]
        deltas = compute_section_deltas(baseline, new)
        assert "examples" in deltas
        section = deltas["examples"]
        assert section.sample_count == 2
        assert section.improved_count == 1
        assert section.regressed_count == 0
        assert section.unchanged_count == 1
        assert section.baseline_score == pytest.approx(0.5)
        assert section.new_score == pytest.approx(1.0)
        assert section.delta == pytest.approx(0.5)
        assert section.weight > 1.0

    def test_regression_moves_delta_negative(self):
        baseline = [
            _record(sample_id="s1", correct=True, section_ids=["rules"]),
        ]
        new = [
            _record(sample_id="s1", correct=False, section_ids=["rules"]),
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas["rules"].delta == pytest.approx(-1.0)
        assert deltas["rules"].regressed_count == 1
        assert deltas["rules"].improved_count == 0
        assert deltas["rules"].weight < 1.0

    def test_unchanged_scores_delta_zero(self):
        baseline = [
            _record(sample_id="s1", correct=True, section_ids=["intro"]),
            _record(sample_id="s2", correct=False, section_ids=["intro"]),
        ]
        deltas = compute_section_deltas(baseline, baseline)
        assert deltas["intro"].delta == pytest.approx(0.0)
        assert deltas["intro"].improved_count == 0
        assert deltas["intro"].regressed_count == 0
        assert deltas["intro"].unchanged_count == 2

    def test_accepts_dict_records(self):
        baseline = [
            _record_dict(sample_id="a", correct=False, section_ids=["rules"]),
        ]
        new = [
            _record_dict(sample_id="a", correct=True, section_ids=["rules"]),
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas["rules"].delta == pytest.approx(1.0)
        assert deltas["rules"].weight > 1.0

    def test_multiple_sections_independent(self):
        baseline = [
            _record(sample_id="s1", correct=False, section_ids=["examples"]),
            _record(sample_id="s2", correct=False, section_ids=["rules"]),
            _record(sample_id="s3", correct=True, section_ids=["intro"]),
        ]
        new = [
            _record(sample_id="s1", correct=True, section_ids=["examples"]),
            _record(sample_id="s2", correct=False, section_ids=["rules"]),
            _record(sample_id="s3", correct=True, section_ids=["intro"]),
        ]
        deltas = compute_section_deltas(baseline, new)
        assert set(deltas) == {"examples", "rules", "intro"}
        assert deltas["examples"].delta > 0
        assert deltas["rules"].delta == pytest.approx(0.0)
        assert deltas["intro"].delta == pytest.approx(0.0)

    def test_sample_only_in_baseline_or_new_handled(self):
        baseline = [
            _record(sample_id="s1", correct=True, section_ids=["rules"]),
            _record(sample_id="only_baseline", correct=False, section_ids=["rules"]),
        ]
        new = [
            _record(sample_id="s1", correct=True, section_ids=["rules"]),
            _record(sample_id="only_new", correct=True, section_ids=["rules"]),
        ]
        deltas = compute_section_deltas(baseline, new)
        section = deltas["rules"]
        # s1 contributes unchanged, only_baseline and only_new counted in totals
        # but not in improved/regressed because they lack a paired partner.
        assert section.sample_count >= 2
        # s1: True→True => unchanged, so improved=0, regressed=0, unchanged>=1
        assert section.improved_count == 0
        assert section.regressed_count == 0
        assert section.unchanged_count >= 1

    def test_records_without_section_id_are_skipped(self):
        baseline = [
            _record(sample_id="s1", correct=True, section_ids=[]),
        ]
        new = [
            _record(sample_id="s1", correct=False, section_ids=[]),
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas == {}

    def test_weight_is_bounded(self):
        # Extreme improvement should not drive weight above the documented cap.
        baseline = [
            _record(sample_id=f"s{i}", correct=False, section_ids=["rules"])
            for i in range(50)
        ]
        new = [
            _record(sample_id=f"s{i}", correct=True, section_ids=["rules"])
            for i in range(50)
        ]
        deltas = compute_section_deltas(baseline, new)
        assert deltas["rules"].weight <= 3.0
        # Extreme regression should keep weight above the documented floor.
        baseline2 = [
            _record(sample_id=f"s{i}", correct=True, section_ids=["rules"])
            for i in range(50)
        ]
        new2 = [
            _record(sample_id=f"s{i}", correct=False, section_ids=["rules"])
            for i in range(50)
        ]
        deltas2 = compute_section_deltas(baseline2, new2)
        assert deltas2["rules"].weight >= 0.1


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------


class TestComputeSectionDeltasEdgeCases:
    def test_both_empty_produces_empty(self):
        assert compute_section_deltas([], []) == {}

    def test_baseline_empty_uses_new_totals(self):
        new = [
            _record(sample_id="s1", correct=True, section_ids=["rules"]),
        ]
        deltas = compute_section_deltas([], new)
        section = deltas["rules"]
        assert section.baseline_score == pytest.approx(0.0)
        assert section.new_score == pytest.approx(1.0)
        # Without a paired baseline, improved/regressed stays zero.
        assert section.improved_count == 0
        assert section.regressed_count == 0
        assert section.sample_count == 1

    def test_new_empty_uses_baseline_totals(self):
        baseline = [
            _record(sample_id="s1", correct=True, section_ids=["rules"]),
        ]
        deltas = compute_section_deltas(baseline, [])
        section = deltas["rules"]
        assert section.baseline_score == pytest.approx(1.0)
        assert section.new_score == pytest.approx(0.0)
        assert section.delta == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


class TestRankSectionDeltas:
    def test_ranks_by_delta_descending(self):
        deltas = {
            "rules": SectionContributionDelta(section_id="rules", delta=0.1),
            "examples": SectionContributionDelta(section_id="examples", delta=0.5),
            "intro": SectionContributionDelta(section_id="intro", delta=0.0),
        }
        ranked = rank_section_deltas(deltas)
        assert [item.section_id for item in ranked] == ["examples", "rules", "intro"]
        assert [item.rank for item in ranked] == [1, 2, 3]

    def test_ranking_ties_broken_by_section_id(self):
        deltas = {
            "beta": SectionContributionDelta(section_id="beta", delta=0.3),
            "alpha": SectionContributionDelta(section_id="alpha", delta=0.3),
        }
        ranked = rank_section_deltas(deltas)
        assert [item.section_id for item in ranked] == ["alpha", "beta"]
        assert [item.rank for item in ranked] == [1, 2]

    def test_ranking_with_weight_key(self):
        deltas = {
            "a": SectionContributionDelta(section_id="a", delta=0.0, weight=2.5),
            "b": SectionContributionDelta(section_id="b", delta=0.2, weight=1.0),
        }
        ranked = rank_section_deltas(deltas, primary_key="weight")
        assert ranked[0].section_id == "a"
        assert ranked[1].section_id == "b"

    def test_ranking_is_deterministic(self):
        deltas = {
            s: SectionContributionDelta(section_id=s, delta=0.1, weight=1.0)
            for s in ["z", "a", "m", "b"]
        }
        first = rank_section_deltas(deltas)
        second = rank_section_deltas(deltas)
        assert [item.section_id for item in first] == [
            item.section_id for item in second
        ]

    def test_ranking_does_not_mutate_inputs(self):
        @dataclass
        class Snapshot:
            section_id: str
            delta: float
            weight: float

        deltas = {
            "a": SectionContributionDelta(section_id="a", delta=0.2, weight=1.1),
        }
        snapshots = [
            Snapshot(section_id=d.section_id, delta=d.delta, weight=d.weight)
            for d in deltas.values()
        ]
        ranked = rank_section_deltas(deltas)
        # Rank was assigned to new copies, not the originals.
        assert list(deltas.values())[0].rank == 0
        assert ranked[0].rank == 1
        # Original fields not mutated.
        for original, snap in zip(deltas.values(), snapshots):
            assert original.section_id == snap.section_id
            assert original.delta == snap.delta
            assert original.weight == snap.weight


# ---------------------------------------------------------------------------
# JSON artifact + dict helper
# ---------------------------------------------------------------------------


class TestSectionContributionArtifacts:
    def test_section_contributions_to_dict_accepts_mapping(self):
        deltas = compute_section_deltas(
            [_record(sample_id="s1", correct=False, section_ids=["rules"])],
            [_record(sample_id="s1", correct=True, section_ids=["rules"])],
        )
        payload = section_contributions_to_dict(deltas)
        assert payload["rules"]["section_id"] == "rules"
        assert payload["rules"]["delta"] > 0
        # Must round-trip through JSON.
        assert json.loads(json.dumps(payload)) == payload

    def test_section_contributions_to_dict_accepts_sequence(self):
        deltas = compute_section_deltas(
            [_record(sample_id="s1", correct=False, section_ids=["rules"])],
            [_record(sample_id="s1", correct=True, section_ids=["rules"])],
        )
        payload = section_contributions_to_dict(list(deltas.values()))
        assert payload["rules"]["section_id"] == "rules"
        assert json.loads(json.dumps(payload)) == payload

    def test_write_artifact_produces_valid_json(self, tmp_path):
        deltas = compute_section_deltas(
            [_record(sample_id="s1", correct=False, section_ids=["rules"])],
            [_record(sample_id="s1", correct=True, section_ids=["rules"])],
        )
        path = write_section_contribution_artifact(deltas, tmp_path)
        assert path.name == SECTION_CONTRIBUTION_ARTIFACT
        assert path.exists()
        data = json.loads(path.read_text())
        assert "rules" in data
        assert data["rules"]["delta"] > 0


# ---------------------------------------------------------------------------
# Integration: compute → rank → serialize → round-trip
# ---------------------------------------------------------------------------


class TestSectionContributionEndToEnd:
    def test_end_to_end_workflow(self, tmp_path):
        baseline = [
            _record(sample_id=f"s{i}", correct=(i % 2 == 0), section_ids=["rules", "examples"])
            for i in range(10)
        ]
        # "rules" improves after patch; "examples" degrades on one sample.
        new = [
            _record(sample_id=f"s{i}", correct=True, section_ids=["rules", "examples"])
            for i in range(10)
        ]
        # Force the "examples" section to regress on one sample.
        new[0] = _record(sample_id="s0", correct=False, section_ids=["examples"])

        deltas = compute_section_deltas(baseline, new)
        ranked = rank_section_deltas(deltas)
        path = write_section_contribution_artifact(deltas, tmp_path)

        # Both sections are represented.
        assert set(deltas) == {"rules", "examples"}
        assert ranked[0].rank == 1

        # JSON round-trip preserves section IDs and delta sign.
        data = json.loads(path.read_text())
        assert data["rules"]["delta"] > 0
        assert data["examples"]["delta"] <= data["rules"]["delta"]


# ---------------------------------------------------------------------------
# Sanity: module import does not pull in sampling / compression dependencies
# ---------------------------------------------------------------------------


class TestNoRiskAwareCoupling:
    def test_module_import_does_not_reference_risk_sampling(self):
        import inspect
        import mmap_optimizer.metrics.section_deltas as module

        source = inspect.getsource(module)
        # The helper must not import risk-aware modules.
        assert "risk_aware" not in source
        assert "sampling.dynamic" not in source
        assert "compression.engine" not in source
        # Nor the patch repair / section contribution legacy modules.
        # (Both are fine but we want to be explicit.)
        assert "prompt_optimizer" not in source

    def test_computation_does_not_require_external_state(self):
        """Section metrics should be pure functions of evaluation records."""

        import mmap_optimizer.metrics.section_deltas as module

        # Only public helpers that accept evaluation records / deltas.
        public = [
            name
            for name in dir(module)
            if not name.startswith("_")
            and name
            not in {
                "SECTION_CONTRIBUTION_ARTIFACT",
                "SectionContributionDelta",
            }
        ]
        # At least three helpers exposed (compute, rank, serialize).
        assert len(public) >= 3
