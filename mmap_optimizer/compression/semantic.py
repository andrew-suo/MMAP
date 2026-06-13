"""Semantic compression helpers with auditable LLM records."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecord, coerce_input_refs, hash_prompt
from mmap_optimizer.orchestration.round_runner import write_llm_step

ModelCallable = Callable[[str], str]


def _call_model(model: ModelCallable | None, prompt: str) -> tuple[str, str | None]:
    if model is None:
        return "", "MissingModel"
    try:
        return model(prompt), None
    except Exception as exc:  # noqa: BLE001 - artifacts should retain failure class.
        return "", type(exc).__name__


def _parse_json(raw_output: str) -> tuple[bool, Any | None, str | None]:
    try:
        return True, json.loads(raw_output), None
    except json.JSONDecodeError as exc:
        return False, None, type(exc).__name__


def _record(
    *,
    step_type: str,
    round_id: int | str,
    template_id: str,
    prompt: str,
    input_refs: list[str],
    raw_output: str,
    parse_success: bool,
    fallback_used: bool,
    error_type: str | None,
    accepted_output_summary: str,
    artifact_root: str | Path | None,
) -> LLMStepRecord:
    record = LLMStepRecord(
        round_id=round_id,
        step_type=step_type,
        template_id=template_id,
        prompt_hash=hash_prompt(prompt),
        input_refs=input_refs,
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=error_type,
        accepted_output_summary=accepted_output_summary,
    )
    if artifact_root is not None:
        write_llm_step(artifact_root, round_id, record)
    return record


def semantic_prune(
    items: list[Any],
    model: ModelCallable | None = None,
    *,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    template_id: str = "semantic_prune",
    input_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Prune items with an LLM and record the prune output."""

    prompt = json.dumps({"task": "semantic_prune", "items": items}, ensure_ascii=False, default=str)
    raw_output, call_error = _call_model(model, prompt)
    parse_success, parsed, parse_error = _parse_json(raw_output) if raw_output else (False, None, call_error)
    fallback_used = not parse_success
    pruned = parsed if parse_success else items
    summary = f"prune output: {str(pruned)[:200]}"
    record = _record(
        step_type="semantic_prune",
        round_id=round_id,
        template_id=template_id,
        prompt=prompt,
        input_refs=coerce_input_refs(input_refs or range(len(items))),
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=None if parse_success else (call_error or parse_error),
        accepted_output_summary=summary,
        artifact_root=artifact_root,
    )
    return {"output": pruned, "prune_output": raw_output, "record": record}


def validate_semantic_compression(
    original: list[Any],
    compressed: Any,
    model: ModelCallable | None = None,
    *,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    template_id: str = "semantic_validation",
    input_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Validate semantic compression and record output plus reason."""

    prompt = json.dumps(
        {"task": "semantic_validation", "original": original, "compressed": compressed},
        ensure_ascii=False,
        default=str,
    )
    raw_output, call_error = _call_model(model, prompt)
    parse_success, parsed, parse_error = _parse_json(raw_output) if raw_output else (False, None, call_error)
    fallback_used = not parse_success
    if isinstance(parsed, dict):
        valid = bool(parsed.get("valid", parsed.get("ok", False)))
        reason = str(parsed.get("reason", "validation accepted"))
    else:
        valid = fallback_used
        reason = call_error or parse_error or "fallback validation accepted"
    summary = f"validation output: {raw_output[:120]}; validation reason: {reason}"
    record = _record(
        step_type="semantic_validation",
        round_id=round_id,
        template_id=template_id,
        prompt=prompt,
        input_refs=coerce_input_refs(input_refs or range(len(original))),
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=None if parse_success else (call_error or parse_error),
        accepted_output_summary=summary,
        artifact_root=artifact_root,
    )
    return {"valid": valid, "validation_output": raw_output, "validation_reason": reason, "record": record}


def semantic_compress(
    items: list[Any],
    prune_model: ModelCallable | None = None,
    validation_model: ModelCallable | None = None,
    *,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    input_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Run prune + validation and persist both LLM artifacts when requested."""

    prune = semantic_prune(
        items,
        prune_model,
        round_id=round_id,
        artifact_root=artifact_root,
        input_refs=input_refs,
    )
    validation = validate_semantic_compression(
        items,
        prune["output"],
        validation_model,
        round_id=round_id,
        artifact_root=artifact_root,
        input_refs=input_refs,
    )
    return {
        "output": prune["output"] if validation["valid"] else items,
        "prune_output": prune["prune_output"],
        "validation_output": validation["validation_output"],
        "validation_reason": validation["validation_reason"],
        "records": [prune["record"], validation["record"]],
    }
