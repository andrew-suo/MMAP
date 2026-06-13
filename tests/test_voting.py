import pytest

from mmap_optimizer.evaluation.metrics import compute_evaluation_metrics
from mmap_optimizer.evaluation.voting import INVALID_VOTE, collect_eval_votes, majority_vote


class DummyEvalModel:
    model_id = "dummy-eval"

    def __init__(self, judgements):
        self.judgements = list(judgements)
        self.calls = []

    def judge(self, sample, *, round_index):
        self.calls.append((sample, round_index))
        return self.judgements[round_index]


def test_three_votes_unanimous():
    model = DummyEvalModel([
        '{"vote": "pass"}',
        '{"status": "pass"}',
        {"judgement": "PASS"},
    ])

    result = collect_eval_votes({"id": "sample-without-gt"}, model)

    assert result.votes == {"pass": 3}
    assert result.majority_status == "pass"
    assert result.confidence == 1.0
    assert result.model_ids == ["dummy-eval", "dummy-eval", "dummy-eval"]
    assert result.is_ground_truth_backed is False
    assert [call[1] for call in model.calls] == [0, 1, 2]


def test_two_to_one_majority_is_weak_label():
    result = majority_vote([
        '{"vote": "pass"}',
        '{"vote": "fail"}',
        '{"vote": "pass"}',
    ])

    assert result.votes == {"pass": 2, "fail": 1}
    assert result.majority_status == "pass"
    assert result.confidence == pytest.approx(2 / 3)
    assert result.is_ground_truth_backed is False


def test_three_way_conflict_has_no_majority():
    result = majority_vote([
        '{"vote": "pass"}',
        '{"vote": "fail"}',
        '{"vote": "uncertain"}',
    ])

    assert result.votes == {"pass": 1, "fail": 1, "uncertain": 1}
    assert result.majority_status is None
    assert result.confidence == pytest.approx(1 / 3)


def test_invalid_json_vote_fallback():
    result = majority_vote([
        "not-json",
        '{"vote": "pass"}',
        '{"status": "pass"}',
    ])

    assert result.votes == {INVALID_VOTE: 1, "pass": 2}
    assert result.majority_status == "pass"
    assert result.confidence == pytest.approx(2 / 3)
    assert result.raw_judgements[0] == {"raw": "not-json", "parse_error": "invalid_json"}


def test_weak_voting_rejects_ground_truth_samples():
    model = DummyEvalModel(['{"vote": "pass"}'] * 3)

    with pytest.raises(ValueError):
        collect_eval_votes({"id": "sample-with-gt", "ground_truth": "answer"}, model)


def test_metrics_separate_gt_accuracy_from_weak_vote_agreement():
    weak_result = majority_vote([
        '{"vote": "pass"}',
        '{"vote": "pass"}',
        '{"vote": "fail"}',
    ])

    metrics = compute_evaluation_metrics([
        {"gt_correct": True},
        {"gt_correct": False},
        {"vote_result": weak_result},
    ])

    assert metrics["gt_accuracy"] == 0.5
    assert metrics["weak_vote_agreement"] == pytest.approx(2 / 3)
