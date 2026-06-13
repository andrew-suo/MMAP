from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.model.client import ModelClient

from mmap_optimizer.analysis.repair import repair_json_text
from mmap_optimizer.analysis.schema import ANALYSIS_OUTPUT_REQUIRED_FIELDS, PATCH_CANDIDATE_REQUIRED_FIELDS


@dataclass
class InvalidPatchCandidate:
    index: int
    reason: str
    candidate: Any


@dataclass
class AnalysisParseResult:
    parsed: dict[str, Any]
    parse_success: bool
    schema_valid: bool
    status: str
    errors: list[str] = field(default_factory=list)
    repaired: bool = False
    repair_actions: list[str] = field(default_factory=list)
    valid_patch_candidates: list[dict[str, Any]] = field(default_factory=list)
    invalid_patch_candidates: list[InvalidPatchCandidate] = field(default_factory=list)


def parse_analysis_output(raw_output: str | None) -> AnalysisParseResult:
    repaired_text, repaired, repair_actions = repair_json_text(raw_output or "")
    try:
        parsed = json.loads(repaired_text)
    except json.JSONDecodeError as exc:
        return AnalysisParseResult(
            parsed={"judgement": {"is_correct": False}, "patch_candidates": []},
            parse_success=False,
            schema_valid=False,
            status="parse_error",
            errors=[f"JSON_DECODE_ERROR:{exc.msg}"],
            repaired=repaired,
            repair_actions=repair_actions,
        )
    if not isinstance(parsed, dict):
        return AnalysisParseResult(
            parsed={"judgement": {"is_correct": False}, "patch_candidates": []},
            parse_success=True,
            schema_valid=False,
            status="schema_error",
            errors=["ROOT_NOT_OBJECT"],
            repaired=repaired,
            repair_actions=repair_actions,
        )
    schema_errors = _analysis_schema_errors(parsed)
    valid_candidates, invalid_candidates = _partition_patch_candidates(parsed.get("patch_candidates", []))
    if invalid_candidates:
        schema_errors.extend(f"PATCH_CANDIDATE_{item.index}:{item.reason}" for item in invalid_candidates)
    schema_valid = not schema_errors
    status = "valid" if schema_valid else "schema_error"
    if schema_valid and not valid_candidates:
        status = "empty_patch_candidates"
    return AnalysisParseResult(
        parsed=parsed,
        parse_success=True,
        schema_valid=schema_valid,
        status=status,
        errors=schema_errors,
        repaired=repaired,
        repair_actions=repair_actions,
        valid_patch_candidates=valid_candidates,
        invalid_patch_candidates=invalid_candidates,
    )


def parse_analysis_output_with_repair(
    raw_output: str | None,
    *,
    repair_client: ModelClient | None = None,
    repair_model_config: dict[str, Any] | None = None,
    enable_llm_repair: bool = False,
    max_attempts: int = 1,
) -> AnalysisParseResult:
    initial = parse_analysis_output(raw_output)
    if initial.parse_success or not enable_llm_repair or repair_client is None:
        return initial
    from mmap_optimizer.analysis.llm_repair import repair_json_with_model

    last = initial
    for attempt in range(max(0, max_attempts)):
        repaired_text = repair_json_with_model(raw_output or "", repair_client, repair_model_config)
        repaired = parse_analysis_output(repaired_text)
        repaired.repaired = True
        repaired.repair_actions = [*initial.repair_actions, f"LLM_JSON_REPAIR_ATTEMPT_{attempt + 1}", *repaired.repair_actions]
        if repaired.parse_success:
            return repaired
        last = repaired
    return last


def _analysis_schema_errors(parsed: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ANALYSIS_OUTPUT_REQUIRED_FIELDS:
        if field not in parsed:
            errors.append(f"MISSING_FIELD:{field}")
    if "judgement" in parsed and not isinstance(parsed["judgement"], dict):
        errors.append("judgement expected object")
    for field in ["confirmed_facts", "hypothesized_error_causes", "prompt_section_attribution", "patch_candidates"]:
        if field in parsed and not isinstance(parsed[field], list):
            errors.append(f"{field} expected array")
    judgement = parsed.get("judgement") if isinstance(parsed.get("judgement"), dict) else {}
    if "is_correct" not in judgement:
        errors.append("MISSING_FIELD:judgement.is_correct")
    elif not isinstance(judgement.get("is_correct"), bool):
        errors.append("judgement.is_correct expected boolean")
    return errors


def _partition_patch_candidates(value: Any) -> tuple[list[dict[str, Any]], list[InvalidPatchCandidate]]:
    if not isinstance(value, list):
        return [], []
    valid: list[dict[str, Any]] = []
    invalid: list[InvalidPatchCandidate] = []
    for idx, candidate in enumerate(value):
        if not isinstance(candidate, dict):
            invalid.append(InvalidPatchCandidate(index=idx, reason="NOT_OBJECT", candidate=candidate))
            continue
        missing = [field for field in PATCH_CANDIDATE_REQUIRED_FIELDS if candidate.get(field) is None or candidate.get(field) == ""]
        if missing:
            invalid.append(InvalidPatchCandidate(index=idx, reason="MISSING_FIELDS:" + ",".join(missing), candidate=candidate))
            continue
        valid.append(candidate)
    return valid, invalid
