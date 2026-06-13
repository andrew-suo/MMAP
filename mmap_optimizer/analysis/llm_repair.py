"""LLM-backed repair helpers with structured parse/fallback metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecorder, get_current_recorder, hash_prompt

DEFAULT_TEMPLATE_ID = "analysis.llm_repair.v1"


@dataclass(slots=True)
class LLMRepairResult:
    """Structured result for a repair attempt."""

    repaired_text: str
    raw_output: str
    parse_success: bool
    fallback_used: bool
    error_type: str | None = None
    parsed_output: Mapping[str, Any] | None = None

    def __str__(self) -> str:
        return self.repaired_text


def _extract_repaired_text(parsed: Any) -> str:
    if isinstance(parsed, dict):
        for key in ("repaired_text", "text", "content", "result"):
            value = parsed.get(key)
            if isinstance(value, str):
                return value
    if isinstance(parsed, str):
        return parsed
    raise ValueError("repair output did not contain repaired text")


def repair_text(
    text: str,
    model_call: Callable[[str], str],
    *,
    round_id: str | None = None,
    template_id: str = DEFAULT_TEMPLATE_ID,
    prompt: str | None = None,
    recorder: LLMStepRecorder | None = None,
) -> LLMRepairResult:
    """Repair ``text`` with an LLM and return raw output plus parse/fallback metadata.

    The model is expected to return JSON containing one of ``repaired_text``, ``text``,
    ``content``, or ``result``. Invalid JSON (or JSON without repair content) falls
    back to the original input text and is recorded as such.
    """

    prompt = prompt or f"Repair the following text and respond with JSON: {text}"
    raw_output = model_call(prompt)
    parse_success = False
    fallback_used = False
    error_type: str | None = None
    parsed_mapping: Mapping[str, Any] | None = None

    try:
        parsed = json.loads(raw_output)
        repaired_text = _extract_repaired_text(parsed)
        parse_success = True
        if isinstance(parsed, Mapping):
            parsed_mapping = parsed
    except json.JSONDecodeError:
        repaired_text = text
        fallback_used = True
        error_type = "json_decode_error"
    except (TypeError, ValueError, KeyError):
        repaired_text = text
        fallback_used = True
        error_type = "missing_repaired_text"

    result = LLMRepairResult(
        repaired_text=repaired_text,
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=error_type,
        parsed_output=parsed_mapping,
    )

    active_recorder = recorder or get_current_recorder()
    if active_recorder is not None:
        active_recorder.record_step(
            step_type="llm_repair",
            template_id=template_id,
            prompt_hash=hash_prompt(prompt),
            input_summary={"input_chars": len(text)},
            raw_output=raw_output,
            parse_success=parse_success,
            fallback_used=fallback_used,
            error_type=error_type,
            metadata={"round_id_arg": round_id} if round_id is not None else {},
        )

    return result


# Backwards-compatible alias for callers that use the module as a simple repair helper.
repair = repair_text
