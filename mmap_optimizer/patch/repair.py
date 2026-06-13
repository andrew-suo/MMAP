from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.alignment import (
    PatchAlignmentEngine,
    match_verbatim_span,
    resolve_section_reference,
)
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.ir import PromptIR
from mmap_optimizer.templates import build_default_template_registry

FUZZY_MATCH_MIN_RATIO = 0.70


@dataclass
class PatchRepairResult:
    """Backward-compatible dict-based repair result.

    Used by :meth:`PatchRepairEngine.repair_locator` which predates the
    :class:`Patch` dataclass schema.  New callers should prefer
    :class:`RepairResult` and :meth:`PatchRepairEngine.repair_patch`.
    """

    repaired_patch: dict[str, Any]
    repaired: bool
    unresolved_fields: list[str]
    raw_output: str | None = None
    failure_reason: str | None = None


@dataclass
class RepairResult:
    """Structured result of a Patch-native repair attempt.

    ``repaired=True`` means the engine produced a new :class:`Patch` with
    corrected locators.  The original patch is never mutated; callers must
    explicitly re-validate the repaired patch using :class:`PatchValidator`
    before applying it with :class:`PatchApplier`.
    """

    repaired: bool
    original_patch: Patch
    repaired_patch: Patch | None = None
    reason: str | None = None
    strategy: str | None = None
    candidate_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the repair result for audit/artifact logging."""
        return {
            "repaired": self.repaired,
            "original_patch_id": self.original_patch.id,
            "repaired_patch_id": self.repaired_patch.id if self.repaired_patch else None,
            "reason": self.reason,
            "strategy": self.strategy,
            "candidate_count": self.candidate_count,
            "metadata": copy.deepcopy(self.metadata),
        }


class PatchRepairEngine:
    """Repair failed patch applications without silently overriding strict apply semantics.

    The engine offers two entry points:

    * :meth:`repair_locator` — dict-based, kept for backward compatibility with
      pre-:class:`Patch` callers.  Runs an optional LLM-assisted rewrite followed
      by fuzzy text/section alignment.
    * :meth:`repair_patch` — Patch-native.  Deterministic, LLM-free fuzzy repair
      using :mod:`mmap_optimizer.patch.alignment` helpers.  Produces a new
      :class:`Patch` object with corrected locators, plus a :class:`RepairResult`
      describing the decision.  The original patch is never mutated.

    Both entry points refuse to repair patches targeting frozen sections and
    refuse to silently pick one of several ambiguous locator matches.  A repair
    ``reason`` of ``"TARGET_SECTION_FROZEN"`` / ``"AMBIGUOUS_LOCATOR"`` /
    ``"INVALID_TARGET_SECTION"`` signals a hard refusal.
    """

    def __init__(self, model_client: ModelClient | None = None, model_config: dict[str, Any] | None = None):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.registry = build_default_template_registry()

    # ------------------------------------------------------------------
    # Dict-based (backward-compatible)
    # ------------------------------------------------------------------
    def repair_locator(self, *, patch: dict[str, Any], prompt_ir: PromptIR, failure_info: str) -> PatchRepairResult:
        candidate = dict(patch)
        raw_output: str | None = None
        if self.model_client is not None:
            template = self.registry.get("patch_translation_retry")
            response = self.model_client.complete(
                [
                    {"role": "system", "content": template.render(failure_info=failure_info, prompt_structure=_prompt_structure(prompt_ir), current_prompt=_prompt_text(prompt_ir), patch_json=json.dumps(patch, ensure_ascii=False))},
                    {"role": "user", "content": {"failure_info": failure_info, "patch": patch}},
                ],
                model_config=self.model_config,
                response_format=template.output_contract,
            )
            raw_output = response.raw_output
            try:
                parsed = json.loads(response.raw_output)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    candidate = parsed[0]
            except json.JSONDecodeError:
                pass
        alignment = PatchAlignmentEngine().align_patch_location(candidate, prompt_ir)
        return PatchRepairResult(
            repaired_patch=alignment.aligned_patch,
            repaired=alignment.changed and not alignment.unresolved,
            unresolved_fields=alignment.unresolved_fields,
            raw_output=raw_output,
            failure_reason=None if not alignment.unresolved else "UNRESOLVED_LOCATOR",
        )

    # ------------------------------------------------------------------
    # Patch-native (PR #40 integration)
    # ------------------------------------------------------------------
    def repair_patch(
        self,
        patch: Patch,
        prompt_ir: PromptIR,
        *,
        failure_info: str | None = None,
    ) -> RepairResult:
        """Attempt to repair a patch whose locator could not be applied exactly.

        Returns a :class:`RepairResult` describing what (if anything) was
        changed.  The original ``patch`` is never mutated: on a successful
        repair, ``result.repaired_patch`` is a new :class:`Patch` instance.

        Repair strategy (first applicable wins):

        1. **Frozen section** → refuse (``TARGET_SECTION_FROZEN``).
        2. **Missing section_id** → try :func:`resolve_section_reference` on
           ``patch.target_section`` (set by the dict layer) or ``patch.extra``
           hints; otherwise refuse.
        3. **Missing locator** for a text-level operation → try
           :func:`match_verbatim_span` on the section content.  If the best
           fuzzy match has a score >= ``0.85``, accept it as the corrected
           locator.  Otherwise refuse.
        4. **Ambiguous locator** (multiple exact matches) → refuse
           (``AMBIGUOUS_LOCATOR``) — silently picking one would break the
           strict application contract.
        5. **Non-text-level mode** (``append`` / ``replace_section`` / …) →
           not applicable (``NOT_APPLICABLE``).

        Callers are expected to re-validate the repaired patch through
        :class:`PatchValidator` before handing it to :class:`PatchApplier`.
        """

        original = patch
        metadata: dict[str, Any] = {"failure_info": failure_info} if failure_info else {}

        # (5) Non-text-level modes: nothing to repair at locator level.
        if not patch.is_text_level():
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="NOT_APPLICABLE",
                strategy="none",
                metadata={"operation_mode": patch.operation_mode},
            )

        # (1) Frozen section: refuse outright.
        section = prompt_ir.section_by_id(patch.section_id)
        if section is None:
            # (2) Try section reference resolution from hints.
            resolved_section = self._try_resolve_section(patch, prompt_ir)
            if resolved_section is None:
                metadata["section_id"] = patch.section_id
                return RepairResult(
                    repaired=False,
                    original_patch=original,
                    reason="INVALID_TARGET_SECTION",
                    strategy="section_reference_resolution",
                    candidate_count=0,
                    metadata=metadata,
                )
            if resolved_section.mutability == "frozen":
                return RepairResult(
                    repaired=False,
                    original_patch=original,
                    reason="TARGET_SECTION_FROZEN",
                    strategy="none",
                    metadata={"section_id": resolved_section.id},
                )
            section = resolved_section
            # Build a new Patch with the resolved section_id before attempting
            # locator repair.  We'll keep accumulating corrections into this
            # object via fresh copies below.
            patch = _patch_with(patch, section_id=section.id)
            metadata["resolved_section_id"] = section.id
        elif section.mutability == "frozen":
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="TARGET_SECTION_FROZEN",
                strategy="none",
                metadata={"section_id": section.id},
            )

        mode = patch.effective_operation_mode
        field_to_repair = _locator_field_for_mode(mode)
        if field_to_repair is None:
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="NOT_APPLICABLE",
                strategy="none",
                metadata={"operation_mode": mode},
            )

        original_locator_value = patch.locator_value(field_to_repair)
        if not original_locator_value or not isinstance(original_locator_value, str):
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="PATCH_LOCATOR_NOT_FOUND",
                strategy="none",
                metadata={"field": field_to_repair, "detail": "locator not present or not a string"},
            )

        # Exact match: already present in section → no repair needed.
        if original_locator_value in section.content:
            occurrences = section.content.count(original_locator_value)
            if occurrences == 1:
                return RepairResult(
                    repaired=False,
                    original_patch=original,
                    reason="NO_REPAIR_NEEDED",
                    strategy="none",
                    metadata={"detail": "locator already present exactly once"},
                )
            # (4) Ambiguous: refuse.
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="AMBIGUOUS_LOCATOR",
                strategy="none",
                candidate_count=occurrences,
                metadata={"field": field_to_repair, "occurrences": occurrences},
            )

        # (3) Missing: try section-content level first, then fall back to a
        # more flexible substring-level fuzzy match for text-level patching.
        # The alignment engine's ``match_verbatim_span`` only scans
        # paragraph/line-level spans, which works well for section-id
        # alignment but misses sub-line locators. We complement with a
        # sliding-window scan restricted to spans of similar length to the
        # original locator text.
        paragraph_match = match_verbatim_span(
            section.content, original_locator_value, min_ratio=FUZZY_MATCH_MIN_RATIO
        )
        substring_match = _match_verbatim_substring(
            section.content, original_locator_value, min_ratio=FUZZY_MATCH_MIN_RATIO
        )
        # Prefer whichever has higher score; tie-break to substring_match
        # which typically has a more specific span.
        candidates = [m for m in (paragraph_match, substring_match) if m is not None]
        if not candidates:
            metadata["fuzzy_match"] = {
                "score": 0.0,
                "field": field_to_repair,
                "method": "none",
            }
            return RepairResult(
                repaired=False,
                original_patch=original,
                reason="PATCH_LOCATOR_NOT_FOUND",
                strategy="fuzzy_match",
                candidate_count=0,
                metadata=metadata,
            )
        best = max(candidates, key=lambda m: m.score)

        # Repair succeeded: build a new Patch with the corrected locator.
        metadata["fuzzy_match"] = {
            "score": best.score,
            "method": best.method,
            "field": field_to_repair,
            "original_length": len(original_locator_value),
            "repaired_length": len(best.text),
        }

        nested_locator = dict(patch.locator or {})
        nested_locator[field_to_repair] = best.text

        field_updates = {
            field_to_repair: best.text,
            "locator": nested_locator,
            "extra": dict(patch.extra or {}),
        }
        existing_repair = list(field_updates["extra"].get("repair_history") or [])
        existing_repair.append(
            {
                "field": field_to_repair,
                "original": original_locator_value,
                "repaired": best.text,
                "strategy": "fuzzy_match",
                "score": best.score,
            }
        )
        field_updates["extra"]["repair_history"] = existing_repair

        repaired_patch = _patch_with(patch, **field_updates)
        return RepairResult(
            repaired=True,
            original_patch=original,
            repaired_patch=repaired_patch,
            reason=None,
            strategy="fuzzy_match",
            candidate_count=1,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _try_resolve_section(self, patch: Patch, prompt_ir: PromptIR) -> Any:
        # Prefer explicit hints in ``extra`` under keys like ``target_section``,
        # falling back to the patch's own fields if they happen to be plain
        # strings that describe a section label.
        reference = None
        extra = patch.extra or {}
        if isinstance(extra.get("target_section"), str):
            reference = extra["target_section"]
        elif isinstance(extra.get("section_label"), str):
            reference = extra["section_label"]
        elif isinstance(patch.operation_type, str) and " " not in patch.operation_type:
            reference = None  # operation_type is not a section reference

        # Look at the old_text/target_text themselves: they may contain the
        # section label (e.g. "## Rules: some text").  Only try if nothing
        # better was found.
        if reference is None:
            for field_name in ("old_text", "target_text"):
                value = patch.locator_value(field_name)
                if isinstance(value, str) and "\n" not in value and value.strip():
                    # Try to resolve this text as a section label (rare case,
                    # e.g. when a patch description accidentally mentions the
                    # section header).
                    candidate = resolve_section_reference(prompt_ir, value)
                    if candidate is not None:
                        return candidate
            return None

        return resolve_section_reference(prompt_ir, reference)


def _locator_field_for_mode(mode: str) -> str | None:
    if mode == "replace_in_section":
        return "old_text"
    if mode in ("insert_after", "insert_before"):
        return "target_text"
    if mode == "delete":
        return "old_text"
    return None


def _patch_with(patch: Patch, **overrides: Any) -> Patch:
    """Build a new Patch copying ``patch`` then applying ``overrides``.

    Preserves the original object intact and ensures every mutable container
    field (``source_sample_ids``, ``extra``, ``locator``, ``payload``, …)
    is deep-copied so the new patch cannot mutate the original's internals.
    """

    # Start from a shallow copy so all scalar fields are preserved.
    base = copy.copy(patch)

    # Deep-copy mutable container fields explicitly.
    for field_name in (
        "source_sample_ids",
        "source_analysis_ids",
        "possible_side_effects",
        "fixed_sample_ids",
        "broken_sample_ids",
        "extra",
        "locator",
        "payload",
    ):
        value = getattr(patch, field_name, None)
        if value is not None:
            setattr(base, field_name, copy.deepcopy(value))

    for key, value in overrides.items():
        setattr(base, key, value)

    return base


@dataclass(frozen=True)
class _TextMatch:
    text: str
    start: int
    end: int
    score: float
    method: str


def _normalize_text(value: str) -> str:
    """Normalize text for fuzzy comparison (strip whitespace/case differences)."""
    return "".join(ch for ch in value.lower() if not ch.isspace())


def _match_verbatim_substring(
    content: str,
    intent: str,
    *,
    min_ratio: float = 0.70,
) -> _TextMatch | None:
    """Find a substring of ``content`` that is similar to ``intent``.

    Scans every contiguous substring of ``content`` whose length is within
    +/- 30% of ``intent``'s length. Returns the best scoring match that
    meets ``min_ratio``, or ``None`` if nothing qualifies. This is used
    specifically for text-level patch locator repair where the target
    string is known to be embedded somewhere within a section's content.
    """

    if not content or not intent or not intent.strip():
        return None

    # Exact shortcut: if it's present verbatim, no repair is needed.
    if intent in content:
        start = content.index(intent)
        return _TextMatch(intent, start, start + len(intent), 1.0, "exact")

    normalized_intent = _normalize_text(intent)
    intent_len = len(normalized_intent)
    if intent_len == 0:
        return None

    # Window size: +/- 30% but at least 1.
    min_len = max(1, int(intent_len * 0.7))
    max_len = max(min_len, int(intent_len * 1.3))

    content_chars = list(content)
    n = len(content_chars)
    best: tuple[float, int, int, str] | None = None

    # Step by 1 for short content; for longer content, step can be slightly
    # larger. We keep step=1 for correctness on short prompt sections.
    step = 1 if n <= 200 else 2

    for start in range(0, n, step):
        for span_len in range(min_len, min(max_len + 1, n - start + 1)):
            if start + span_len > n:
                continue
            candidate_slice = "".join(content_chars[start : start + span_len])
            normalized_candidate = _normalize_text(candidate_slice)
            if not normalized_candidate:
                continue
            score = SequenceMatcher(
                None, normalized_intent, normalized_candidate
            ).ratio()
            if best is None or score > best[0]:
                best = (score, start, start + span_len, candidate_slice)

    if best is not None and best[0] >= min_ratio:
        # Re-search at the fine-grained level around the best window for
        # higher precision (in case we used step > 1).
        _, s, e, _text = best
        # widen a bit and scan every offset/span around the match.
        s_lo = max(0, s - 3)
        s_hi = min(n, s + 3)
        e_lo = max(1, e - 3)
        e_hi = min(n, e + 3)
        refined: tuple[float, int, int, str] | None = None
        for start in range(s_lo, s_hi + 1):
            for end in range(e_lo, e_hi + 1):
                if end <= start:
                    continue
                candidate_slice = "".join(content_chars[start:end])
                normalized_candidate = _normalize_text(candidate_slice)
                if not normalized_candidate:
                    continue
                score = SequenceMatcher(None, normalized_intent, normalized_candidate).ratio()
                if refined is None or score > refined[0]:
                    refined = (score, start, end, candidate_slice)
        chosen = refined if refined is not None else best
        return _TextMatch(
            text=chosen[3],
            start=chosen[1],
            end=chosen[2],
            score=chosen[0],
            method="fuzzy_substring",
        )
    return None


def _prompt_structure(prompt_ir: PromptIR) -> str:
    return "\n".join(f"- {section.id}: {section.name or section.type}" for section in prompt_ir.sections)


def _prompt_text(prompt_ir: PromptIR) -> str:
    return "\n\n".join(section.content for section in prompt_ir.sections if section.rendering_enabled)
