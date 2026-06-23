import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mmap_optimizer.patch.clusterer import cluster_patches
from mmap_optimizer.patch.conflict import detect_patch_conflicts
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.tree_reduce import TreeReducePatchMerger


def make_patch(patch_id: str, text: str, section: str = "ambiguity_policy", sample_id: str = "s1", operation: str = "ADD_RULE") -> Patch:
    return Patch(
        id=patch_id,
        type="prompt_patch",
        status="candidate",
        target_prompt_type="extraction",
        base_version_id="extraction_prompt_v1",
        section_id=section,
        operation_type=operation,
        operation_mode="append",
        intent_name=patch_id,
        intent_description=patch_id,
        patch_text=text,
        rationale="test",
        source_sample_ids=[sample_id],
        source_analysis_ids=[f"a_{sample_id}"],
        risk_level="low",
    )


class _StubSection:
    def __init__(self, mutability: str = "mutable") -> None:
        self.mutability = mutability


class _StubPromptIR:
    def __init__(self, sections: dict | None = None) -> None:
        self._sections = sections or {}

    def section_by_id(self, section_id: str):
        return self._sections.get(section_id)


def prompt_ir():
    return _StubPromptIR({"output_schema": _StubSection(mutability="frozen")})


def test_cluster_patches_groups_by_target_section_and_operation():
    patches = [make_patch("p1", "a"), make_patch("p2", "b"), make_patch("p3", "c", section="visual_evidence_rules")]

    clusters = cluster_patches(patches)

    assert len(clusters) == 2
    assert [patch.id for patch in clusters[0].patches] == ["p1", "p2"]
    assert clusters[0].id == "cluster_extraction_ambiguity_policy_ADD_RULE"


def test_tree_reduce_deduplicates_and_preserves_trace():
    patches = [make_patch("p1", "检查标签缺失。", sample_id="s1"), make_patch("p2", "检查标签缺失", sample_id="s2")]

    result = TreeReducePatchMerger().merge(round_id="round_000001", patches=patches, prompt_ir=prompt_ir())

    assert [patch.id for patch in result.final_patches] == ["p1"]
    assert result.final_patches[0].source_sample_ids == ["s1", "s2"]
    assert result.rejected_patches[0].rejection_reason == "DUPLICATE_PATCH"
    assert result.merge_report.duplicate_patch_ids == ["p2"]
    assert result.merge_report.final_patch_ids == ["p1"]


def test_tree_reduce_merges_related_non_duplicate_patches():
    patches = [make_patch("p1", "检查标签缺失。", sample_id="s1"), make_patch("p2", "检查安装方向。", sample_id="s2")]

    result = TreeReducePatchMerger().merge(round_id="round_000001", patches=patches, prompt_ir=prompt_ir())

    assert len(result.final_patches) == 1
    merged = result.final_patches[0]
    assert merged.id == "merge_round_000001_extraction_ambiguity_policy_ADD_RULE"
    assert "[p1] 检查标签缺失。" in merged.patch_text
    assert "[p2] 检查安装方向。" in merged.patch_text
    assert merged.source_sample_ids == ["s1", "s2"]
    assert result.merge_report.merged_patch_ids == [merged.id]


def test_tree_reduce_rejects_conflicting_label_bias_patches():
    patches = [make_patch("p1", "此类情况优先输出OK。"), make_patch("p2", "此类情况优先输出NG。", sample_id="s2")]

    result = TreeReducePatchMerger().merge(round_id="round_000001", patches=patches, prompt_ir=prompt_ir())

    assert not result.final_patches
    assert sorted(patch.id for patch in result.rejected_patches) == ["p1", "p2"]
    assert result.merge_report.conflict_patch_ids == ["p1", "p2"]
    assert result.merge_report.clusters[0]["conflicts"][0]["conflict_type"] == "OPPOSITE_LABEL_BIAS"


def test_conflict_detector_flags_frozen_target():
    patch = make_patch("p1", "修改 schema", section="output_schema")

    conflicts = detect_patch_conflicts([patch], prompt_ir())

    assert conflicts[0].conflict_type == "SCHEMA_OR_FROZEN_TARGET"
