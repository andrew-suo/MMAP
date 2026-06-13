from __future__ import annotations

from tests._compat import candidate_modules, find_symbol

EVAL_MODULES = candidate_modules(
    "mmap.eval_voting",
    "mmap.evaluation.voting",
    "mmap.eval.voting",
    "mmap_engine.eval_voting",
    "src.eval_voting",
)


def test_no_ground_truth_three_round_voting_uses_majority_and_records_rounds() -> None:
    vote = find_symbol(EVAL_MODULES, "vote_without_ground_truth", "run_no_gt_voting", "three_round_vote")

    result = vote(
        candidates=["patch-a", "patch-b", "patch-a"],
        rounds=3,
        ground_truth=None,
        judges=["judge-1", "judge-2", "judge-3"],
    )

    assert result["winner"] == "patch-a"
    assert result["ground_truth_used"] is False
    assert len(result["rounds"]) == 3
    assert all("votes" in round_result for round_result in result["rounds"])
