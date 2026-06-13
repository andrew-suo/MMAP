"""Utilities for structured JSON repair/auditing of LLM output."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable

from mmap_optimizer.orchestration.llm_records import LLMStepRecord, prompt_hash, record_llm_step


@dataclass(slots=True)
class LLMRepairResult:
    """Structured result returned by JSON repair helpers."""

    repaired_text: str
    raw_output: str
    parse_success: bool
    fallback_used: bool
    error_type: str | None = None
    accepted_output_summary: str | None = None
    parsed: Any = None

    def __str__(self) -> str:
        """Remain friendly to legacy callers that printed the returned text."""

        return self.repaired_text


def _candidate_json_texts(text: str) -> Iterable[str]:
    yield text

    extracted: list[str] = []
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        extracted.append(fence_match.group(1).strip())

    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            extracted.append(text[start : end + 1])

    for candidate in extracted:
        yield candidate

    for candidate in [text, *extracted]:
        normalized = re.sub(r",\s*([}\]])", r"\1", candidate)
        if normalized != candidate:
            yield normalized

        single_quote_normalized = re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", r'"\1"', candidate)
        if single_quote_normalized != candidate:
            yield re.sub(r",\s*([}\]])", r"\1", single_quote_normalized)


def repair_json_output(
    raw_output: str,
    *,
    round_id: str | None = None,
    step_type: str = "json_repair",
    template_id: str | None = "json_repair",
    input_refs: list[str] | None = None,
) -> LLMRepairResult:
    """Repair JSON-like LLM text and return a structured result.

    The function first tries the raw output, then conservative fallbacks such as
    fenced-code extraction, JSON substring extraction, trailing-comma removal, and
    simple single-quote normalization.  Every call emits an ``LLMStepRecord``.
    """

    input_refs = input_refs or []
    last_error: Exception | None = None
    for index, candidate in enumerate(_candidate_json_texts(raw_output)):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

        result = LLMRepairResult(
            repaired_text=json.dumps(parsed, ensure_ascii=False, sort_keys=True),
            raw_output=raw_output,
            parse_success=True,
            fallback_used=index > 0,
            accepted_output_summary=type(parsed).__name__,
            parsed=parsed,
        )
        record_llm_step(
            LLMStepRecord(
                round_id=round_id,
                step_type=step_type,
                template_id=template_id,
                prompt_hash=prompt_hash(raw_output),
                input_refs=input_refs,
                raw_output=raw_output,
                parse_success=True,
                fallback_used=result.fallback_used,
                accepted_output_summary=result.accepted_output_summary,
            )
        )
        return result

    error_type = type(last_error).__name__ if last_error is not None else "JSONDecodeError"
    result = LLMRepairResult(
        repaired_text=raw_output,
        raw_output=raw_output,
        parse_success=False,
        fallback_used=True,
        error_type=error_type,
    )
    record_llm_step(
        LLMStepRecord(
            round_id=round_id,
            step_type=step_type,
            template_id=template_id,
            prompt_hash=prompt_hash(raw_output),
            input_refs=input_refs,
            raw_output=raw_output,
            parse_success=False,
            fallback_used=True,
            error_type=error_type,
        )
    )
    return result


# Backwards-compatible aliases for likely call sites.
def repair_json(raw_output: str, **kwargs: Any) -> LLMRepairResult:
    return repair_json_output(raw_output, **kwargs)


def repair_llm_json(raw_output: str, **kwargs: Any) -> LLMRepairResult:
    return repair_json_output(raw_output, **kwargs)
