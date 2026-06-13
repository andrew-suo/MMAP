"""Semantic patch post-processing utilities.

This module normalizes LLM-produced patch payloads and enforces the
invariants required before semantic optimizer output can be consumed by the
rest of the pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import copy
import json
from typing import Any, Iterable, Mapping, Sequence

SEMANTIC_PROCESSOR_VERSION = "2026.06.13"
DEFAULT_SEMANTIC_TEMPLATE_ID = "semantic-patch-v1"
ROOT_AUDIT_SECTION_IDS = {"root", "root-audit", "root_audit"}


@dataclass(slots=True)
class Patch:
    """A normalized patch produced by the semantic optimizer."""

    patch_id: str
    section_id: str
    content: str = ""
    operation: str = "update"
    source_sample_ids: list[str] = field(default_factory=list)
    source_analysis_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Compatibility alias for callers that use ``patch.id``."""

        return self.patch_id

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the patch."""

        return {
            "patch_id": self.patch_id,
            "section_id": self.section_id,
            "content": self.content,
            "operation": self.operation,
            "source_sample_ids": list(self.source_sample_ids),
            "source_analysis_ids": list(self.source_analysis_ids),
            "extra": copy.deepcopy(self.extra),
        }


@dataclass(slots=True)
class SemanticPatchConfig:
    """Configuration for semantic patch normalization."""

    max_output_patches: int | None = None
    semantic_template_id: str = DEFAULT_SEMANTIC_TEMPLATE_ID
    semantic_processor_version: str = SEMANTIC_PROCESSOR_VERSION
    allow_root_audit_cross_section: bool = False


def _patch_id(patch: Patch | Mapping[str, Any]) -> str:
    if isinstance(patch, Patch):
        return patch.patch_id
    return str(patch.get("patch_id") or patch.get("id") or "")


def _section_id(patch: Patch | Mapping[str, Any]) -> str:
    if isinstance(patch, Patch):
        return patch.section_id
    return str(patch.get("section_id") or "")


def _ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _collect_trace_ids(
    patches: Sequence[Patch | Mapping[str, Any]], field_name: str
) -> list[str]:
    """Collect de-duplicated trace ids from a sequence of patches."""

    result: list[str] = []
    seen: set[str] = set()
    for patch in patches:
        values = getattr(patch, field_name) if isinstance(patch, Patch) else patch.get(field_name)
        for value in _ids(values):
            if value not in seen:
                result.append(value)
                seen.add(value)
    return result


def _find_fallback_patch(
    patch_id: str,
    fallback_patch: Patch | Mapping[str, Any] | None,
    input_patches: Sequence[Patch | Mapping[str, Any]],
) -> Patch | Mapping[str, Any] | None:
    if fallback_patch is not None:
        return fallback_patch
    for patch in input_patches:
        if _patch_id(patch) == patch_id:
            return patch
    return None


def _trace_from_patch(
    patch: Patch | Mapping[str, Any] | None,
    field_name: str,
) -> list[str]:
    if patch is None:
        return []
    return _ids(getattr(patch, field_name) if isinstance(patch, Patch) else patch.get(field_name))


def _patch_from_dict(
    raw_patch: Mapping[str, Any],
    *,
    fallback_patch: Patch | Mapping[str, Any] | None = None,
    input_patches: Sequence[Patch | Mapping[str, Any]] = (),
) -> Patch:
    """Build a :class:`Patch` from LLM output, backfilling missing trace ids.

    If the LLM omits ``source_sample_ids`` or ``source_analysis_ids``, values
    are recovered first from the matching fallback patch and then from the full
    input patch collection. This keeps downstream auditability intact even when
    the model returns a lossy patch schema.
    """

    patch_id = str(raw_patch.get("patch_id") or raw_patch.get("id") or "")
    matching_fallback = _find_fallback_patch(patch_id, fallback_patch, input_patches)

    source_sample_ids = _ids(raw_patch.get("source_sample_ids"))
    if not source_sample_ids:
        source_sample_ids = _trace_from_patch(matching_fallback, "source_sample_ids")
    if not source_sample_ids:
        source_sample_ids = _collect_trace_ids(input_patches, "source_sample_ids")

    source_analysis_ids = _ids(raw_patch.get("source_analysis_ids"))
    if not source_analysis_ids:
        source_analysis_ids = _trace_from_patch(matching_fallback, "source_analysis_ids")
    if not source_analysis_ids:
        source_analysis_ids = _collect_trace_ids(input_patches, "source_analysis_ids")

    extra = copy.deepcopy(dict(raw_patch.get("extra") or {}))
    return Patch(
        patch_id=patch_id,
        section_id=str(raw_patch.get("section_id") or ""),
        content=str(raw_patch.get("content") or raw_patch.get("text") or ""),
        operation=str(raw_patch.get("operation") or raw_patch.get("action") or "update"),
        source_sample_ids=source_sample_ids,
        source_analysis_ids=source_analysis_ids,
        extra=extra,
    )


class SemanticPatchProcessor:
    """Normalize and constrain semantic patch output."""

    def __init__(self, config: SemanticPatchConfig | None = None, **config_overrides: Any) -> None:
        if config is None:
            config = SemanticPatchConfig(**config_overrides)
        elif config_overrides:
            config = SemanticPatchConfig(**{**asdict(config), **config_overrides})
        self.config = config

    def normalize(
        self,
        llm_output: str | Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
        input_patches: Sequence[Patch | Mapping[str, Any]],
        *,
        fallback_patches: Sequence[Patch | Mapping[str, Any]] | None = None,
        template_id: str | None = None,
        root_audit: bool = False,
    ) -> list[Patch]:
        """Normalize LLM output into constrained semantic patches."""

        fallback_used = False
        raw_patches = self._extract_raw_patches(llm_output)
        if not raw_patches:
            fallback_used = True
            raw_patches = [self._as_raw_patch(patch) for patch in (fallback_patches or input_patches)]

        input_sections = {_section_id(patch) for patch in input_patches}
        input_patch_ids = [_patch_id(patch) for patch in input_patches]
        fallback_by_id = {_patch_id(patch): patch for patch in (fallback_patches or input_patches)}
        limit = self._output_limit(input_patches)

        patches: list[Patch] = []
        dropped_patch_ids: list[str] = []
        for raw_patch in raw_patches:
            fallback_patch = fallback_by_id.get(str(raw_patch.get("patch_id") or raw_patch.get("id") or ""))
            patch = _patch_from_dict(
                raw_patch,
                fallback_patch=fallback_patch,
                input_patches=input_patches,
            )
            if not self._section_allowed(patch.section_id, input_sections, root_audit=root_audit):
                dropped_patch_ids.append(patch.patch_id)
                continue
            patches.append(patch)

        if len(patches) > limit:
            dropped_patch_ids.extend(patch.patch_id for patch in patches[limit:])
            patches = patches[:limit]

        if root_audit:
            emitted_ids = {patch.patch_id for patch in patches}
            dropped_patch_ids.extend(patch_id for patch_id in input_patch_ids if patch_id not in emitted_ids)

        dropped_patch_ids = _dedupe(dropped_patch_ids)
        for patch in patches:
            patch.extra.update(
                {
                    "semantic_template_id": template_id or self.config.semantic_template_id,
                    "semantic_input_patch_ids": list(input_patch_ids),
                    "semantic_processor_version": self.config.semantic_processor_version,
                    "semantic_fallback_used": fallback_used,
                }
            )
            if root_audit:
                patch.extra["dropped_patch_ids"] = list(dropped_patch_ids)
        return patches

    optimize = normalize
    process = normalize

    def _extract_raw_patches(
        self, llm_output: str | Sequence[Mapping[str, Any]] | Mapping[str, Any] | None
    ) -> list[Mapping[str, Any]]:
        if llm_output is None:
            return []
        parsed: Any = llm_output
        if isinstance(llm_output, str):
            try:
                parsed = json.loads(llm_output)
            except json.JSONDecodeError:
                return []
        if isinstance(parsed, Mapping):
            parsed = parsed.get("patches", [])
        if not isinstance(parsed, Sequence) or isinstance(parsed, (str, bytes, bytearray)):
            return []
        return [item for item in parsed if isinstance(item, Mapping)]

    def _as_raw_patch(self, patch: Patch | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(patch, Patch):
            return patch.to_dict()
        return patch

    def _output_limit(self, input_patches: Sequence[Patch | Mapping[str, Any]]) -> int:
        input_limit = len(input_patches)
        if self.config.max_output_patches is None:
            return input_limit
        return min(input_limit, max(0, self.config.max_output_patches))

    def _section_allowed(self, section_id: str, input_sections: set[str], *, root_audit: bool) -> bool:
        if section_id in input_sections:
            return True
        if root_audit and self.config.allow_root_audit_cross_section:
            return True
        return False


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result
