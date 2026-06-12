from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.core.enums import EvaluationStatus
from mmap_optimizer.dataset.sample import GroundTruth
from mmap_optimizer.prompt.contract import OutputSchemaContract
from .schema_validator import SimpleJsonSchemaValidator


@dataclass
class EvaluationRecord:
    id: str
    round_id: str
    run_id: str
    sample_id: str
    ground_truth_id: str
    parse_success: bool
    schema_valid: bool
    primary_answer_correct: bool
    overall_status: str
    prediction: Any = None
    normalized_prediction: Any = None
    normalized_ground_truth: Any = None
    schema_errors: list[str] = field(default_factory=list)
    used_prompt_sections: list[dict[str, Any]] = field(default_factory=list)


def normalize_label(value: Any, mapping: dict[str, Any] | None = None) -> Any:
    if mapping is None:
        mapping = {"合格": "OK", "正常": "OK", "不合格": "NG", "异常": "NG", "无法确认": "UNCERTAIN", "不确定": "UNCERTAIN"}
    if isinstance(value, str):
        return mapping.get(value, mapping.get(value.upper(), value.upper()))
    return value


class Evaluator:
    def __init__(self, label_mapping: dict[str, Any] | None = None):
        self.label_mapping = label_mapping
        self.validator = SimpleJsonSchemaValidator()

    def evaluate(self, *, round_id: str, run_id: str, sample_id: str, raw_output: str | dict[str, Any] | None, ground_truth: GroundTruth, contract: OutputSchemaContract) -> EvaluationRecord:
        parsed: dict[str, Any] | None = None
        parse_success = False
        if isinstance(raw_output, dict):
            parsed = raw_output
            parse_success = True
        elif isinstance(raw_output, str):
            try:
                parsed = json.loads(raw_output)
                parse_success = True
            except json.JSONDecodeError:
                parsed = None
        if not parse_success or parsed is None:
            return EvaluationRecord(
                id=f"eval_{run_id}", round_id=round_id, run_id=run_id, sample_id=sample_id, ground_truth_id=ground_truth.id,
                parse_success=False, schema_valid=False, primary_answer_correct=False, overall_status=EvaluationStatus.PARSE_ERROR.value,
            )
        policy = contract.validation_policy
        schema_result = self.validator.validate(parsed, contract.schema, extra_fields_allowed=policy.get("extra_fields_allowed", False))
        primary_field = contract.primary_answer_fields[0]
        prediction = parsed.get(primary_field)
        norm_prediction = normalize_label(prediction, self.label_mapping)
        norm_gt = normalize_label(ground_truth.primary_answer, self.label_mapping)
        correct = schema_result.valid and norm_prediction == norm_gt
        status = EvaluationStatus.CORRECT.value if correct else (EvaluationStatus.SCHEMA_ERROR.value if not schema_result.valid else EvaluationStatus.WRONG.value)
        return EvaluationRecord(
            id=f"eval_{run_id}", round_id=round_id, run_id=run_id, sample_id=sample_id, ground_truth_id=ground_truth.id,
            parse_success=True, schema_valid=schema_result.valid, primary_answer_correct=correct, overall_status=status,
            prediction=prediction, normalized_prediction=norm_prediction, normalized_ground_truth=norm_gt,
            schema_errors=schema_result.errors, used_prompt_sections=parsed.get("used_prompt_sections", []),
        )
