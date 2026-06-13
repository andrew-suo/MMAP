"""Semantic compression helpers.

The semantic compressor asks an LLM to prune a section, then validates the
candidate against the *original* section.  Validation is deliberately strict:
invalid or non-JSON validator output is surfaced as an explicit parse error.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


@dataclass(slots=True)
class SemanticCompressionCandidate:
    """Result of an attempted semantic compression."""

    content: str
    reason: str
    accepted: bool
    attempt_count: int
    validation_reason: str | None = None
    validation_raw_output: str | None = None
    candidate_line_count: int = 0
    rejected_reason: str | None = None


def semantic_compress_section(
    section_content: str,
    llm: Any,
    *,
    max_attempts: int = 1,
    behavior_gate: Callable[[str, str], bool | tuple[bool, str]] | None = None,
) -> SemanticCompressionCandidate:
    """Try to semantically compress ``section_content`` with up to N attempts.

    Each attempt starts from the original, unmodified section for both prune and
    validation prompts.  Validation parse errors are returned immediately with a
    ``validation_parse_error`` rejected reason so callers can report the raw LLM
    output.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    last_result: SemanticCompressionCandidate | None = None
    for attempt in range(1, max_attempts + 1):
        prune_raw = _call_llm(llm, _prune_prompt(section_content, attempt, max_attempts))
        candidate_content, prune_reason = _parse_prune_output(prune_raw)
        candidate_line_count = _line_count(candidate_content)

        validation_raw = _call_llm(
            llm,
            _validation_prompt(
                original_section=section_content,
                candidate_section=candidate_content,
                attempt=attempt,
                max_attempts=max_attempts,
            ),
        )
        validation = _parse_validation_output(validation_raw)
        if validation["parse_error"]:
            return SemanticCompressionCandidate(
                content=candidate_content,
                reason=prune_reason,
                accepted=False,
                attempt_count=attempt,
                validation_reason=validation["reason"],
                validation_raw_output=validation_raw,
                candidate_line_count=candidate_line_count,
                rejected_reason=f"validation_parse_error: {validation['reason']}",
            )

        validation_reason = validation["reason"]
        if validation["valid"]:
            gate_passed, gate_reason = _run_behavior_gate(
                behavior_gate, candidate_content, section_content
            )
            if gate_passed:
                return SemanticCompressionCandidate(
                    content=candidate_content,
                    reason=prune_reason,
                    accepted=True,
                    attempt_count=attempt,
                    validation_reason=validation_reason,
                    validation_raw_output=validation_raw,
                    candidate_line_count=candidate_line_count,
                )

            return SemanticCompressionCandidate(
                content=candidate_content,
                reason=prune_reason,
                accepted=False,
                attempt_count=attempt,
                validation_reason=validation_reason,
                validation_raw_output=validation_raw,
                candidate_line_count=candidate_line_count,
                rejected_reason=f"behavior_gate_failed: {gate_reason}",
            )

        last_result = SemanticCompressionCandidate(
            content=candidate_content,
            reason=prune_reason,
            accepted=False,
            attempt_count=attempt,
            validation_reason=validation_reason,
            validation_raw_output=validation_raw,
            candidate_line_count=candidate_line_count,
            rejected_reason=f"semantic_validation_failed: {validation_reason}",
        )

    assert last_result is not None
    return last_result


def _call_llm(llm: Any, prompt: str) -> str:
    """Call a broad range of simple LLM test doubles and client wrappers."""

    if callable(llm):
        result = llm(prompt)
    elif hasattr(llm, "complete"):
        result = llm.complete(prompt)
    elif hasattr(llm, "generate"):
        result = llm.generate(prompt)
    elif hasattr(llm, "invoke"):
        result = llm.invoke(prompt)
    else:
        raise TypeError("llm must be callable or expose complete/generate/invoke")

    if hasattr(result, "content"):
        result = result.content
    return str(result)


def _prune_prompt(section_content: str, attempt: int, max_attempts: int) -> str:
    return (
        "Prune the following section while preserving all semantics.\n"
        f"Attempt: {attempt}/{max_attempts}\n"
        "Return JSON with keys 'content' and 'reason'.\n"
        "ORIGINAL_SECTION:\n"
        f"{section_content}"
    )


def _validation_prompt(
    *, original_section: str, candidate_section: str, attempt: int, max_attempts: int
) -> str:
    return (
        "Validate whether CANDIDATE_SECTION preserves ORIGINAL_SECTION semantics.\n"
        f"Attempt: {attempt}/{max_attempts}\n"
        "Return JSON with boolean key 'valid' and string key 'reason'.\n"
        "ORIGINAL_SECTION:\n"
        f"{original_section}\n"
        "CANDIDATE_SECTION:\n"
        f"{candidate_section}"
    )


def _parse_prune_output(raw_output: str) -> tuple[str, str]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return raw_output, "semantic_prune_raw_text"

    if not isinstance(parsed, dict):
        return raw_output, "semantic_prune_non_object_json"

    content = parsed.get("content", parsed.get("candidate", parsed.get("compressed", "")))
    reason = parsed.get("reason", "semantic_prune")
    return str(content), str(reason)


def _parse_validation_output(raw_output: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "reason": f"validator returned non-JSON output: {exc.msg}",
            "parse_error": True,
        }

    if not isinstance(parsed, dict):
        return {
            "valid": False,
            "reason": "validator JSON output must be an object",
            "parse_error": True,
        }

    valid = parsed.get("valid", parsed.get("ok", parsed.get("semantic_equivalent")))
    if not isinstance(valid, bool):
        return {
            "valid": False,
            "reason": "validator JSON output must include boolean 'valid'",
            "parse_error": True,
        }

    return {
        "valid": valid,
        "reason": str(parsed.get("reason", "")),
        "parse_error": False,
    }


def _run_behavior_gate(
    behavior_gate: Callable[[str, str], bool | tuple[bool, str]] | None,
    candidate_content: str,
    original_content: str,
) -> tuple[bool, str]:
    if behavior_gate is None:
        return True, "behavior gate not configured"

    result = behavior_gate(candidate_content, original_content)
    if isinstance(result, tuple):
        passed, reason = result
        return bool(passed), str(reason)
    return bool(result), "behavior gate returned false"


def _line_count(content: str) -> int:
    if not content:
        return 0
    return len(content.splitlines())
