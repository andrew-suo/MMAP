import pytest

from mmap_optimizer.metrics.round_metrics import RoundMetrics
from mmap_optimizer.metrics.trend import build_metrics_trend


def metrics(round_id: str, batch_accuracy: float, dval_accuracy: float | None, analysis_rate: float = 1.0) -> RoundMetrics:
    return RoundMetrics(
        id=f"metrics_{round_id}",
        round_id=round_id,
        batch_accuracy=batch_accuracy,
        dynamic_validation_raw_accuracy=dval_accuracy,
        dynamic_validation_weighted_accuracy=dval_accuracy,
        schema_valid_rate=1.0,
        format_error_rate=0.0,
        parse_error_rate=0.0,
        accepted_count=1,
        rejected_count=2,
        toxic_count=0,
        analysis_judgement_match_rate=analysis_rate,
        merge_conflict_count=1,
        merge_duplicate_count=3,
    )


def test_build_metrics_trend_tracks_best_rounds_and_regressions():
    trend = build_metrics_trend(
        [
            metrics("round_000001", batch_accuracy=0.5, dval_accuracy=0.6, analysis_rate=1.0),
            metrics("round_000002", batch_accuracy=0.75, dval_accuracy=0.7, analysis_rate=0.5),
            metrics("round_000003", batch_accuracy=0.5, dval_accuracy=0.4, analysis_rate=0.5),
        ]
    )

    assert trend.round_count == 3
    assert trend.best_batch_round_id == "round_000002"
    assert trend.best_dynamic_validation_round_id == "round_000002"
    assert trend.batch_accuracy_delta_total == 0.0
    assert trend.dynamic_validation_accuracy_delta_total == pytest.approx(-0.2)
    assert trend.total_accepted_patches == 3
    assert trend.total_rejected_patches == 6
    assert trend.total_merge_conflicts == 3
    assert trend.total_merge_duplicates == 9
    assert trend.regression_round_ids == ["round_000003"]
    assert trend.analysis_regression_round_ids == ["round_000002"]
    assert trend.points[1].batch_accuracy_delta == 0.25
    assert trend.points[2].dynamic_validation_regressed is True
