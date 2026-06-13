from __future__ import annotations

from mmap_optimizer.core.enums import Transition
from mmap_optimizer.evaluation.evaluator import EvaluationRecord


def classify_transition(base: EvaluationRecord, patched: EvaluationRecord) -> str:
    base_correct = base.overall_status == "correct"
    patched_correct = patched.overall_status == "correct"
    if not base_correct and patched_correct:
        return Transition.FIXED.value
    if base_correct and not patched_correct:
        return Transition.BROKEN.value
    if not base_correct and not patched_correct:
        return Transition.UNCHANGED_WRONG.value
    return Transition.UNCHANGED_CORRECT.value
