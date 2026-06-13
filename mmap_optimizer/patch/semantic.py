"""Semantic patch merge and root audit helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence
import json

from mmap_optimizer.orchestration.llm_records import LLMStepRecorder, get_current_recorder, hash_prompt

MERGE_TEMPLATE_ID = "patch.semantic_merge.v1"
ROOT_AUDIT_TEMPLATE_ID = "patch.root_audit.v1"


@dataclass(slots=True)
class SemanticMergeResult:
    patches: list[Mapping[str, Any]]
    raw_output: str
    parse_success: bool
    fallback_used: bool
    error_type: str | None = None
    parsed_output: Mapping[str, Any] | None = None


def _patch_id(patch: Mapping[str, Any], index: int) -> str:
    return str(patch.get("id") or patch.get("patch_id") or f"patch_{index}")


def _parse_patches(raw_output: str) -> tuple[list[Mapping[str, Any]], Mapping[str, Any] | None]:
    parsed = json.loads(raw_output)
    if isinstance(parsed, dict):
        candidates = parsed.get("patches") or parsed.get("merged_patches")
        if isinstance(candidates, list):
            return [p for p in candidates if isinstance(p, Mapping)], parsed
    if isinstance(parsed, list):
        return [p for p in parsed if isinstance(p, Mapping)], None
    raise ValueError("semantic merge output did not contain patches")


def semantic_merge(
    patches: Sequence[Mapping[str, Any]],
    model_call: Callable[[str], str],
    *,
    template_id: str = MERGE_TEMPLATE_ID,
    prompt: str | None = None,
    recorder: LLMStepRecorder | None = None,
    step_type: str = "semantic_merge",
) -> SemanticMergeResult:
    """Merge patches semantically, falling back to original patches on invalid output."""

    input_patch_ids = [_patch_id(patch, index) for index, patch in enumerate(patches)]
    prompt = prompt or json.dumps({"patch_ids": input_patch_ids, "patches": list(patches)}, ensure_ascii=False)
    raw_output = model_call(prompt)
    parse_success = False
    fallback_used = False
    error_type: str | None = None
    parsed_output: Mapping[str, Any] | None = None

    try:
        merged_patches, parsed_output = _parse_patches(raw_output)
        if not merged_patches and patches:
            raise ValueError("semantic merge output contained no valid patch objects")
        parse_success = True
    except json.JSONDecodeError:
        merged_patches = list(patches)
        fallback_used = True
        error_type = "json_decode_error"
    except ValueError:
        merged_patches = list(patches)
        fallback_used = True
        error_type = "missing_patches"

    active_recorder = recorder or get_current_recorder()
    if active_recorder is not None:
        active_recorder.record_step(
            step_type=step_type,
            template_id=template_id,
            prompt_hash=hash_prompt(prompt),
            input_summary={"input_patch_ids": input_patch_ids, "patch_count": len(patches)},
            raw_output=raw_output,
            parse_success=parse_success,
            fallback_used=fallback_used,
            error_type=error_type,
            metadata={"output_patch_count": len(merged_patches)},
        )

    return SemanticMergeResult(merged_patches, raw_output, parse_success, fallback_used, error_type, parsed_output)


def root_audit(
    patches: Sequence[Mapping[str, Any]],
    model_call: Callable[[str], str],
    *,
    template_id: str = ROOT_AUDIT_TEMPLATE_ID,
    prompt: str | None = None,
    recorder: LLMStepRecorder | None = None,
) -> SemanticMergeResult:
    """Audit root-level semantic patch decisions with the same recording contract."""

    return semantic_merge(
        patches,
        model_call,
        template_id=template_id,
        prompt=prompt,
        recorder=recorder,
        step_type="root_audit",
    )
