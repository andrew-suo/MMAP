"""Tree-reduce patch merger with section-risk-aware ordering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from mmap_optimizer.metrics.section_contribution import compute_section_risk


@dataclass
class PatchCandidate:
    patch_id: str
    section_id: str
    content: str
    cited: float = 0.0
    parasite: float = 0.0
    accuracy: float = 1.0
    safe: bool = False
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_score(self) -> float:
        return compute_section_risk(self.cited, self.parasite, self.accuracy)


def _coerce_patch(patch: PatchCandidate | Mapping[str, Any]) -> PatchCandidate:
    if isinstance(patch, PatchCandidate):
        return patch
    metrics = dict(patch.get("metrics", {})) if isinstance(patch.get("metrics", {}), Mapping) else {}
    return PatchCandidate(
        patch_id=str(patch.get("patch_id", patch.get("id", ""))),
        section_id=str(patch.get("section_id", "")),
        content=str(patch.get("content", patch.get("patch", ""))),
        cited=float(patch.get("cited", metrics.get("cited", 0.0))),
        parasite=float(patch.get("parasite", metrics.get("parasite", 0.0))),
        accuracy=float(patch.get("accuracy", metrics.get("accuracy", 1.0))),
        safe=bool(patch.get("safe", patch.get("is_safe", False))),
        score=float(patch.get("score", 0.0)),
        metadata=dict(patch.get("metadata", {})),
    )


class TreeReducePatchMerger:
    """Merge patch candidates while protecting safe patches for risky sections."""

    def __init__(self, *, max_patches: int | None = None) -> None:
        self.max_patches = max_patches

    def rank_patches(self, patches: Iterable[PatchCandidate | Mapping[str, Any]]) -> list[PatchCandidate]:
        coerced = [_coerce_patch(patch) for patch in patches]
        return sorted(
            coerced,
            key=lambda patch: (
                1 if patch.safe else 0,
                patch.risk_score,
                patch.cited,
                patch.parasite,
                -patch.accuracy,
                patch.score,
            ),
            reverse=True,
        )

    def merge(self, patches: Iterable[PatchCandidate | Mapping[str, Any]]) -> list[PatchCandidate]:
        ranked = self.rank_patches(patches)
        if self.max_patches is None:
            return ranked
        return ranked[: self.max_patches]
