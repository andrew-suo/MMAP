"""Tree-reduction utilities for merging candidate patches.

The reducer performs a fan-in merge: patches are merged in L0 buckets first,
then the bucket outputs are merged again at L1/L2/... until the result stops
shrinking or ``max_levels`` is reached.  Each level emits an auditable report
that records the ids entering and leaving the level as well as rejected,
conflicting, and semantic-fallback patch ids.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, is_dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping, Sequence

Patch = Any
MergeCluster = Callable[[Sequence[Patch]], Any]
RootAudit = Callable[[Sequence[Patch]], Any]


@dataclass(slots=True)
class PatchMergeConfig:
    """Configuration for tree-reduced patch merging."""

    fan_in: int = 8
    max_levels: int = 8
    parallel_merge_enabled: bool = False

    def __post_init__(self) -> None:
        if self.fan_in < 2:
            raise ValueError("fan_in must be >= 2")
        if self.max_levels < 1:
            raise ValueError("max_levels must be >= 1")


@dataclass(slots=True)
class MergeBucketReport:
    """Audit information for a single bucket within a merge level."""

    bucket_index: int
    input_ids: list[str]
    output_ids: list[str]
    rejected_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    semantic_fallback: bool = False


@dataclass(slots=True)
class MergeLevelReport:
    """Audit information for one level in the tree reduction."""

    level: int
    input_ids: list[str]
    output_ids: list[str]
    rejected_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    semantic_fallback: bool = False
    buckets: list[MergeBucketReport] = field(default_factory=list)


@dataclass(slots=True)
class RootAuditReport:
    """Summary of the final root-level audit."""

    input_ids: list[str]
    output_ids: list[str]
    rejected_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    semantic_fallback: bool = False


@dataclass(slots=True)
class PatchMergeReport:
    """Result schema for patch merging.

    ``levels`` is the tree-reduction audit trail.  It is intentionally a first
    class field so callers can inspect how rejected/conflicting ids propagated
    through the fan-in hierarchy.
    """

    output_patches: list[Patch]
    output_ids: list[str]
    rejected_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    semantic_fallback: bool = False
    levels: list[MergeLevelReport] = field(default_factory=list)
    root_audit: RootAuditReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class _ClusterResult:
    output_patches: list[Patch]
    rejected_ids: list[str] = field(default_factory=list)
    conflict_ids: list[str] = field(default_factory=list)
    semantic_fallback: bool = False


def tree_reduce_patches(
    candidate_patches: Sequence[Patch],
    *,
    fan_in: int = 8,
    max_levels: int = 8,
    parallel_merge_enabled: bool = False,
    merge_cluster: MergeCluster | None = None,
    root_audit: RootAudit | None = None,
) -> PatchMergeReport:
    """Merge candidate patches through a bounded fan-in reduction tree.

    Args:
        candidate_patches: Candidate patches.  Patches may be mappings,
            dataclasses, or arbitrary objects.  Ids are read from ``id`` /
            ``patch_id`` / ``name`` when available; otherwise a stable hash is
            generated from the patch value.
        fan_in: Number of patches per bucket at each level.
        max_levels: Maximum number of merge levels before the root audit.
        parallel_merge_enabled: Run per-level buckets in a thread pool when
            true.  Ordering is preserved in the emitted reports and outputs.
        merge_cluster: Optional cluster merge function.  If omitted, the module
            default ``_merge_cluster`` is used.
        root_audit: Optional final audit function.  If omitted, the module
            default ``_root_audit`` is used.
    """

    config = PatchMergeConfig(
        fan_in=fan_in,
        max_levels=max_levels,
        parallel_merge_enabled=parallel_merge_enabled,
    )
    cluster_fn = merge_cluster or _merge_cluster
    root_audit_fn = root_audit or _root_audit

    current = list(candidate_patches)
    levels: list[MergeLevelReport] = []
    all_rejected: list[str] = []
    all_conflicts: list[str] = []
    semantic_fallback = False

    for level_index in range(config.max_levels):
        if len(current) <= 1:
            break

        level_input_ids = patch_ids(current)
        # Grow the effective bucket span at each level.  This preserves L0
        # fan-in behavior while ensuring patches separated into different L0
        # buckets can meet at L1/L2 instead of being regrouped identically.
        level_fan_in = config.fan_in ** (level_index + 1)
        buckets = _bucketize(current, level_fan_in)
        bucket_results = _merge_buckets(
            buckets,
            cluster_fn=cluster_fn,
            parallel=config.parallel_merge_enabled,
        )

        next_patches: list[Patch] = []
        bucket_reports: list[MergeBucketReport] = []
        level_rejected: list[str] = []
        level_conflicts: list[str] = []
        level_fallback = False

        for bucket_index, (bucket, result) in enumerate(zip(buckets, bucket_results)):
            normalized = _normalize_cluster_result(result, bucket)
            output_ids = patch_ids(normalized.output_patches)
            next_patches.extend(normalized.output_patches)
            level_rejected.extend(normalized.rejected_ids)
            level_conflicts.extend(normalized.conflict_ids)
            level_fallback = level_fallback or normalized.semantic_fallback
            bucket_reports.append(
                MergeBucketReport(
                    bucket_index=bucket_index,
                    input_ids=patch_ids(bucket),
                    output_ids=output_ids,
                    rejected_ids=list(normalized.rejected_ids),
                    conflict_ids=list(normalized.conflict_ids),
                    semantic_fallback=normalized.semantic_fallback,
                )
            )

        # Protect unique boundary patches by ensuring they survive every level
        # even if a custom merge function accidentally drops them.
        next_patches = _restore_unique_boundary_patches(current, next_patches)

        level_report = MergeLevelReport(
            level=level_index,
            input_ids=level_input_ids,
            output_ids=patch_ids(next_patches),
            rejected_ids=_stable_unique(level_rejected),
            conflict_ids=_stable_unique(level_conflicts),
            semantic_fallback=level_fallback,
            buckets=bucket_reports,
        )
        levels.append(level_report)
        all_rejected.extend(level_report.rejected_ids)
        all_conflicts.extend(level_report.conflict_ids)
        semantic_fallback = semantic_fallback or level_fallback

        # Continue while multiple buckets remain so conflicts/duplicates that
        # were separated at lower levels can still meet at an upper level.
        # Convergence is only final once a whole level is represented by a
        # single bucket and the merge no longer shrinks the patch set.
        converged = (
            patch_ids(next_patches) == patch_ids(current)
            or len(next_patches) >= len(current)
        )
        if len(buckets) == 1 and converged:
            current = next_patches
            break
        current = next_patches

    audit_result = _normalize_root_audit_result(root_audit_fn(current), current)
    final_patches = _restore_unique_boundary_patches(current, audit_result.output_patches)
    root_report = RootAuditReport(
        input_ids=patch_ids(current),
        output_ids=patch_ids(final_patches),
        rejected_ids=_stable_unique(audit_result.rejected_ids),
        conflict_ids=_stable_unique(audit_result.conflict_ids),
        semantic_fallback=audit_result.semantic_fallback,
    )
    all_rejected.extend(root_report.rejected_ids)
    all_conflicts.extend(root_report.conflict_ids)
    semantic_fallback = semantic_fallback or root_report.semantic_fallback

    return PatchMergeReport(
        output_patches=final_patches,
        output_ids=patch_ids(final_patches),
        rejected_ids=_stable_unique(all_rejected),
        conflict_ids=_stable_unique(all_conflicts),
        semantic_fallback=semantic_fallback,
        levels=levels,
        root_audit=root_report,
    )


# Backwards-friendly aliases callers may already use.
reduce_patches = tree_reduce_patches
merge_patches = tree_reduce_patches


def _merge_cluster(patches: Sequence[Patch]) -> _ClusterResult:
    """Default cluster merge.

    The default is intentionally conservative: identical non-boundary patches
    are de-duplicated, obvious same-target/different-content conflicts are
    rejected, and unique boundary patches are always retained.  Projects with a
    richer semantic merger can pass it via ``merge_cluster`` while still getting
    the tree reducer and reporting behavior.
    """

    outputs: list[Patch] = []
    seen_fingerprints: set[str] = set()
    target_fingerprints: dict[str, str] = {}
    rejected_ids: list[str] = []
    conflict_ids: list[str] = []
    fallback = False

    for patch in patches:
        pid = patch_id(patch)
        fingerprint = _patch_fingerprint(patch)
        target = _patch_target(patch)
        is_boundary = _is_unique_boundary_patch(patch)

        if target is not None:
            prior = target_fingerprints.get(target)
            if prior is not None and prior != fingerprint and not is_boundary:
                conflict_ids.append(pid)
                rejected_ids.append(pid)
                continue
            target_fingerprints.setdefault(target, fingerprint)
        else:
            fallback = True

        if not is_boundary and fingerprint in seen_fingerprints:
            rejected_ids.append(pid)
            continue

        seen_fingerprints.add(fingerprint)
        outputs.append(patch)

    return _ClusterResult(
        output_patches=outputs,
        rejected_ids=_stable_unique(rejected_ids),
        conflict_ids=_stable_unique(conflict_ids),
        semantic_fallback=fallback,
    )


def _root_audit(patches: Sequence[Patch]) -> _ClusterResult:
    """Final global audit used after level reduction."""

    return _merge_cluster(patches)


def patch_ids(patches: Iterable[Patch]) -> list[str]:
    return [patch_id(patch) for patch in patches]


def patch_id(patch: Patch) -> str:
    for key in ("id", "patch_id", "name"):
        value = _get_value(patch, key)
        if value is not None:
            return str(value)
    return "patch:" + sha256(_json_bytes(_project_patch(patch))).hexdigest()[:16]


def _bucketize(items: Sequence[Patch], fan_in: int) -> list[list[Patch]]:
    return [list(items[index : index + fan_in]) for index in range(0, len(items), fan_in)]


def _merge_buckets(
    buckets: Sequence[Sequence[Patch]],
    *,
    cluster_fn: MergeCluster,
    parallel: bool,
) -> list[Any]:
    if not parallel or len(buckets) <= 1:
        return [cluster_fn(bucket) for bucket in buckets]
    with ThreadPoolExecutor(max_workers=len(buckets)) as executor:
        return list(executor.map(cluster_fn, buckets))


def _normalize_cluster_result(result: Any, fallback_input: Sequence[Patch]) -> _ClusterResult:
    if isinstance(result, _ClusterResult):
        return result
    if isinstance(result, PatchMergeReport):
        return _ClusterResult(
            output_patches=list(result.output_patches),
            rejected_ids=list(result.rejected_ids),
            conflict_ids=list(result.conflict_ids),
            semantic_fallback=result.semantic_fallback,
        )
    if isinstance(result, Mapping):
        output = result.get(
            "output_patches",
            result.get("patches", result.get("outputs", fallback_input)),
        )
        return _ClusterResult(
            output_patches=list(output),
            rejected_ids=[str(item) for item in result.get("rejected_ids", [])],
            conflict_ids=[str(item) for item in result.get("conflict_ids", [])],
            semantic_fallback=bool(result.get("semantic_fallback", False)),
        )
    if is_dataclass(result):
        return _normalize_cluster_result(asdict(result), fallback_input)
    if isinstance(result, tuple):
        output = result[0] if result else fallback_input
        rejected = result[1] if len(result) > 1 else []
        conflicts = result[2] if len(result) > 2 else []
        fallback = result[3] if len(result) > 3 else False
        return _ClusterResult(
            list(output),
            [str(x) for x in rejected],
            [str(x) for x in conflicts],
            bool(fallback),
        )
    return _ClusterResult(
        output_patches=list(result if result is not None else fallback_input)
    )


def _normalize_root_audit_result(result: Any, fallback_input: Sequence[Patch]) -> _ClusterResult:
    return _normalize_cluster_result(result, fallback_input)


def _restore_unique_boundary_patches(source: Sequence[Patch], merged: Sequence[Patch]) -> list[Patch]:
    output = list(merged)
    output_ids = set(patch_ids(output))
    for patch in source:
        if _is_unique_boundary_patch(patch) and patch_id(patch) not in output_ids:
            output.append(patch)
            output_ids.add(patch_id(patch))
    return output


def _is_unique_boundary_patch(patch: Patch) -> bool:
    for key in ("unique_boundary", "is_unique_boundary", "boundary", "is_boundary"):
        value = _get_value(patch, key)
        if value is not None:
            return bool(value)
    metadata = _get_value(patch, "metadata")
    if isinstance(metadata, Mapping):
        return any(
            bool(metadata.get(key))
            for key in ("unique_boundary", "is_unique_boundary", "boundary", "is_boundary")
        )
    return False


def _patch_target(patch: Patch) -> str | None:
    for key in ("target", "path", "file", "filename", "module"):
        value = _get_value(patch, key)
        if value is not None:
            return str(value)
    metadata = _get_value(patch, "metadata")
    if isinstance(metadata, Mapping):
        for key in ("target", "path", "file", "filename", "module"):
            if metadata.get(key) is not None:
                return str(metadata[key])
    return None


def _patch_fingerprint(patch: Patch) -> str:
    projected = _project_patch(patch, exclude_ids=True)
    return sha256(_json_bytes(projected)).hexdigest()


def _project_patch(patch: Patch, *, exclude_ids: bool = False) -> Any:
    if is_dataclass(patch):
        patch = asdict(patch)
    if isinstance(patch, Mapping):
        excluded = {"id", "patch_id", "name"} if exclude_ids else set()
        return {
            str(key): _project_patch(value, exclude_ids=False)
            for key, value in sorted(patch.items(), key=lambda item: str(item[0]))
            if key not in excluded
        }
    if isinstance(patch, (list, tuple)):
        return [_project_patch(value, exclude_ids=False) for value in patch]
    if isinstance(patch, (str, int, float, bool)) or patch is None:
        return patch
    if hasattr(patch, "__dict__"):
        return _project_patch(vars(patch), exclude_ids=exclude_ids)
    return repr(patch)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=repr,
    ).encode("utf-8")


def _get_value(patch: Patch, key: str) -> Any:
    if isinstance(patch, Mapping):
        return patch.get(key)
    return getattr(patch, key, None)


def _stable_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        value = str(item)
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
