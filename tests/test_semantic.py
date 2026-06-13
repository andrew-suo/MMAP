import pytest

from mmap_optimizer.patch.semantic import Patch, SemanticPatchConfig, SemanticPatchProcessor, _patch_from_dict


def _inputs():
    return [
        Patch(
            patch_id="p1",
            section_id="s1",
            content="one",
            source_sample_ids=["sample-1"],
            source_analysis_ids=["analysis-1"],
        ),
        Patch(
            patch_id="p2",
            section_id="s2",
            content="two",
            source_sample_ids=["sample-2"],
            source_analysis_ids=["analysis-2"],
        ),
    ]


def test_empty_output_uses_fallback_and_records_metadata():
    processor = SemanticPatchProcessor(SemanticPatchConfig(max_output_patches=1))

    patches = processor.normalize({"patches": []}, _inputs(), template_id="tpl-empty")

    assert [patch.patch_id for patch in patches] == ["p1"]
    assert patches[0].extra["semantic_fallback_used"] is True
    assert patches[0].extra["semantic_template_id"] == "tpl-empty"
    assert patches[0].extra["semantic_input_patch_ids"] == ["p1", "p2"]
    assert patches[0].extra["semantic_processor_version"]


def test_excess_output_is_capped_by_input_count_and_config_limit():
    processor = SemanticPatchProcessor(SemanticPatchConfig(max_output_patches=1))
    raw = {"patches": [
        {"patch_id": "p1", "section_id": "s1", "content": "a"},
        {"patch_id": "p2", "section_id": "s2", "content": "b"},
        {"patch_id": "p3", "section_id": "s1", "content": "c"},
    ]}

    patches = processor.normalize(raw, _inputs())

    assert [patch.patch_id for patch in patches] == ["p1"]


def test_cross_section_output_is_removed_unless_root_audit_allows_it():
    raw = {"patches": [{"patch_id": "p3", "section_id": "s3", "content": "x"}]}

    blocked = SemanticPatchProcessor().normalize(raw, _inputs())
    allowed = SemanticPatchProcessor(
        SemanticPatchConfig(allow_root_audit_cross_section=True)
    ).normalize(raw, _inputs(), root_audit=True)

    assert blocked == []
    assert [patch.section_id for patch in allowed] == ["s3"]


def test_patch_from_dict_backfills_missing_trace_ids_from_fallback_or_inputs():
    input_patches = _inputs()

    from_fallback = _patch_from_dict(
        {"patch_id": "p1", "section_id": "s1"},
        fallback_patch=input_patches[0],
        input_patches=input_patches,
    )
    from_inputs = _patch_from_dict(
        {"patch_id": "new", "section_id": "s1"},
        input_patches=input_patches,
    )

    assert from_fallback.source_sample_ids == ["sample-1"]
    assert from_fallback.source_analysis_ids == ["analysis-1"]
    assert from_inputs.source_sample_ids == ["sample-1", "sample-2"]
    assert from_inputs.source_analysis_ids == ["analysis-1", "analysis-2"]


def test_invalid_json_uses_fallback():
    patches = SemanticPatchProcessor().normalize("not json", _inputs())

    assert [patch.patch_id for patch in patches] == ["p1", "p2"]
    assert all(patch.extra["semantic_fallback_used"] is True for patch in patches)


def test_root_audit_records_dropped_patch_ids_for_merge_or_delete():
    raw = {"patches": [{"patch_id": "p1", "section_id": "s1", "content": "merged"}]}

    patches = SemanticPatchProcessor().normalize(raw, _inputs(), root_audit=True)

    assert patches[0].extra["dropped_patch_ids"] == ["p2"]
