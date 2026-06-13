"""Semantic patch merge and root-audit helpers with LLM artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecord, coerce_input_refs, hash_prompt
from mmap_optimizer.orchestration.round_runner import write_llm_step

ModelCallable = Callable[[str], str]


def _patch_id(patch: Any) -> str:
    if isinstance(patch, Mapping):
        return str(patch.get("id") or patch.get("patch_id") or patch.get("name") or hash(json.dumps(patch, sort_keys=True)))
    return str(getattr(patch, "id", getattr(patch, "patch_id", patch)))


def _call_model(model: ModelCallable | None, prompt: str) -> tuple[str, str | None]:
    if model is None:
        return "", "MissingModel"
    try:
        return model(prompt), None
    except Exception as exc:  # noqa: BLE001 - artifact should include provider failure class.
        return "", type(exc).__name__


def _parse_json_output(raw_output: str) -> tuple[bool, Any | None, str | None]:
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


def semantic_merge(
    patches: list[Any],
    model: ModelCallable | None = None,
    *,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    template_id: str = "semantic_merge",
    fallback: Any | None = None,
) -> dict[str, Any]:
    """Merge patches semantically and record patch ids plus model parse state."""

    patch_ids = [_patch_id(patch) for patch in patches]
    prompt = json.dumps({"task": "semantic_merge", "patches": patches}, ensure_ascii=False, default=str)
    raw_output, call_error = _call_model(model, prompt)
    parse_success, parsed, parse_error = _parse_json_output(raw_output) if raw_output else (False, None, call_error)
    fallback_used = not parse_success
    accepted = parsed if parse_success else (fallback if fallback is not None else {"patches": patches})
    summary = f"merged input patch ids: {', '.join(patch_ids)}"
    record = _record(
        step_type="semantic_merge",
        round_id=round_id,
        template_id=template_id,
        prompt=prompt,
        input_refs=coerce_input_refs(patch_ids),
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=None if parse_success else (call_error or parse_error),
        accepted_output_summary=summary,
        artifact_root=artifact_root,
    )
    return {"output": accepted, "record": record, "input_patch_ids": patch_ids}


def root_audit(
    patches: list[Any],
    model: ModelCallable | None = None,
    *,
    round_id: int | str = 0,
    artifact_root: str | Path | None = None,
    template_id: str = "root_audit",
    fallback: Any | None = None,
) -> dict[str, Any]:
    """Audit root-level patch consistency and record raw/parse/fallback state."""

    patch_ids = [_patch_id(patch) for patch in patches]
    prompt = json.dumps({"task": "root_audit", "patches": patches}, ensure_ascii=False, default=str)
    raw_output, call_error = _call_model(model, prompt)
    parse_success, parsed, parse_error = _parse_json_output(raw_output) if raw_output else (False, None, call_error)
    fallback_used = not parse_success
    accepted = parsed if parse_success else (fallback if fallback is not None else {"ok": True, "patch_ids": patch_ids})
    summary = f"root audit input patch ids: {', '.join(patch_ids)}"
    record = _record(
        step_type="root_audit",
        round_id=round_id,
        template_id=template_id,
        prompt=prompt,
        input_refs=coerce_input_refs(patch_ids),
        raw_output=raw_output,
        parse_success=parse_success,
        fallback_used=fallback_used,
        error_type=None if parse_success else (call_error or parse_error),
        accepted_output_summary=summary,
        artifact_root=artifact_root,
    )
    return {"output": accepted, "record": record, "input_patch_ids": patch_ids}
