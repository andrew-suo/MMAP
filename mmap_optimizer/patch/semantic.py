"""Semantic patch operations with LLM audit records."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from mmap_optimizer.analysis.llm_repair import repair_json_output
from mmap_optimizer.orchestration.llm_records import LLMStepRecord, prompt_hash, record_llm_step

LLMCallable = Callable[[str], str]


def _patch_id(patch: Any, index: int) -> str:
    if isinstance(patch, Mapping):
        return str(patch.get("id") or patch.get("patch_id") or f"patch_{index}")
    return str(getattr(patch, "id", getattr(patch, "patch_id", f"patch_{index}")))


def _patch_text(patch: Any) -> str:
    if isinstance(patch, Mapping):
        return str(patch.get("text") or patch.get("content") or patch)
    return str(getattr(patch, "text", getattr(patch, "content", patch)))


def semantic_merge(
    patches: Sequence[Any],
    *,
    llm: LLMCallable | None = None,
    round_id: str | None = None,
    template_id: str = "semantic_merge",
) -> dict[str, Any]:
    """Merge patches semantically and record the LLM/fallback state."""

    input_refs = [_patch_id(patch, index) for index, patch in enumerate(patches)]
    prompt = "\n".join(f"[{ref}] {_patch_text(patch)}" for ref, patch in zip(input_refs, patches))
    raw_output = llm(prompt) if llm is not None else "\n".join(_patch_text(patch) for patch in patches)

    parsed = repair_json_output(
        raw_output,
        round_id=round_id,
        step_type="semantic_merge_parse",
        template_id=template_id,
        input_refs=input_refs,
    )
    fallback_used = not parsed.parse_success
    merged_patch = parsed.parsed if parsed.parse_success else {"merged_text": raw_output}
    summary = "json" if parsed.parse_success else "raw_text_fallback"

    record_llm_step(
        LLMStepRecord(
            round_id=round_id,
            step_type="semantic_merge",
            template_id=template_id,
            prompt_hash=prompt_hash(prompt),
            input_refs=input_refs,
            raw_output=raw_output,
            parse_success=parsed.parse_success,
            fallback_used=fallback_used,
            error_type=parsed.error_type,
            accepted_output_summary=summary,
        )
    )
    return {
        "input_patch_ids": input_refs,
        "raw_output": raw_output,
        "parse_success": parsed.parse_success,
        "fallback_used": fallback_used,
        "merged_patch": merged_patch,
    }


def root_audit(
    patches: Sequence[Any],
    *,
    llm: LLMCallable | None = None,
    round_id: str | None = None,
    template_id: str = "root_audit",
) -> dict[str, Any]:
    """Audit root patches and record the LLM/fallback state."""

    input_refs = [_patch_id(patch, index) for index, patch in enumerate(patches)]
    prompt = "\n".join(f"audit:{ref}:{_patch_text(patch)}" for ref, patch in zip(input_refs, patches))
    raw_output = llm(prompt) if llm is not None else '{"accepted": true, "reason": "no llm configured"}'
    parsed = repair_json_output(
        raw_output,
        round_id=round_id,
        step_type="root_audit_parse",
        template_id=template_id,
        input_refs=input_refs,
    )
    audit = parsed.parsed if parsed.parse_success else {"accepted": False, "reason": "fallback"}

    record_llm_step(
        LLMStepRecord(
            round_id=round_id,
            step_type="root_audit",
            template_id=template_id,
            prompt_hash=prompt_hash(prompt),
            input_refs=input_refs,
            raw_output=raw_output,
            parse_success=parsed.parse_success,
            fallback_used=not parsed.parse_success,
            error_type=parsed.error_type,
            accepted_output_summary=str(audit.get("reason", "audit")) if isinstance(audit, dict) else "audit",
        )
    )
    return {
        "input_patch_ids": input_refs,
        "raw_output": raw_output,
        "parse_success": parsed.parse_success,
        "fallback_used": not parsed.parse_success,
        "audit": audit,
    }
