from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from mmap_optimizer.prompt.ir import PromptIR, PromptSection

LOCATOR_FIELDS = {"target_section", "section_id", "old_text", "target_text"}
PAYLOAD_FIELDS = {"op", "operation_mode", "content", "patch_text", "new_text", "new_content", "rationale", "reasoning"}


@dataclass
class TextMatchResult:
    text: str
    start: int
    end: int
    score: float
    method: str


@dataclass
class PatchLocationAlignment:
    original_patch: dict[str, Any]
    aligned_patch: dict[str, Any]
    status: str
    changes: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    match_details: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def unresolved(self) -> bool:
        return bool(self.unresolved_fields)


class PatchAlignmentEngine:
    def align_patch_locations(self, patches: list[dict[str, Any]], prompt_ir: PromptIR) -> list[PatchLocationAlignment]:
        return [self.align_patch_location(patch, prompt_ir) for patch in patches]

    def align_patch_location(self, patch: dict[str, Any], prompt_ir: PromptIR) -> PatchLocationAlignment:
        original = dict(patch)
        aligned = dict(patch)
        changes: list[str] = []
        unresolved: list[str] = []
        match_details: dict[str, dict[str, Any]] = {}

        section = self._resolve_section(aligned, prompt_ir)
        if section is None:
            if "target_section" in aligned or "section_id" in aligned:
                unresolved.append("target_section")
            _mark_unresolved(aligned, unresolved)
            return PatchLocationAlignment(original, aligned, _status(changes, unresolved), changes, unresolved, match_details)

        section_label = _section_label(section)
        if aligned.get("target_section") != section_label:
            aligned["target_section"] = section_label
            changes.append("target_section")
        if aligned.get("section_id") != section.id:
            aligned["section_id"] = section.id
            changes.append("section_id")

        for field_name in ("old_text", "target_text"):
            value = aligned.get(field_name)
            if not isinstance(value, str) or not value.strip():
                continue
            result = match_verbatim_span(section.content, value)
            if result:
                match_details[field_name] = {
                    "start": result.start,
                    "end": result.end,
                    "score": result.score,
                    "method": result.method,
                }
                if value != result.text:
                    aligned[field_name] = result.text
                    changes.append(field_name)
            else:
                unresolved.append(field_name)

        if unresolved:
            _mark_unresolved(aligned, unresolved)
        _assert_payload_unchanged(original, aligned)
        return PatchLocationAlignment(original, aligned, _status(changes, unresolved), changes, unresolved, match_details)

    def _resolve_section(self, patch: dict[str, Any], prompt_ir: PromptIR) -> PromptSection | None:
        section_id = patch.get("section_id")
        if isinstance(section_id, str):
            section = prompt_ir.section_by_id(section_id)
            if section is not None:
                return section
        target = patch.get("target_section")
        if not isinstance(target, str) or not target.strip():
            return None
        return resolve_section_reference(prompt_ir, target)


def resolve_section_reference(prompt_ir: PromptIR, reference: str) -> PromptSection | None:
    normalized_reference = _normalize_reference(reference)
    best: tuple[float, PromptSection] | None = None
    for section in prompt_ir.sections:
        aliases = {section.id, section.type, _section_label(section)}
        if section.name:
            aliases.add(section.name)
        aliases.add(f'<SECTION id="{section.id}" type="{section.type}" priority="{section.priority}">')
        for alias in aliases:
            normalized_alias = _normalize_reference(alias)
            if normalized_alias == normalized_reference:
                return section
            score = SequenceMatcher(None, normalized_alias, normalized_reference).ratio()
            if best is None or score > best[0]:
                best = (score, section)
    if best is not None and best[0] >= 0.72:
        return best[1]
    return None


def match_verbatim_substring(section_content: str, intent_text: str, *, min_ratio: float = 0.58) -> str:
    result = match_verbatim_span(section_content, intent_text, min_ratio=min_ratio)
    return result.text if result else ""


def match_verbatim_span(section_content: str, intent_text: str, *, min_ratio: float = 0.58) -> TextMatchResult | None:
    if not section_content or not intent_text or not intent_text.strip():
        return None
    exact_start = section_content.find(intent_text)
    if exact_start >= 0:
        return TextMatchResult(intent_text, exact_start, exact_start + len(intent_text), 1.0, "exact")
    normalized_intent = _normalize_text(intent_text)
    best: tuple[float, int, int, str] | None = None
    for start, end, candidate in _candidate_substrings(section_content):
        score = SequenceMatcher(None, _normalize_text(candidate), normalized_intent).ratio()
        if best is None or score > best[0] or (score == best[0] and (end - start) > (best[2] - best[1])):
            best = (score, start, end, candidate)
    if best is not None and best[0] >= min_ratio:
        return TextMatchResult(best[3], best[1], best[2], best[0], "fuzzy")
    return None


def _candidate_substrings(content: str) -> list[tuple[int, int, str]]:
    candidates: list[tuple[int, int, str]] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    for paragraph in content.split("\n\n"):
        start = content.find(paragraph, cursor)
        end = start + len(paragraph)
        cursor = end + 2
        if paragraph.strip():
            stripped = paragraph.strip()
            strip_start = start + paragraph.find(stripped)
            spans.append((strip_start, strip_start + len(stripped)))
    line_start = 0
    for line in content.splitlines(keepends=True):
        raw = line.rstrip("\n")
        stripped = raw.strip()
        if stripped:
            start = line_start + raw.find(stripped)
            spans.append((start, start + len(stripped)))
            if stripped.startswith(("- ", "* ")):
                bullet_text = stripped[2:].strip()
                bullet_start = start + stripped.find(bullet_text)
                spans.append((bullet_start, bullet_start + len(bullet_text)))
        line_start += len(line)
    seen: set[tuple[int, int]] = set()
    for start, end in spans:
        if start < 0 or end <= start or (start, end) in seen:
            continue
        seen.add((start, end))
        candidates.append((start, end, content[start:end]))
    return candidates


def _section_label(section: PromptSection) -> str:
    return section.name or section.id


def _normalize_reference(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def _mark_unresolved(aligned: dict[str, Any], unresolved: list[str]) -> None:
    if not unresolved:
        return
    extra = dict(aligned.get("extra") or {})
    existing = list(extra.get("unresolved_locators") or [])
    for field_name in unresolved:
        if field_name not in existing:
            existing.append(field_name)
    extra["unresolved_locators"] = existing
    aligned["extra"] = extra


def _status(changes: list[str], unresolved: list[str]) -> str:
    if unresolved and changes:
        return "partial"
    if unresolved:
        return "unresolved"
    if changes:
        return "aligned"
    return "unchanged"


def _assert_payload_unchanged(original: dict[str, Any], aligned: dict[str, Any]) -> None:
    changed_payload = [field for field in PAYLOAD_FIELDS if field in original and original.get(field) != aligned.get(field)]
    if changed_payload:
        raise AssertionError("Patch alignment changed payload fields: " + ", ".join(sorted(changed_payload)))
    changed_non_locator = [field for field in original if field not in LOCATOR_FIELDS and field != "extra" and original.get(field) != aligned.get(field)]
    if changed_non_locator:
        raise AssertionError("Patch alignment changed non-locator fields: " + ", ".join(sorted(changed_non_locator)))
