import pytest

from mmap_optimizer.patch.semantic import (
    Patch,
    SemanticPatchConfig,
    SemanticPatchValidationError,
    postprocess_semantic_output,
)


def _input_patch() -> Patch:
    return Patch(
        patch_id="input-1",
        section_id="section-a",
        content="original",
        source_sample_ids=("sample-1",),
        source_analysis_ids=("analysis-1",),
    )


def test_empty_llm_output_returns_fallback_with_semantic_metadata() -> None:
    result = postprocess_semantic_output([], [_input_patch()])

    assert result == [
        Patch(
            patch_id="input-1",
            section_id="section-a",
            content="original",
            source_sample_ids=("sample-1",),
            source_analysis_ids=("analysis-1",),
            extra={
                "semantic_processed_by": "semantic_llm",
                "semantic_input_patch_ids": ("input-1",),
                "semantic_template_id": "semantic_patch_optimizer",
            },
        )
    ]


def test_llm_output_over_configured_maximum_is_rejected() -> None:
    output = [Patch(patch_id=f"out-{idx}", section_id="section-a") for idx in range(3)]

    with pytest.raises(SemanticPatchValidationError, match="max_semantic_output_patches=2"):
        postprocess_semantic_output(
            output,
            [_input_patch()],
            config=SemanticPatchConfig(max_semantic_output_patches=2),
        )


def test_cross_section_llm_output_is_rejected_without_root_audit() -> None:
    output = [Patch(patch_id="out-1", section_id="section-b")]

    with pytest.raises(SemanticPatchValidationError, match="section-b"):
        postprocess_semantic_output(output, [_input_patch()])


def test_cross_section_llm_output_is_allowed_when_root_audit_validator_passes() -> None:
    class PassingValidator:
        def validate_root_audit_patch(self, patch, *, allowed_section_ids, input_patches):
            return patch.patch_id == "out-1" and allowed_section_ids == {"section-a"}

    output = [Patch(patch_id="out-1", section_id="section-b")]

    result = postprocess_semantic_output(
        output,
        [_input_patch()],
        config=SemanticPatchConfig(allow_root_audit_section_expansion=True),
        root_audit_validator=PassingValidator(),
    )

    assert result[0].section_id == "section-b"


def test_missing_trace_fields_are_filled_from_fallback_and_merged_from() -> None:
    fallback = Patch(
        patch_id="fallback-1",
        section_id="section-a",
        source_sample_ids=("sample-fallback",),
        source_analysis_ids=("analysis-fallback",),
    )
    merged_source = Patch(
        patch_id="source-1",
        section_id="section-a",
        source_sample_ids=("sample-merged",),
        source_analysis_ids=("analysis-merged",),
    )
    output = [
        Patch(
            patch_id="out-1",
            section_id="section-a",
            merged_from=("fallback-1", "source-1"),
        )
    ]

    result = postprocess_semantic_output(
        output,
        [fallback, merged_source],
        fallback_patches=[fallback],
    )

    assert result[0].source_sample_ids == ("sample-fallback", "sample-merged")
    assert result[0].source_analysis_ids == ("analysis-fallback", "analysis-merged")
    assert result[0].extra == {
        "semantic_processed_by": "semantic_llm",
        "semantic_input_patch_ids": ("fallback-1", "source-1"),
        "semantic_template_id": "semantic_patch_optimizer",
    }
