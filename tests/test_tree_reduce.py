from mmap_optimizer.patch.tree_reduce import PatchMergeReport, tree_reduce_patches


def patch(pid, path, content, **extra):
    return {"id": pid, "path": path, "content": content, **extra}


def test_multi_level_merge_reports_are_emitted():
    patches = [
        patch("a", "a.py", "1"),
        patch("b", "b.py", "1"),
        patch("c", "c.py", "1"),
        patch("d", "d.py", "1"),
        patch("e", "e.py", "1"),
    ]

    report = tree_reduce_patches(patches, fan_in=2, max_levels=4)

    assert isinstance(report, PatchMergeReport)
    assert [level.level for level in report.levels] == [0, 1, 2]
    assert report.levels[0].input_ids == ["a", "b", "c", "d", "e"]
    assert report.root_audit.input_ids == report.output_ids


def test_isolated_patch_is_preserved_across_levels():
    patches = [
        patch("a", "a.py", "1"),
        patch("b", "b.py", "1"),
        patch("isolated", "isolated.py", "keep"),
    ]

    report = tree_reduce_patches(patches, fan_in=2, max_levels=3)

    assert "isolated" in report.output_ids
    assert "isolated" not in report.rejected_ids


def test_conflict_propagates_across_levels():
    patches = [
        patch("a", "shared.py", "left"),
        patch("x", "x.py", "1"),
        patch("b", "shared.py", "right"),
        patch("y", "y.py", "1"),
    ]

    report = tree_reduce_patches(patches, fan_in=2, max_levels=3)

    assert "b" in report.conflict_ids
    assert "b" in report.rejected_ids
    assert any("b" in level.conflict_ids for level in report.levels)
    assert "a" in report.output_ids
    assert "b" not in report.output_ids


def test_duplicate_patch_is_deduplicated_across_levels():
    patches = [
        patch("a", "a.py", "same"),
        patch("x", "x.py", "1"),
        patch("a-dup", "a.py", "same"),
        patch("y", "y.py", "1"),
    ]

    report = tree_reduce_patches(patches, fan_in=2, max_levels=3)

    assert "a" in report.output_ids
    assert "a-dup" not in report.output_ids
    assert "a-dup" in report.rejected_ids


def test_unique_boundary_patch_is_protected_when_custom_merger_drops_it():
    boundary = patch("boundary", "boundary.py", "keep", unique_boundary=True)
    regular = patch("regular", "regular.py", "keep")

    def dropping_merger(bucket):
        return {"output_patches": [p for p in bucket if p["id"] != "boundary"]}

    report = tree_reduce_patches(
        [boundary, regular],
        fan_in=2,
        max_levels=2,
        merge_cluster=dropping_merger,
        root_audit=dropping_merger,
    )

    assert "boundary" in report.output_ids
