from __future__ import annotations

import json
from collections import Counter
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
    extra: dict[str, Any] = field(default_factory=dict)


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


    def evaluate_without_ground_truth(
        self,
        *,
        round_id: str,
        run_id: str,
        sample_id: str,
        raw_outputs: list[str | dict[str, Any] | None],
        contract: OutputSchemaContract,
    ) -> EvaluationRecord:
        parsed_outputs: list[dict[str, Any]] = []
        parse_errors = 0
        for raw_output in raw_outputs:
            parsed = self._parse_output(raw_output)
            if parsed is None:
                parse_errors += 1
            else:
                parsed_outputs.append(parsed)
        if not parsed_outputs:
            return EvaluationRecord(
                id=f"eval_{run_id}",
                round_id=round_id,
                run_id=run_id,
                sample_id=sample_id,
                ground_truth_id="NO_GT",
                parse_success=False,
                schema_valid=False,
                primary_answer_correct=False,
                overall_status=EvaluationStatus.PARSE_ERROR.value,
                extra={"no_ground_truth": True, "vote_rounds": len(raw_outputs), "parse_errors": parse_errors},
            )
        primary_field = contract.primary_answer_fields[0]
        policy = contract.validation_policy
        schema_results = [
            self.validator.validate(parsed, contract.schema, extra_fields_allowed=policy.get("extra_fields_allowed", False))
            for parsed in parsed_outputs
        ]
        valid_predictions = [
            normalize_label(parsed.get(primary_field), self.label_mapping)
            for parsed, result in zip(parsed_outputs, schema_results, strict=False)
            if result.valid
        ]
        if not valid_predictions:
            first = parsed_outputs[0]
            return EvaluationRecord(
                id=f"eval_{run_id}",
                round_id=round_id,
                run_id=run_id,
                sample_id=sample_id,
                ground_truth_id="NO_GT",
                parse_success=True,
                schema_valid=False,
                primary_answer_correct=False,
                overall_status=EvaluationStatus.SCHEMA_ERROR.value,
                prediction=first.get(primary_field),
                normalized_prediction=normalize_label(first.get(primary_field), self.label_mapping),
                schema_errors=[error for result in schema_results for error in result.errors],
                used_prompt_sections=first.get("used_prompt_sections", []),
                extra={"no_ground_truth": True, "vote_rounds": len(raw_outputs), "parse_errors": parse_errors},
            )
        counts = Counter(valid_predictions)
        majority, majority_count = counts.most_common(1)[0]
        first = parsed_outputs[0]
        first_norm = normalize_label(first.get(primary_field), self.label_mapping)
        return EvaluationRecord(
            id=f"eval_{run_id}",
            round_id=round_id,
            run_id=run_id,
            sample_id=sample_id,
            ground_truth_id="NO_GT",
            parse_success=True,
            schema_valid=True,
            primary_answer_correct=first_norm == majority,
            overall_status=EvaluationStatus.CORRECT.value,
            prediction=first.get(primary_field),
            normalized_prediction=first_norm,
            normalized_ground_truth=majority,
            used_prompt_sections=first.get("used_prompt_sections", []),
            extra={
                "no_ground_truth": True,
                "vote_rounds": len(raw_outputs),
                "parse_errors": parse_errors,
                "vote_majority": majority,
                "vote_confidence": majority_count / max(1, len(valid_predictions)),
                "votes": valid_predictions,
            },
        )

    def _parse_output(self, raw_output: str | dict[str, Any] | None) -> dict[str, Any] | None:
        if isinstance(raw_output, dict):
            return raw_output
        if isinstance(raw_output, str):
            try:
                parsed = json.loads(raw_output)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else None
        return None

    def evaluate(self, *, round_id: str, run_id: str, sample_id: str, raw_output: str | dict[str, Any] | None, ground_truth: GroundTruth, contract: OutputSchemaContract) -> EvaluationRecord:
        parsed = self._parse_output(raw_output)
        if parsed is None:
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
