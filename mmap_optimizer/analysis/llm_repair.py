"""JSON repair helpers backed by optional LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecord, coerce_input_refs, hash_prompt
from mmap_optimizer.orchestration.round_runner import write_llm_step

ModelCallable = Callable[[str], str]


@dataclass(slots=True)
class JSONRepairResult:
    """Structured result returned by :func:`repair_json_with_model`."""

    text: str
    value: Any | None
    raw_output: str
    parse_success: bool
    fallback_used: bool
    error_type: str | None
    accepted_output_summary: str
    record: LLMStepRecord

    def __str__(self) -> str:
        """Return repaired text for callers that stringify the result."""

        return self.text


def _parse_json(text: str) -> tuple[bool, Any | None, str | None]:
    try:
        return True, json.loads(text), None
    except json.JSONDecodeError as exc:
        return False, None, type(exc).__name__


def _summarize_value(value: Any, text: str) -> str:
    if isinstance(value, dict):
        return f"json object with keys: {', '.join(map(str, list(value)[:8]))}"
    if isinstance(value, list):
        return f"json array with {len(value)} items"
    if value is not None:
        return f"json {type(value).__name__}"
    return text[:160]


def repair_json_with_model(
    text: str,
    model: ModelCallable | None = None,
    *,
    prompt: str | None = None,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    input_refs: list[str] | str | None = None,
    template_id: str = "json_repair",
    fallback_text: str | None = None,
) -> JSONRepairResult:
    """Repair JSON and return a structured, auditable result.

    If ``text`` already parses, no model call is required.  When invalid JSON is
    supplied and no model (or an invalid model response) can repair it, the
    function returns a fallback result and still emits an LLM record when
    ``artifact_root`` is provided.
    """

    parse_success, value, error_type = _parse_json(text)
    if parse_success:
        accepted = text
        raw_output = text
        fallback_used = False
    else:
        repair_prompt = prompt or f"Repair this invalid JSON and return only JSON:\n{text}"
        raw_output = ""
        model_error: str | None = None
        if model is not None:
            try:
                raw_output = model(repair_prompt)
            except Exception as exc:  # noqa: BLE001 - preserve provider errors as artifact metadata.
                model_error = type(exc).__name__
                raw_output = ""
        candidate = raw_output or (fallback_text if fallback_text is not None else text)
        parse_success, value, candidate_error = _parse_json(candidate)
        if parse_success:
            accepted = candidate
            fallback_used = False
            error_type = None
        else:
            accepted = fallback_text if fallback_text is not None else text
            fallback_used = True
            error_type = model_error or candidate_error or error_type
            parse_success, value, _ = _parse_json(accepted)

    summary = _summarize_value(value, accepted)
    record = LLMStepRecord(
        round_id=round_id,
        step_type="json_repair",
        template_id=template_id,
        prompt_hash=hash_prompt(prompt or text),
        input_refs=coerce_input_refs(input_refs),
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=error_type,
        accepted_output_summary=summary,
    )
    if artifact_root is not None:
        write_llm_step(artifact_root, round_id, record)
    return JSONRepairResult(
        text=accepted,
        value=value,
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=error_type,
        accepted_output_summary=summary,
        record=record,
    )
