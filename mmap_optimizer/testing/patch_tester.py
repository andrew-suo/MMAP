from __future__ import annotations

from dataclasses import dataclass, field

from mmap_optimizer.evaluation.evaluator import EvaluationRecord
from .transition import classify_transition


@dataclass
class PatchTestSuite:
    id: str
    round_id: str
    sample_ids: list[str]
    suite_type: str = "individual_patch"
    composition: dict[str, int] = field(default_factory=dict)


@dataclass
class PatchTestResult:
    id: str
    round_id: str
    patch_id: str | None
    test_suite_id: str
    fixed_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    unchanged_wrong_sample_ids: list[str] = field(default_factory=list)
    unchanged_correct_sample_ids: list[str] = field(default_factory=list)
    schema_violation_count: int = 0
    format_error_count: int = 0
    parse_error_count: int = 0
    canary_broken_count: int = 0
    historical_fixed_regression_count: int = 0
    accepted: bool = False
    effectiveness_result: str = "not_tested"
    toxicity_result: str = "not_tested"
    rejection_reason: str | None = None


def summarize_patch_test(
    round_id: str,
    patch_id: str | None,
    suite_id: str,
    base_evals: list[EvaluationRecord],
    patched_evals: list[EvaluationRecord],
    *,
    canary_sample_ids: list[str] | None = None,
    historically_fixed_sample_ids: list[str] | None = None,
) -> PatchTestResult:
    by_base = {e.sample_id: e for e in base_evals}
    result = PatchTestResult(id=f"ptest_{round_id}_{patch_id or 'bundle'}", round_id=round_id, patch_id=patch_id, test_suite_id=suite_id)
    canary_ids = set(canary_sample_ids or [])
    hist_fixed_ids = set(historically_fixed_sample_ids or [])
    for patched in patched_evals:
        base = by_base.get(patched.sample_id)
        if base is None:
            continue
        transition = classify_transition(base, patched)
        if transition == "fixed":
            result.fixed_sample_ids.append(patched.sample_id)
        elif transition == "broken":
            result.broken_sample_ids.append(patched.sample_id)
        elif transition == "unchanged_wrong":
            result.unchanged_wrong_sample_ids.append(patched.sample_id)
        else:
            result.unchanged_correct_sample_ids.append(patched.sample_id)
        if patched.overall_status == "schema_error":
            result.schema_violation_count += 1
        if patched.overall_status == "parse_error":
            result.parse_error_count += 1
        # Canary protection: canary sample broken
        if patched.sample_id in canary_ids and patched.overall_status != "correct":
            result.canary_broken_count += 1
        # Historical regression: previously fixed sample regressed
        if patched.sample_id in hist_fixed_ids and patched.overall_status != "correct":
            result.historical_fixed_regression_count += 1
    result.effectiveness_result = "effective" if result.fixed_sample_ids else "ineffective"
    result.toxicity_result = "toxic" if result.broken_sample_ids else "non_toxic"
    result.accepted = bool(result.fixed_sample_ids) and not result.broken_sample_ids and result.schema_violation_count == 0 and result.parse_error_count == 0
    if not result.accepted:
        result.rejection_reason = "TOXIC" if result.broken_sample_ids else "INEFFECTIVE"
    # Canary broken overrides: even if patch fixes samples, canary breakage means rejection
    if result.canary_broken_count > 0:
        result.accepted = False
        result.rejection_reason = "CANARY_BROKEN"
    # Historical regression: previously fixed sample regressed means rejection
    elif result.historical_fixed_regression_count > 0:
        result.accepted = False
        result.rejection_reason = "HISTORICAL_REGRESSION"
    return result
