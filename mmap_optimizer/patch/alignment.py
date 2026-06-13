from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from mmap_optimizer.prompt.ir import PromptIR, PromptSection

LOCATOR_FIELDS = {"target_section", "section_id", "old_text", "target_text"}
PAYLOAD_FIELDS = {"op", "operation_mode", "content", "patch_text", "new_text", "new_content", "rationale", "reasoning"}


@dataclass
class PatchLocationAlignment:
    original_patch: dict[str, Any]
    aligned_patch: dict[str, Any]
    status: str
    changes: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)

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

        section = self._resolve_section(aligned, prompt_ir)
        if section is None:
            if "target_section" in aligned or "section_id" in aligned:
                unresolved.append("target_section")
            return PatchLocationAlignment(original, aligned, _status(changes, unresolved), changes, unresolved)

        section_label = _section_label(section)
        if aligned.get("target_section") != section_label:
            aligned["target_section"] = section_label
            changes.append("target_section")
        if "section_id" in aligned and aligned.get("section_id") != section.id:
            aligned["section_id"] = section.id
            changes.append("section_id")

        for field_name in ("old_text", "target_text"):
            value = aligned.get(field_name)
            if not isinstance(value, str) or not value.strip():
                continue
            if value in section.content:
                continue
            match = match_verbatim_substring(section.content, value)
            if match:
                aligned[field_name] = match
                changes.append(field_name)
            else:
                unresolved.append(field_name)

        _assert_payload_unchanged(original, aligned)
        return PatchLocationAlignment(original, aligned, _status(changes, unresolved), changes, unresolved)

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
    if not section_content or not intent_text or not intent_text.strip():
        return ""
    if intent_text in section_content:
        return intent_text
    normalized_intent = _normalize_text(intent_text)
    best: tuple[float, str] | None = None
    for candidate in _candidate_substrings(section_content):
        score = SequenceMatcher(None, _normalize_text(candidate), normalized_intent).ratio()
        if best is None or score > best[0] or (score == best[0] and len(candidate) > len(best[1])):
            best = (score, candidate)
    if best is not None and best[0] >= min_ratio:
        return best[1]
    return ""


def _candidate_substrings(content: str) -> list[str]:
    candidates: list[str] = []
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    bullets = [line[2:].strip() for line in lines if line.startswith(("- ", "* "))]
    candidates.extend(paragraphs)
    candidates.extend(lines)
    candidates.extend(bullets)
    unique: list[str] = []
    seen = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def _section_label(section: PromptSection) -> str:
    return section.name or section.id


def _normalize_reference(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _normalize_text(value: str) -> str:
    return "".join(value.lower().split())


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
    changed_non_locator = [field for field in original if field not in LOCATOR_FIELDS and original.get(field) != aligned.get(field)]
    if changed_non_locator:
        raise AssertionError("Patch alignment changed non-locator fields: " + ", ".join(sorted(changed_non_locator)))
