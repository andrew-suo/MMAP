"""Helpers for exercising patches in tests and optimization pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from mmap_optimizer.patch.applier import PatchApplyError, apply_patch
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidationError


@dataclass(slots=True)
class PatchTestResult:
    """Result of attempting to validate and apply one patch."""

    status: str
    document: Any | None = None
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def rejected(self) -> bool:
        return self.status == "rejected"


def test_patch(document: Any, patch: Patch | Mapping[str, Any]) -> PatchTestResult:
    """Apply a patch and mark validation/location failures as rejected."""

    try:
        patched_document = apply_patch(document, patch, validate=True, copy=True)
    except (PatchApplyError, PatchValidationError, ValueError) as exc:
        return PatchTestResult(status="rejected", error=str(exc))
    return PatchTestResult(status="accepted", document=patched_document)


test_patch.__test__ = False


def test_patches(document: Any, patches: list[Patch | Mapping[str, Any]]) -> list[PatchTestResult]:
    """Test patches independently against the same source document."""

    return [test_patch(document, patch) for patch in patches]


test_patches.__test__ = False
