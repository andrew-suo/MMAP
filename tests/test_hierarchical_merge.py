from mmap_optimizer.patch.hierarchical_merge import HierarchicalPatchMerger, Patch


def patch(pid, section="intro", content=None, **metadata):
    return Patch(
        id=pid,
        target_prompt="prompt-a",
        section=section,
        operation="replace",
        risk="low",
        content=content or f"content {pid}",
        metadata=metadata,
    )


def test_large_patch_set_is_bucketed_and_semantically_merged_in_batches():
    seen_batches = []

    def semantic_merge(batch, bucket):
        seen_batches.append(tuple(item.id for item in batch))
        return (
            patch(
                f"merged-{len(seen_batches)}",
                content="\n".join(item.content for item in batch),
            ),
        )

    patches = [patch(f"p{i:02d}") for i in range(7)]
    result = HierarchicalPatchMerger(
        max_patch_per_batch=3, semantic_merge=semantic_merge
    ).merge(patches)

    assert seen_batches == [
        ("p00", "p01", "p02"),
        ("p03", "p04", "p05"),
        ("p06",),
    ]
    assert result.output_ids == ("merged-1", "merged-2", "merged-3")
    l2_semantic_reports = [
        report
        for report in result.reports
        if report.layer == "L2" and report.semantic_ids
    ]
    assert [report.semantic_ids for report in l2_semantic_reports] == seen_batches
    assert all(len(report.semantic_ids) <= 3 for report in l2_semantic_reports)


def test_cross_section_root_audit_rejects_conflicting_patches():
    patches = [
        patch("keep", section="intro"),
        patch("a", section="intro", conflicts_with=("b",)),
        patch("b", section="body"),
    ]

    result = HierarchicalPatchMerger().merge(patches)

    assert result.output_ids == ("keep",)
    assert result.rejected_ids == ("a", "b")
    root_report = next(report for report in result.reports if report.layer == "Ln/root")
    assert root_report.conflict_ids == ("a", "b")


def test_isolated_patch_is_preserved_without_semantic_merge():
    result = HierarchicalPatchMerger(max_patch_per_batch=2).merge([patch("solo")])

    assert result.output_ids == ("solo",)
    assert result.rejected_ids == ()
    assert result.section_summaries["intro"].startswith("section=intro; patches=1")


def test_conflicting_patch_in_same_bucket_is_rejected_at_l1():
    patches = [
        patch("winner"),
        patch("left", conflicts_with=("right",)),
        patch("right"),
    ]

    result = HierarchicalPatchMerger().merge(patches)

    assert result.output_ids == ("winner",)
    l1_report = next(report for report in result.reports if report.layer == "L1")
    assert l1_report.conflict_ids == ("left", "right")
    assert result.rejected_ids == ("left", "right")


def test_l1_dedupes_and_drops_subsumed_patches_deterministically():
    result = HierarchicalPatchMerger().merge(
        [
            patch("p1", content="set alpha"),
            patch("p2", content="set alpha"),
            patch("p3", content="set alpha and beta"),
        ]
    )

    assert result.output_ids == ("p3",)
    l1_report = next(report for report in result.reports if report.layer == "L1")
    assert l1_report.dropped_ids == ("p1", "p2")
