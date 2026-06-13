"""Semantic compression helpers with LLM step audit records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecorder, get_current_recorder, hash_prompt

PRUNE_TEMPLATE_ID = "compression.semantic_prune.v1"
VALIDATION_TEMPLATE_ID = "compression.semantic_validation.v1"


@dataclass(slots=True)
class SemanticCompressionResult:
    pruned_items: list[Any]
    prune_raw_output: str
    prune_parse_success: bool
    validation_raw_output: str
    validation_parse_success: bool
    validation_success: bool
    validation_reason: str | None
    fallback_used: bool
    error_type: str | None = None


def _parse_prune_output(raw_output: str) -> list[Any]:
    parsed = json.loads(raw_output)
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        return parsed["items"]
    if isinstance(parsed, dict) and isinstance(parsed.get("pruned_items"), list):
        return parsed["pruned_items"]
    if isinstance(parsed, list):
        return parsed
    raise ValueError("prune output did not contain items")


def _parse_validation_output(raw_output: str) -> tuple[bool, str | None]:
    parsed = json.loads(raw_output)
    if not isinstance(parsed, dict):
        raise ValueError("validation output was not an object")
    valid = parsed.get("valid", parsed.get("success", parsed.get("ok")))
    if not isinstance(valid, bool):
        raise ValueError("validation output did not contain a boolean valid field")
    reason = parsed.get("reason")
    return valid, str(reason) if reason is not None else None


def semantic_prune_and_validate(
    items: Sequence[Any],
    prune_model_call: Callable[[str], str],
    validation_model_call: Callable[[str], str],
    *,
    prune_template_id: str = PRUNE_TEMPLATE_ID,
    validation_template_id: str = VALIDATION_TEMPLATE_ID,
    prune_prompt: str | None = None,
    validation_prompt: str | None = None,
    recorder: LLMStepRecorder | None = None,
) -> SemanticCompressionResult:
    """Prune items and validate the result while recording both LLM outputs."""

    active_recorder = recorder or get_current_recorder()
    prune_prompt = prune_prompt or json.dumps({"items": list(items)}, ensure_ascii=False)
    prune_raw_output = prune_model_call(prune_prompt)
    prune_parse_success = False
    fallback_used = False
    error_type: str | None = None

    try:
        pruned_items = _parse_prune_output(prune_raw_output)
        prune_parse_success = True
    except json.JSONDecodeError:
        pruned_items = list(items)
        fallback_used = True
        error_type = "json_decode_error"
    except ValueError:
        pruned_items = list(items)
        fallback_used = True
        error_type = "missing_pruned_items"

    if active_recorder is not None:
        active_recorder.record_step(
            step_type="semantic_prune",
            template_id=prune_template_id,
            prompt_hash=hash_prompt(prune_prompt),
            input_summary={"input_count": len(items)},
            raw_output=prune_raw_output,
            parse_success=prune_parse_success,
            fallback_used=fallback_used,
            error_type=error_type,
            metadata={"output_count": len(pruned_items)},
        )

    validation_prompt = validation_prompt or json.dumps({"items": pruned_items}, ensure_ascii=False)
    validation_raw_output = validation_model_call(validation_prompt)
    validation_parse_success = False
    validation_success = False
    validation_reason: str | None = None
    validation_error_type: str | None = None

    try:
        validation_success, validation_reason = _parse_validation_output(validation_raw_output)
        validation_parse_success = True
        if not validation_success:
            fallback_used = True
            if validation_reason is None:
                validation_reason = "validation failed"
    except json.JSONDecodeError:
        validation_reason = "validation output was invalid JSON"
        validation_error_type = "json_decode_error"
        fallback_used = True
    except ValueError as exc:
        validation_reason = str(exc)
        validation_error_type = "invalid_validation_output"
        fallback_used = True

    if fallback_used and (not validation_success or not prune_parse_success):
        pruned_items = list(items)

    if active_recorder is not None:
        active_recorder.record_step(
            step_type="semantic_validation",
            template_id=validation_template_id,
            prompt_hash=hash_prompt(validation_prompt),
            input_summary={"candidate_count": len(pruned_items)},
            raw_output=validation_raw_output,
            parse_success=validation_parse_success,
            fallback_used=fallback_used and not validation_success,
            error_type=validation_error_type,
            metadata={"validation_success": validation_success, "validation_reason": validation_reason},
        )

    return SemanticCompressionResult(
        pruned_items=pruned_items,
        prune_raw_output=prune_raw_output,
        prune_parse_success=prune_parse_success,
        validation_raw_output=validation_raw_output,
        validation_parse_success=validation_parse_success,
        validation_success=validation_success,
        validation_reason=validation_reason,
        fallback_used=fallback_used,
        error_type=error_type or validation_error_type,
    )


semantic_compress = semantic_prune_and_validate
