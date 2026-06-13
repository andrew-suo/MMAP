"""Semantic compression helpers with LLM audit records."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from mmap_optimizer.analysis.llm_repair import repair_json_output
from mmap_optimizer.orchestration.llm_records import LLMStepRecord, prompt_hash, record_llm_step

LLMCallable = Callable[[str], str]


def semantic_compress(
    items: Sequence[str],
    *,
    llm: LLMCallable | None = None,
    validator: LLMCallable | None = None,
    round_id: str | None = None,
    template_id: str = "semantic_compression",
) -> dict[str, Any]:
    """Prune and validate semantically compressed text."""

    prompt = "\n".join(str(item) for item in items)
    prune_output = llm(prompt) if llm is not None else "\n".join(str(item) for item in items)
    validation_prompt = f"Validate semantic compression:\n{prune_output}"
    validation_output = (
        validator(validation_prompt)
        if validator is not None
        else '{"valid": true, "reason": "no validator configured"}'
    )
    validation = repair_json_output(
        validation_output,
        round_id=round_id,
        step_type="semantic_compression_validation_parse",
        template_id=template_id,
        input_refs=[f"item_{index}" for index, _ in enumerate(items)],
    )
    validation_reason = None
    if isinstance(validation.parsed, dict):
        validation_reason = validation.parsed.get("reason")
    if validation_reason is None:
        validation_reason = validation.error_type or "validation_unavailable"

    record_llm_step(
        LLMStepRecord(
            round_id=round_id,
            step_type="semantic_compression",
            template_id=template_id,
            prompt_hash=prompt_hash(prompt),
            input_refs=[f"item_{index}" for index, _ in enumerate(items)],
            raw_output=prune_output,
            parse_success=validation.parse_success,
            fallback_used=not validation.parse_success,
            error_type=validation.error_type,
            accepted_output_summary=str(validation_reason),
        )
    )
    return {
        "prune_output": prune_output,
        "validation_output": validation_output,
        "validation_reason": validation_reason,
        "parse_success": validation.parse_success,
        "fallback_used": not validation.parse_success,
    }
