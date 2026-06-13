"""Patch merge utilities."""

from .hierarchical_merge import (
    HierarchicalMergeResult,
    HierarchicalPatchMerger,
    Patch,
    PatchMergeReport,
    hierarchical_merge,
)

__all__ = [
    "HierarchicalMergeResult",
    "HierarchicalPatchMerger",
    "Patch",
    "PatchMergeReport",
    "hierarchical_merge",
]
