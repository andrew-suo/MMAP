"""Semantic patch post-processing and validation utilities.

This module normalizes patches produced by an LLM-based semantic optimizer before
those patches are allowed back into the rest of the pipeline.  The checks are
intentionally strict around output size, section boundaries, and trace metadata
because semantic rewrites are generated outside the deterministic patch planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Protocol, Sequence


class SemanticPatchValidationError(ValueError):
    """Raised when LLM semantic patch output violates safety constraints."""


@dataclass(frozen=True)
class Patch:
    """A minimal patch representation used by semantic post-processing.

    The project can pass richer patch-like values by converting them to this
    structure at the semantic boundary.  Trace fields are modeled explicitly so
    they can be preserved across LLM output, fallbacks, and merged patches.
    """

    patch_id: str
    section_id: str
    content: str = ""
    source_sample_ids: tuple[str, ...] = ()
    source_analysis_ids: tuple[str, ...] = ()
    merged_from: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticPatchConfig:
    """Configuration for semantic LLM output validation."""

    max_semantic_output_patches: int = 8
    semantic_processed_by: str = "semantic_llm"
    semantic_template_id: str = "semantic_patch_optimizer"
    allow_root_audit_section_expansion: bool = False


class RootAuditValidator(Protocol):
    """Validator hook for rare root-audit approved cross-section edits."""

    def validate_root_audit_patch(
        self,
        patch: Patch,
        *,
        allowed_section_ids: set[str],
        input_patches: Sequence[Patch],
    ) -> bool:
        """Return True only when the cross-section patch is explicitly valid."""


def postprocess_semantic_output(
    llm_output_patches: Sequence[Patch],
    input_patches: Sequence[Patch],
    *,
    config: SemanticPatchConfig | None = None,
    fallback_patches: Sequence[Patch] | None = None,
    root_audit_validator: RootAuditValidator | None = None,
) -> list[Patch]:
    """Validate and normalize semantic patches produced by an LLM.

    Args:
        llm_output_patches: Patches returned by the LLM.
        input_patches: Patches originally sent to the LLM.
        config: Semantic post-processing constraints and metadata.
        fallback_patches: Deterministic patches used when LLM output is empty or
            when trace metadata must be restored.
        root_audit_validator: Optional validator for explicitly approved
            root-audit cross-section patches.

    Returns:
        Validated patches with preserved trace metadata and semantic provenance
        written into ``Patch.extra``.

    Raises:
        SemanticPatchValidationError: If the LLM emits too many patches or tries
        to edit a section outside the input section set without an approved root
        audit validation.
    """

    config = config or SemanticPatchConfig()
    fallback_patches = tuple(fallback_patches or input_patches)
    input_patches = tuple(input_patches)
    llm_output_patches = tuple(llm_output_patches)

    if len(llm_output_patches) > config.max_semantic_output_patches:
        raise SemanticPatchValidationError(
            "semantic LLM output produced "
            f"{len(llm_output_patches)} patches, exceeding configured maximum "
            f"max_semantic_output_patches={config.max_semantic_output_patches}"
        )

    allowed_section_ids = {patch.section_id for patch in input_patches}
    semantic_input_patch_ids = tuple(patch.patch_id for patch in input_patches)

    selected_patches = llm_output_patches or fallback_patches
    normalized: list[Patch] = []
    for patch in selected_patches:
        if patch.section_id not in allowed_section_ids and not _root_audit_allows_section(
            patch,
            allowed_section_ids=allowed_section_ids,
            input_patches=input_patches,
            config=config,
            root_audit_validator=root_audit_validator,
        ):
            raise SemanticPatchValidationError(
                f"semantic LLM output patch {patch.patch_id!r} targets section "
                f"{patch.section_id!r}, which is not present in input sections "
                f"{sorted(allowed_section_ids)!r}"
            )

        normalized.append(
            _with_trace_and_semantic_extra(
                patch,
                fallback_patches=fallback_patches,
                input_patches=input_patches,
                semantic_input_patch_ids=semantic_input_patch_ids,
                config=config,
            )
        )

    return normalized


def _root_audit_allows_section(
    patch: Patch,
    *,
    allowed_section_ids: set[str],
    input_patches: Sequence[Patch],
    config: SemanticPatchConfig,
    root_audit_validator: RootAuditValidator | None,
) -> bool:
    """Return whether a cross-section patch is explicitly allowed."""

    explicitly_allowed = bool(
        config.allow_root_audit_section_expansion
        or patch.extra.get("root_audit_allows_section_expansion")
    )
    if not explicitly_allowed or root_audit_validator is None:
        return False
    return bool(
        root_audit_validator.validate_root_audit_patch(
            patch,
            allowed_section_ids=allowed_section_ids,
            input_patches=input_patches,
        )
    )


def _with_trace_and_semantic_extra(
    patch: Patch,
    *,
    fallback_patches: Sequence[Patch],
    input_patches: Sequence[Patch],
    semantic_input_patch_ids: tuple[str, ...],
    config: SemanticPatchConfig,
) -> Patch:
    """Return ``patch`` with required trace fields and semantic provenance."""

    sample_ids = patch.source_sample_ids or _merged_trace(
        patch,
        fallback_patches,
        input_patches,
        attr="source_sample_ids",
    )
    analysis_ids = patch.source_analysis_ids or _merged_trace(
        patch,
        fallback_patches,
        input_patches,
        attr="source_analysis_ids",
    )
    extra = dict(patch.extra)
    extra.update(
        {
            "semantic_processed_by": config.semantic_processed_by,
            "semantic_input_patch_ids": semantic_input_patch_ids,
            "semantic_template_id": config.semantic_template_id,
        }
    )
    return replace(
        patch,
        source_sample_ids=tuple(sample_ids),
        source_analysis_ids=tuple(analysis_ids),
        extra=extra,
    )


def _merged_trace(
    patch: Patch,
    fallback_patches: Sequence[Patch],
    input_patches: Sequence[Patch],
    *,
    attr: str,
) -> tuple[str, ...]:
    """Resolve missing trace data from fallback patches or merged_from links."""

    lookup = {candidate.patch_id: candidate for candidate in (*fallback_patches, *input_patches)}
    candidates: list[Patch] = []

    if patch.patch_id in lookup:
        candidates.append(lookup[patch.patch_id])

    for source_id in patch.merged_from:
        source = lookup.get(source_id)
        if source is not None:
            candidates.append(source)

    if not candidates and len(fallback_patches) == 1:
        candidates.append(fallback_patches[0])

    seen: set[str] = set()
    values: list[str] = []
    for candidate in candidates:
        for value in _as_tuple(getattr(candidate, attr)):
            if value not in seen:
                seen.add(value)
                values.append(value)
    return tuple(values)


def _as_tuple(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(values)


# Backward-friendly aliases for callers that use shorter semantic terminology.
SemanticConfig = SemanticPatchConfig
SemanticValidationError = SemanticPatchValidationError
process_semantic_patches = postprocess_semantic_output
