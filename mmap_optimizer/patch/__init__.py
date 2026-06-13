"""Patch application utilities."""

from .alignment import AlignedPatchResult, align_patches
from .applier import (
    PatchApplicationError,
    apply_aligned_result,
    apply_patches,
    insert_after,
    insert_before,
    replace_in_section,
)
from .schema import Patch, PatchLocator, PatchPayload
from .validator import PatchValidationError, validate_patch, validate_patches

__all__ = [
    "AlignedPatchResult",
    "Patch",
    "PatchApplicationError",
    "PatchLocator",
    "PatchPayload",
    "PatchValidationError",
    "insert_after",
    "insert_before",
    "align_patches",
    "apply_aligned_result",
    "apply_patches",
    "replace_in_section",
    "validate_patch",
    "validate_patches",
]
