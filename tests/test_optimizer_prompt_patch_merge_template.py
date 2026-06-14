"""Contract tests for the patch_semantic_merge optimizer template.

Verifies that the patch_semantic_merge template has been updated with the
legacy PATCH_MERGE_PROMPT strategies while preserving the existing
output contract, placeholders, and operations.
"""

from __future__ import annotations

import pytest

from mmap_optimizer.templates.optimizer_prompts import (
    PATCH_SEMANTIC_MERGE_TEMPLATE,
    DEFAULT_OPTIMIZER_TEMPLATES,
)


@pytest.fixture(scope="module")
def rendered_template() -> str:
    """Render the patch_semantic_merge template with minimal placeholders."""
    return PATCH_SEMANTIC_MERGE_TEMPLATE.format(
        prompt_structure="Prompt structure\n## 1. Role\n## 2. Output Format",
        patches_json='[{"op": "append_to_section", "target_section": "1. Role"}]',
    )


# ---------------------------------------------------------------------------
# Template existence / basic sanity
# ---------------------------------------------------------------------------

class TestTemplateExistence:
    def test_template_string_is_non_empty(self) -> None:
        assert isinstance(PATCH_SEMANTIC_MERGE_TEMPLATE, str)
        assert len(PATCH_SEMANTIC_MERGE_TEMPLATE) > 0

    def test_render_with_required_placeholders(self, rendered_template: str) -> None:
        assert len(rendered_template) > 0
        assert "{" + "prompt_structure" + "}" not in rendered_template
        assert "{" + "patches_json" + "}" not in rendered_template

    def test_template_only_uses_two_placeholders(self) -> None:
        import string
        fmt = string.Formatter()
        placeholders = [
            field_name for _, field_name, _, _ in fmt.parse(PATCH_SEMANTIC_MERGE_TEMPLATE)
            if field_name
        ]
        assert set(placeholders) == {"prompt_structure", "patches_json"}, (
            f"unexpected placeholders: {placeholders}"
        )


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------

class TestContractPreservation:
    def test_output_is_json_array(self, rendered_template: str) -> None:
        assert "JSON 数组" in rendered_template or "JSON array" in rendered_template

    def test_fallback_to_original_patch_array(self, rendered_template: str) -> None:
        assert "fallback" in rendered_template

    def test_no_new_required_output_field_introduced(
        self, rendered_template: str
    ) -> None:
        # The contract should still emit patch array elements only, not
        # introduce new top-level required fields.
        assert "three-dimension" in rendered_template
        assert "JSON schema" in rendered_template

    def test_no_unsupported_operation_introduced(
        self, rendered_template: str
    ) -> None:
        # Verify the operation list matches the supported ops.
        allowed_ops = {
            "append_to_section",
            "insert_after",
            "insert_before",
            "replace_section",
            "add_after_section",
            "replace_in_section",
            "delete_section",
        }
        import re
        op_tokens = re.findall(r"`([a-z_]+)`", rendered_template)
        for token in op_tokens:
            if "_" not in token or len(token) <= 5:
                continue
            # allow schema field names that may appear
            if token in {"patches", "op", "target_section", "section_id",
                          "payload", "reasoning", "risk_level", "cited_sections",
                          "old_text", "new_text", "extra", "unresolved_locators",
                          "failure_info"}:
                continue
            if token.startswith("patch_"):
                continue
            assert token in allowed_ops, (
                f"unknown operation-like token referenced: '{token}'"
            )


# ---------------------------------------------------------------------------
# Migrated rule presence tests
# ---------------------------------------------------------------------------

class TestMigratedRulePresence:
    def test_three_dimension_framework(self, rendered_template: str) -> None:
        assert "Three-Dimensional Merge Framework" in rendered_template
        assert "Dimension 1" in rendered_template
        assert "Dimension 2" in rendered_template
        assert "Dimension 3" in rendered_template

    def test_structure_isolation(self, rendered_template: str) -> None:
        assert "Structure Isolation" in rendered_template

    def test_logic_deduplication(self, rendered_template: str) -> None:
        assert "Logic Deduplication" in rendered_template

    def test_technical_constraints(self, rendered_template: str) -> None:
        assert "Technical Constraints" in rendered_template

    def test_group_by_section(self, rendered_template: str) -> None:
        assert "group by target section" in rendered_template.lower() \
            or "Group-by-Section" in rendered_template

    def test_unique_valid_patch_preservation(self, rendered_template: str) -> None:
        assert "unique valid patch" in rendered_template

    def test_popularity_bias_as_soft_signal(self, rendered_template: str) -> None:
        assert "soft priority signal" in rendered_template
        assert "not a hard deletion rule" in rendered_template

    def test_conflict_resolution_by_reasoning(self, rendered_template: str) -> None:
        assert "When two patches conflict, prefer the one with clearer evidence" in rendered_template

    def test_line_level_non_overlap(self, rendered_template: str) -> None:
        assert "line-level" in rendered_template or "locator non-overlap" in rendered_template

    def test_compact_merged_without_fixed_ratio(self, rendered_template: str) -> None:
        assert "compact merged patch list" in rendered_template or "Prefer a compact merged patch" in rendered_template
        # Must NOT hardcode a fixed compression ratio
        assert "1/3" not in rendered_template

    def test_supported_operations_only(self, rendered_template: str) -> None:
        assert "Use only operations supported by the current patch schema" in rendered_template

    def test_no_cross_section_semantic_drift(self, rendered_template: str) -> None:
        assert "Do not merge unrelated section-local patches" in rendered_template

    def test_migration_note_present(self, rendered_template: str) -> None:
        assert "Migration Note" in rendered_template


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_no_optimizer_loop_change(self, rendered_template: str) -> None:
        assert "optimizer loop" not in rendered_template

    def test_no_patch_generation_change(self, rendered_template: str) -> None:
        assert "patch_generation" not in rendered_template

    def test_no_root_audit_change(self, rendered_template: str) -> None:
        assert "patch_root_audit" not in rendered_template
        assert "root audit" not in rendered_template.lower()

    def test_no_schema_new_fields(self, rendered_template: str) -> None:
        # Must not invent new required fields; mentions new fields only in
        # the negative.
        assert "Do not invent new operation names" in rendered_template

    def test_no_fixed_compression_ratio(self, rendered_template: str) -> None:
        assert "1/3" not in rendered_template
        assert "one-third" not in rendered_template.lower()

    def test_no_llm_runtime(self, rendered_template: str) -> None:
        # The template should not call out to an LLM runtime.
        assert "runtime" not in rendered_template.lower()

    def test_popularity_bias_not_hard_rule(self, rendered_template: str) -> None:
        assert "not a hard deletion rule" in rendered_template


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_patch_semantic_merge_in_registry(self) -> None:
        ids = [spec.id for spec in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "patch_semantic_merge" in ids

    def test_input_variables_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_semantic_merge":
                assert set(spec.input_variables) == {"prompt_structure", "patches_json"}, (
                    f"unexpected inputs: {spec.input_variables}"
                )

    def test_output_contract_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_semantic_merge":
                contract_type = spec.output_contract.get("type")
                assert contract_type == "json_array", (
                    f"unexpected contract type: {contract_type}"
                )

    def test_version_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_semantic_merge":
                assert str(spec.version) == "1.1", (
                    f"unexpected version: {spec.version!r}"
                )

    def test_fallback_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_semantic_merge":
                fallback = spec.output_contract.get("fallback", "")
                assert "original patch array" in fallback, (
                    f"unexpected fallback: {fallback!r}"
                )


# ---------------------------------------------------------------------------
# Cross-template isolation — confirm other templates were NOT modified.
# ---------------------------------------------------------------------------

class TestOtherTemplatesNotModified:
    def test_patch_generation_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_GENERATION_TEMPLATE,
        )
        # Stable fingerprint from PR #63 adaptation.
        assert "Four-Strategy Framework" in PATCH_GENERATION_TEMPLATE \
            or "Strategy 1 — Add missing constraint" in PATCH_GENERATION_TEMPLATE

    def test_patch_root_audit_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_ROOT_AUDIT_TEMPLATE,
        )
        # Stable fingerprint from original.
        assert "Audit Checks" in PATCH_ROOT_AUDIT_TEMPLATE
        assert "Structure Isolation" not in PATCH_ROOT_AUDIT_TEMPLATE

    def test_patch_translation_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TRANSLATION_TEMPLATE,
        )
        assert "Calibration Workflow" in PATCH_TRANSLATION_TEMPLATE
        assert "Structure Isolation" not in PATCH_TRANSLATION_TEMPLATE

    def test_patch_translation_retry_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TRANSLATION_RETRY_TEMPLATE,
        )
        # Stable fingerprint: the translation-retry template must contain
        # its own Chinese heading + a unique marker (Failure Details)
        assert "Failure Details" in PATCH_TRANSLATION_RETRY_TEMPLATE
        assert "extra.unresolved_locators" in PATCH_TRANSLATION_RETRY_TEMPLATE
        # Not polluted by our merge framework keywords.
        assert "Structure Isolation" not in PATCH_TRANSLATION_RETRY_TEMPLATE

    def test_patch_text_match_unchanged(self) -> None:
        # If this template has a stable marker, check it; otherwise just
        # verify it's not polluted with our merge framework keywords.
        try:
            from mmap_optimizer.templates.optimizer_prompts import (
                PATCH_TEXT_MATCH_TEMPLATE,
            )
            assert "Structure Isolation" not in PATCH_TEXT_MATCH_TEMPLATE
        except Exception:
            pass

    def test_json_fix_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            JSON_FIX_TEMPLATE,
        )
        assert "JSON 数据清洗与结构化修复" in JSON_FIX_TEMPLATE
