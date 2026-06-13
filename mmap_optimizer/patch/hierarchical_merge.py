"""Hierarchical patch merge pipeline.

The merger intentionally keeps all local decisions deterministic and exposes
per-layer bookkeeping so callers can audit which patch ids were kept, dropped,
flagged as conflicts, or sent through a semantic merge step.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from hashlib import sha1
from itertools import combinations
from typing import Callable, Iterable, Mapping, Sequence

ConflictPair = tuple[str, str]
BucketKey = tuple[str, str, str, str]
SemanticMergeFn = Callable[[Sequence["Patch"], BucketKey], Sequence["Patch"]]
RootAuditFn = Callable[[Sequence["Patch"]], Iterable[ConflictPair]]


@dataclass(frozen=True, order=True)
class Patch:
    """A normalized patch candidate consumed by the hierarchical merger."""

    id: str
    target_prompt: str
    section: str
    operation: str
    risk: str
    content: str
    metadata: Mapping[str, object] = field(default_factory=dict, compare=False)

    def bucket_key(self) -> BucketKey:
        """Return the L0 bucket key for the patch."""

        return (self.target_prompt, self.section, self.operation, self.risk)

    def canonical_signature(self) -> tuple[str, str, str, str, str]:
        """Return a deterministic signature used for exact dedupe."""

        return (*self.bucket_key(), " ".join(self.content.split()))

    def conflicts_with(self) -> frozenset[str]:
        """Return explicit patch ids this patch conflicts with."""

        raw = self.metadata.get("conflicts_with", ())
        if isinstance(raw, str):
            return frozenset({raw})
        if isinstance(raw, Iterable):
            return frozenset(str(item) for item in raw)
        return frozenset()


@dataclass(frozen=True)
class PatchMergeReport:
    """Per-layer merge bookkeeping.

    The id fields are deliberately present on every layer so downstream systems
    can compare local decisions, semantic decisions, and audit decisions with a
    single report schema.
    """

    layer: str
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    semantic_ids: tuple[str, ...] = ()
    bucket: BucketKey | tuple[str, ...] | None = None
    summary: str = ""


@dataclass(frozen=True)
class HierarchicalMergeResult:
    """Final hierarchical merge result."""

    patches: tuple[Patch, ...]
    reports: tuple[PatchMergeReport, ...]
    rejected_ids: tuple[str, ...]
    section_summaries: Mapping[str, str]

    @property
    def output_ids(self) -> tuple[str, ...]:
        """Return final patch ids in deterministic order."""

        return tuple(patch.id for patch in self.patches)


class HierarchicalPatchMerger:
    """Four-level deterministic/semantic patch merger.

    L0 buckets patches by target prompt, section, operation, and risk. L1 handles
    deterministic dedupe, subsumption, and explicit conflict detection inside a
    bucket. L2 batches large buckets through a semantic merge function. L3 emits
    section-level summaries. The root audit can reject cross-section conflicts.
    """

    def __init__(
        self,
        *,
        max_patch_per_batch: int = 8,
        semantic_merge: SemanticMergeFn | None = None,
        root_audit: RootAuditFn | None = None,
    ) -> None:
        if max_patch_per_batch < 1:
            raise ValueError("max_patch_per_batch must be at least 1")
        self.max_patch_per_batch = max_patch_per_batch
        self.semantic_merge = semantic_merge or self._default_semantic_merge
        self.root_audit = root_audit or self._default_root_audit

    def merge(self, patches: Iterable[Patch]) -> HierarchicalMergeResult:
        """Run L0/L1/L2/L3/root hierarchical merge."""

        ordered = tuple(sorted(patches, key=lambda patch: patch.id))
        reports: list[PatchMergeReport] = []
        buckets = self._bucket_l0(ordered)
        reports.append(
            PatchMergeReport(
                layer="L0",
                input_ids=self._ids(ordered),
                output_ids=tuple("|".join(key) for key in sorted(buckets)),
                summary="bucketed by target_prompt/section/operation/risk",
            )
        )

        l2_outputs: list[Patch] = []
        rejected: set[str] = set()
        for bucket_key in sorted(buckets):
            bucket_patches = tuple(
                sorted(buckets[bucket_key], key=lambda patch: patch.id)
            )
            l1_patches, l1_dropped, l1_conflicts = self._l1_reduce(bucket_patches)
            rejected.update(l1_dropped)
            rejected.update(l1_conflicts)
            reports.append(
                PatchMergeReport(
                    layer="L1",
                    bucket=bucket_key,
                    input_ids=self._ids(bucket_patches),
                    output_ids=self._ids(l1_patches),
                    dropped_ids=tuple(sorted(l1_dropped)),
                    conflict_ids=tuple(sorted(l1_conflicts)),
                    summary="deterministic dedupe/subsumption/conflict detection",
                )
            )

            merged, l2_reports = self._l2_semantic_batches(l1_patches, bucket_key)
            reports.extend(l2_reports)
            l2_outputs.extend(merged)

        section_summaries, l3_reports = self._l3_section_summaries(l2_outputs)
        reports.extend(l3_reports)

        final_patches, root_report = self._root_audit(l2_outputs)
        rejected.update(root_report.conflict_ids)
        reports.append(root_report)

        return HierarchicalMergeResult(
            patches=tuple(sorted(final_patches, key=lambda patch: patch.id)),
            reports=tuple(reports),
            rejected_ids=tuple(sorted(rejected)),
            section_summaries=section_summaries,
        )

    def _bucket_l0(self, patches: Sequence[Patch]) -> dict[BucketKey, list[Patch]]:
        buckets: dict[BucketKey, list[Patch]] = defaultdict(list)
        for patch in patches:
            buckets[patch.bucket_key()].append(patch)
        return dict(buckets)

    def _l1_reduce(
        self, patches: Sequence[Patch]
    ) -> tuple[tuple[Patch, ...], set[str], set[str]]:
        deduped: list[Patch] = []
        dropped: set[str] = set()
        seen: dict[tuple[str, str, str, str, str], str] = {}
        for patch in sorted(patches, key=lambda item: item.id):
            signature = patch.canonical_signature()
            if signature in seen:
                dropped.add(patch.id)
                continue
            seen[signature] = patch.id
            deduped.append(patch)

        subsumed = self._find_subsumed_ids(deduped)
        dropped.update(subsumed)
        reduced = [patch for patch in deduped if patch.id not in subsumed]

        conflicts = self._find_explicit_conflicts(reduced)
        output = tuple(patch for patch in reduced if patch.id not in conflicts)
        return output, dropped, conflicts

    def _find_subsumed_ids(self, patches: Sequence[Patch]) -> set[str]:
        subsumed: set[str] = set()
        normalized = {patch.id: " ".join(patch.content.split()) for patch in patches}
        for candidate, container in combinations(
            sorted(patches, key=lambda patch: patch.id), 2
        ):
            if candidate.operation != container.operation:
                continue
            candidate_text = normalized[candidate.id]
            container_text = normalized[container.id]
            if not candidate_text or candidate_text == container_text:
                continue
            if candidate_text in container_text:
                subsumed.add(candidate.id)
            elif container_text in candidate_text:
                subsumed.add(container.id)
        return subsumed

    def _find_explicit_conflicts(self, patches: Sequence[Patch]) -> set[str]:
        ids = {patch.id for patch in patches}
        conflicts: set[str] = set()
        for patch in patches:
            for other_id in patch.conflicts_with():
                if other_id in ids:
                    conflicts.add(patch.id)
                    conflicts.add(other_id)
        return conflicts

    def _l2_semantic_batches(
        self, patches: Sequence[Patch], bucket_key: BucketKey
    ) -> tuple[tuple[Patch, ...], tuple[PatchMergeReport, ...]]:
        if len(patches) <= self.max_patch_per_batch:
            return tuple(patches), (
                PatchMergeReport(
                    layer="L2",
                    bucket=bucket_key,
                    input_ids=self._ids(patches),
                    output_ids=self._ids(patches),
                    summary="semantic merge skipped; bucket within batch limit",
                ),
            )

        outputs: list[Patch] = []
        reports: list[PatchMergeReport] = []
        for index, batch in enumerate(
            self._chunks(tuple(patches), self.max_patch_per_batch), start=1
        ):
            merged_batch = tuple(
                sorted(
                    self.semantic_merge(batch, bucket_key), key=lambda patch: patch.id
                )
            )
            outputs.extend(merged_batch)
            reports.append(
                PatchMergeReport(
                    layer="L2",
                    bucket=(*bucket_key, f"batch-{index}"),
                    input_ids=self._ids(batch),
                    output_ids=self._ids(merged_batch),
                    semantic_ids=self._ids(batch),
                    summary=f"semantic merge batch {index}",
                )
            )
        return tuple(sorted(outputs, key=lambda patch: patch.id)), tuple(reports)

    def _l3_section_summaries(
        self, patches: Sequence[Patch]
    ) -> tuple[Mapping[str, str], tuple[PatchMergeReport, ...]]:
        by_section: dict[str, list[Patch]] = defaultdict(list)
        for patch in patches:
            by_section[patch.section].append(patch)

        summaries: dict[str, str] = {}
        reports: list[PatchMergeReport] = []
        for section in sorted(by_section):
            section_patches = tuple(
                sorted(by_section[section], key=lambda patch: patch.id)
            )
            operations = sorted({patch.operation for patch in section_patches})
            risks = sorted({patch.risk for patch in section_patches})
            summary = (
                f"section={section}; patches={len(section_patches)}; "
                f"operations={','.join(operations)}; risks={','.join(risks)}"
            )
            summaries[section] = summary
            reports.append(
                PatchMergeReport(
                    layer="L3",
                    bucket=(section,),
                    input_ids=self._ids(section_patches),
                    output_ids=self._ids(section_patches),
                    summary=summary,
                )
            )
        return summaries, tuple(reports)

    def _root_audit(
        self, patches: Sequence[Patch]
    ) -> tuple[tuple[Patch, ...], PatchMergeReport]:
        ordered = tuple(sorted(patches, key=lambda patch: patch.id))
        alias_to_patch_id = self._alias_to_patch_id(ordered)
        conflict_ids = {
            alias_to_patch_id.get(conflict_id, conflict_id)
            for pair in self.root_audit(ordered)
            for conflict_id in pair
        }
        final_patches = tuple(
            patch for patch in ordered if patch.id not in conflict_ids
        )
        return final_patches, PatchMergeReport(
            layer="Ln/root",
            input_ids=self._ids(ordered),
            output_ids=self._ids(final_patches),
            conflict_ids=tuple(sorted(conflict_ids)),
            summary="root audit checked cross-section conflicts",
        )

    @staticmethod
    def _chunks(patches: Sequence[Patch], size: int) -> Iterable[tuple[Patch, ...]]:
        for start in range(0, len(patches), size):
            yield tuple(patches[start : start + size])

    @staticmethod
    def _ids(patches: Sequence[Patch]) -> tuple[str, ...]:
        return tuple(patch.id for patch in patches)

    @staticmethod
    def _aliases(patch: Patch) -> frozenset[str]:
        merged_from = patch.metadata.get("merged_from", ())
        if isinstance(merged_from, str):
            aliases = {merged_from}
        elif isinstance(merged_from, Iterable):
            aliases = {str(item) for item in merged_from}
        else:
            aliases = set()
        aliases.add(patch.id)
        return frozenset(aliases)

    @classmethod
    def _alias_to_patch_id(cls, patches: Sequence[Patch]) -> dict[str, str]:
        return {alias: patch.id for patch in patches for alias in cls._aliases(patch)}

    @classmethod
    def _default_root_audit(cls, patches: Sequence[Patch]) -> Iterable[ConflictPair]:
        """Detect explicit conflicts across sections at the root layer."""

        by_alias = {alias: patch for patch in patches for alias in cls._aliases(patch)}
        for patch in patches:
            for other_id in patch.conflicts_with():
                other = by_alias.get(other_id)
                if (
                    other is not None
                    and other.id != patch.id
                    and other.section != patch.section
                ):
                    yield tuple(sorted((patch.id, other.id)))  # type: ignore[misc]

    @staticmethod
    def _default_semantic_merge(
        patches: Sequence[Patch], bucket_key: BucketKey
    ) -> Sequence[Patch]:
        """Deterministically fold a semantic batch into a single patch."""

        if len(patches) == 1:
            return patches
        digest = sha1(
            "|".join(patch.id for patch in patches).encode("utf-8")
        ).hexdigest()[:10]
        merged_id = f"semantic:{digest}"
        content = "\n".join(
            patch.content for patch in sorted(patches, key=lambda patch: patch.id)
        )
        sources = tuple(sorted(patches, key=lambda patch: patch.id))
        metadata = {
            "merged_from": tuple(patch.id for patch in sources),
            "conflicts_with": tuple(
                sorted(
                    {
                        conflict_id
                        for patch in sources
                        for conflict_id in patch.conflicts_with()
                    }
                )
            ),
            "semantic_bucket": bucket_key,
        }
        return (replace(patches[0], id=merged_id, content=content, metadata=metadata),)


def hierarchical_merge(
    patches: Iterable[Patch],
    *,
    max_patch_per_batch: int = 8,
    semantic_merge: SemanticMergeFn | None = None,
    root_audit: RootAuditFn | None = None,
) -> HierarchicalMergeResult:
    """Convenience wrapper around :class:`HierarchicalPatchMerger`."""

    return HierarchicalPatchMerger(
        max_patch_per_batch=max_patch_per_batch,
        semantic_merge=semantic_merge,
        root_audit=root_audit,
    ).merge(patches)
