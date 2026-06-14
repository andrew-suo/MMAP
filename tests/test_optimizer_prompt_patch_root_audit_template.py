"""Contract tests for the patch_root_audit optimizer template.

Verifies that the patch_root_audit template has been updated with the
legacy PATCH_ROOT_MERGE_PROMPT four-dimension cross-section audit
framework while preserving the existing output contract, placeholders,
and operations.
"""

from __future__ import annotations

import pytest

from mmap_optimizer.templates.optimizer_prompts import (
    PATCH_ROOT_AUDIT_TEMPLATE,
    DEFAULT_OPTIMIZER_TEMPLATES,
)


@pytest.fixture(scope="module")
def rendered_template() -> str:
    """Render the patch_root_audit template with minimal placeholders."""
    return PATCH_ROOT_AUDIT_TEMPLATE.format(
        prompt_structure="Prompt structure\n## 1. Role\n## 2. Output Format",
        patches_json='[{"op": "append_to_section", "target_section": "1. Role"}]',
    )


# ---------------------------------------------------------------------------
# Template existence / basic sanity
# ---------------------------------------------------------------------------

class TestTemplateExistence:
    def test_template_string_is_non_empty(self) -> None:
        assert isinstance(PATCH_ROOT_AUDIT_TEMPLATE, str)
        assert len(PATCH_ROOT_AUDIT_TEMPLATE) > 0

    def test_render_with_required_placeholders(self, rendered_template: str) -> None:
        assert len(rendered_template) > 0
        assert "{" + "prompt_structure" + "}" not in rendered_template
        assert "{" + "patches_json" + "}" not in rendered_template

    def test_template_only_uses_two_placeholders(self) -> None:
        import string
        fmt = string.Formatter()
        placeholders = [
            field_name
            for _, field_name, _, _ in fmt.parse(PATCH_ROOT_AUDIT_TEMPLATE)
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

    def test_fallback_present(self, rendered_template: str) -> None:
        assert "audited patches" in rendered_template or "[]" in rendered_template

    def test_no_new_required_output_field_introduced(
        self, rendered_template: str
    ) -> None:
        # The contract must not introduce new required top-level fields.
        assert "new required field" not in rendered_template

    def test_no_unsupported_operation_introduced(
        self, rendered_template: str
    ) -> None:
        # Verify the operation set is preserved — no new op name referenced.
        import re
        allowed_ops = {
            "append_to_section",
            "insert_after",
            "insert_before",
            "replace_section",
            "add_after_section",
            "replace_in_section",
            "delete_section",
        }
        op_tokens = re.findall(r"`([a-z_]+)`", rendered_template)
        for token in op_tokens:
            if "_" not in token or len(token) <= 5:
                continue
            if token in {"patches", "op", "target_section", "section_id",
                          "payload", "reasoning", "risk_level",
                          "old_text", "new_text", "extra", "unresolved_locators",
                          "failure_info", "cited_sections"}:
                continue
            if token.startswith("patch_"):
                continue
            assert token in allowed_ops, (
                f"unknown operation-like token referenced: '{token}'"
            )


# ---------------------------------------------------------------------------
# Migrated rule presence tests — the new content from the legacy
# PATCH_ROOT_MERGE_PROMPT must be present in the rendered template.
# ---------------------------------------------------------------------------

class TestMigratedRulePresence:
    def test_cross_section_audit_framework(self, rendered_template: str) -> None:
        assert "Cross-Section Audit Framework" in rendered_template

    def test_audit_dimension_1_rules_output_format(
        self, rendered_template: str
    ) -> None:
        assert "Audit Dimension 1" in rendered_template
        assert "Rules ↔ Output Format consistency" in rendered_template
        assert "Output Format" in rendered_template

    def test_audit_dimension_2_workflow_rules(
        self, rendered_template: str
    ) -> None:
        assert "Audit Dimension 2" in rendered_template
        assert "Workflow ↔ Rules consistency" in rendered_template

    def test_audit_dimension_3_redundancy(
        self, rendered_template: str
    ) -> None:
        assert "Audit Dimension 3" in rendered_template
        assert "Redundancy and duplication" in rendered_template

    def test_audit_dimension_4_orphan_protection(
        self, rendered_template: str
    ) -> None:
        assert "Audit Dimension 4" in rendered_template
        assert "Orphan protection" in rendered_template

    def test_modify_first_never_delete_by_default(
        self, rendered_template: str
    ) -> None:
        assert "Modify-First, Never-Delete-by-Default" in rendered_template
        assert "prefer a minimal modification" in rendered_template

    def test_no_brand_new_patches(self, rendered_template: str) -> None:
        assert "Do not create brand-new patches" in rendered_template
        assert "Do not invent new patch intents" in rendered_template

    def test_unique_valid_patch_preservation(
        self, rendered_template: str
    ) -> None:
        assert "only non-conflicting patch addressing" in rendered_template

    def test_output_format_sensitivity(
        self, rendered_template: str
    ) -> None:
        assert "Output Format changes are high-impact" in rendered_template

    def test_supported_operations_only(
        self, rendered_template: str
    ) -> None:
        assert "Use only the current patch schema and supported operations" in rendered_template

    def test_no_broad_global_rewrite(self, rendered_template: str) -> None:
        assert "Do not convert several localized patches into a broad global rewrite" in rendered_template

    def test_no_hallucinated_requirements(
        self, rendered_template: str
    ) -> None:
        assert "Only audit against the provided prompt structure" in rendered_template

    def test_common_conflict_examples_present(
        self, rendered_template: str
    ) -> None:
        # Cross-section conflict examples — at least one reference to the
        # common conflict patterns.
        assert "Common conflicts" in rendered_template

    def test_migration_note_present(self, rendered_template: str) -> None:
        assert "Migration Note" in rendered_template
        assert "PATCH_ROOT_MERGE_PROMPT" in rendered_template


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_no_optimizer_loop_change(self, rendered_template: str) -> None:
        assert "optimizer loop" not in rendered_template

    def test_no_patch_generation_change(self, rendered_template: str) -> None:
        assert "patch_generation" not in rendered_template
        assert "PATCH_GENERATION_TEMPLATE" not in rendered_template

    def test_no_patch_semantic_merge_change(
        self, rendered_template: str
    ) -> None:
        assert "patch_semantic_merge" not in rendered_template
        assert "PATCH_MERGE_PROMPT" not in rendered_template

    def test_no_schema_new_fields(self, rendered_template: str) -> None:
        # The template must not claim to introduce new schema fields;
        # it should explicitly say no new fields are introduced.
        assert "No new patch operations, required fields" in rendered_template

    def test_no_new_decision_object(self, rendered_template: str) -> None:
        # The template must not introduce new decision objects or shapes.
        # "decision objects" appears only in the negative-requirement text.
        # We check that when the phrase appears, it's in a "do not invent"
        # context.
        import re
        # Find all occurrences of "decision" in the text
        for match in re.finditer(r"decision.{0,80}", rendered_template, re.DOTALL):
            snippet = match.group(0)
            if "objects" in snippet:
                # This should only appear in a negative / prohibition context.
                assert "not" in snippet.lower() or "do not" in snippet.lower() \
                    or "never" in snippet.lower() or "prohibition" in snippet.lower(), (
                    f"'decision objects' appears outside a prohibition: {snippet[:60]}"
                )

    def test_root_audit_is_not_patch_generation(
        self, rendered_template: str
    ) -> None:
        # Root audit remains an audit layer.
        assert "Root audit remains an audit layer, not a patch-generation layer" in rendered_template


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_patch_root_audit_in_registry(self) -> None:
        ids = [spec.id for spec in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "patch_root_audit" in ids

    def test_input_variables_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_root_audit":
                assert set(spec.input_variables) == {
                    "prompt_structure", "patches_json"
                }, f"unexpected inputs: {spec.input_variables}"

    def test_output_contract_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_root_audit":
                contract_type = spec.output_contract.get("type")
                assert contract_type == "json_array", (
                    f"unexpected contract type: {contract_type}"
                )

    def test_version_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_root_audit":
                assert str(spec.version) == "1.1", (
                    f"unexpected version: {spec.version!r}"
                )

    def test_fallback_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_root_audit":
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
        # Stable fingerprint: the generation template must still contain
        # its original prompt optimization expert role declaration.
        assert "你是顶级 Prompt 优化专家" in PATCH_GENERATION_TEMPLATE
        assert "Operation Priority" in PATCH_GENERATION_TEMPLATE
        # Must not have been polluted by cross-section audit terms.
        assert "Audit Dimension" not in PATCH_GENERATION_TEMPLATE
        assert "Orphan protection" not in PATCH_GENERATION_TEMPLATE

    def test_patch_semantic_merge_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_SEMANTIC_MERGE_TEMPLATE,
        )
        # Stable fingerprint: must still contain its role declaration
        # and the conflict-checks / operation-priority sections.
        assert "你是高级 Prompt 策略合并专家" in PATCH_SEMANTIC_MERGE_TEMPLATE
        assert "Conflict Checks" in PATCH_SEMANTIC_MERGE_TEMPLATE
        assert "Operation Priority" in PATCH_SEMANTIC_MERGE_TEMPLATE
        # Must not contain audit dimension headings.
        assert "Audit Dimension" not in PATCH_SEMANTIC_MERGE_TEMPLATE
        assert "Orphan protection" not in PATCH_SEMANTIC_MERGE_TEMPLATE

    def test_patch_translation_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TRANSLATION_TEMPLATE,
        )
        assert "Patch 文本校准专家" in PATCH_TRANSLATION_TEMPLATE
        assert "Audit Dimension" not in PATCH_TRANSLATION_TEMPLATE

    def test_patch_translation_retry_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TRANSLATION_RETRY_TEMPLATE,
        )
        assert "二次校准与故障修复专家" in PATCH_TRANSLATION_RETRY_TEMPLATE
        assert "Audit Dimension" not in PATCH_TRANSLATION_RETRY_TEMPLATE

    def test_patch_text_match_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TEXT_MATCH_TEMPLATE,
        )
        assert "Prompt 文本定位与对齐专家" in PATCH_TEXT_MATCH_TEMPLATE
        assert "Audit Dimension" not in PATCH_TEXT_MATCH_TEMPLATE

    def test_json_fix_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            JSON_FIX_TEMPLATE,
        )
        assert "JSON 数据清洗与结构化修复" in JSON_FIX_TEMPLATE
        assert "Audit Dimension" not in JSON_FIX_TEMPLATE
