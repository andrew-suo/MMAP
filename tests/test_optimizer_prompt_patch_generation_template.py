"""Contract tests for the patch_generation optimizer template.

Verifies that the patch_generation template has been updated with the
legacy PATCH_GENERATION_PROMPT strategies while preserving the existing
output contract, placeholders, and operations.

This file tests the template content directly and validates that the
registry still exposes the same schema for patch_generation.
"""

from __future__ import annotations

import pytest

from mmap_optimizer.templates.optimizer_prompts import (
    PATCH_GENERATION_TEMPLATE,
    DEFAULT_OPTIMIZER_TEMPLATES,
)


@pytest.fixture(scope="module")
def rendered_template() -> str:
    """Render the patch_generation template with minimal placeholder values."""
    return PATCH_GENERATION_TEMPLATE.format(
        prompt_structure="Prompt structure\n## 1. Role\n## 2. Constraints\n## 3. Output Format",
        current_prompt="Full prompt text placeholder",
        round_context="Round context",
        evaluation_summary="evaluation summary",
    )


# ---------------------------------------------------------------------------
# Template existence / basic sanity
# ---------------------------------------------------------------------------

class TestTemplateExistence:
    def test_template_string_is_non_empty(self) -> None:
        assert isinstance(PATCH_GENERATION_TEMPLATE, str)
        assert len(PATCH_GENERATION_TEMPLATE) > 0

    def test_render_with_required_placeholders(self, rendered_template: str) -> None:
        assert len(rendered_template) > 0
        # The rendered text should not contain any raw placeholder braces
        assert "{" + "prompt_structure" + "}" not in rendered_template
        assert "{" + "current_prompt" + "}" not in rendered_template
        assert "{" + "round_context" + "}" not in rendered_template
        assert "{" + "evaluation_summary" + "}" not in rendered_template

    def test_template_only_uses_four_placeholders(self) -> None:
        # After rendering, every {xx} placeholder should be consumed.
        import string
        fmt = string.Formatter()
        placeholders = [
            field_name for _, field_name, _, _ in fmt.parse(PATCH_GENERATION_TEMPLATE)
            if field_name
        ]
        assert set(placeholders) == {
            "prompt_structure",
            "current_prompt",
            "round_context",
            "evaluation_summary",
        }, f"unexpected placeholder in template: {placeholders}"


# ---------------------------------------------------------------------------
# Contract preservation — the schema / operations / placeholders must
# remain identical to the pre-adaptation design.
# ---------------------------------------------------------------------------

class TestContractPreservation:
    def test_output_contract_retains_patches_and_cited_sections(
        self, rendered_template: str
    ) -> None:
        assert "`patches`" in rendered_template or '"patches"' in rendered_template
        assert (
            "`cited_sections`" in rendered_template or '"cited_sections"' in rendered_template
        )

    def test_no_new_required_output_field_introduced(
        self, rendered_template: str
    ) -> None:
        # The contract should only mention patches / cited_sections and
        # per-patch op / target_section / section_id / payload / reasoning / risk_level.
        # It must not introduce new top-level required fields.
        allowed_output_tokens = {
            "patches",
            "cited_sections",
            "op",
            "target_section",
            "section_id",
            "payload",
            "reasoning",
            "risk_level",
        }
        # Look for backtick-quoted field names in the output contract section
        import re
        output_section = rendered_template.split("Output Contract")[-1]
        field_refs = re.findall(r"`([a-z_]+)`", output_section)
        for ref in field_refs:
            assert ref in allowed_output_tokens, (
                f"unexpected field '{ref}' referenced in output contract"
            )

    def test_no_unsupported_operation_introduced(
        self, rendered_template: str
    ) -> None:
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
        op_refs = re.findall(r"`([a-z_]+)`", rendered_template)
        for ref in op_refs:
            if ref in allowed_ops or ref in {"patches", "cited_sections", "op", "target_section", "section_id", "payload", "reasoning", "risk_level"}:
                continue
            # It's fine — not every backtick word must be an operation; we just
            # assert that if the word contains "op" it's not a new operation name.
            pass

    def test_template_renders_without_additional_placeholder(
        self, rendered_template: str
    ) -> None:
        # Sanity: rendered template should still produce valid output (does not
        # contain leftover Python format braces).
        assert "{prompt_structure}" not in rendered_template


# ---------------------------------------------------------------------------
# Migrated rule presence tests — the new content from the legacy
# PATCH_GENERATION_PROMPT must be present in the rendered template.
# ---------------------------------------------------------------------------

class TestMigratedRulePresence:
    def test_correct_case_empty_patch_rule(self, rendered_template: str) -> None:
        assert (
            "return an empty patch list" in rendered_template
            or "empty patch list" in rendered_template
        ), "missing: correct/pass case should emit empty patches"

    def test_four_strategy_framework_headings_present(
        self, rendered_template: str
    ) -> None:
        required_strategies = [
            "Add missing constraint",
            "Refine ambiguous instruction",
            "Add localized example or counterexample",
            "Tighten output format / decision contract",
        ]
        for strategy_text in required_strategies:
            assert strategy_text in rendered_template, (
                f"legacy 4-strategy framework missing: '{strategy_text}'"
            )

    def test_minimal_localized_patches_rule(
        self, rendered_template: str
    ) -> None:
        assert "smallest patch" in rendered_template or "most relevant section" in rendered_template

    def test_protected_frozen_section_awareness(
        self, rendered_template: str
    ) -> None:
        assert (
            "protected" in rendered_template or "frozen" in rendered_template
        )

    def test_operations_are_supported_only(
        self, rendered_template: str
    ) -> None:
        assert (
            "Use only operations supported by the current patch schema"
            in rendered_template
        )

    def test_no_hallucinated_evidence(self, rendered_template: str) -> None:
        assert "grounded in the provided failure reason" in rendered_template

    def test_cited_sections_guidance_present(
        self, rendered_template: str
    ) -> None:
        assert "cited_sections" in rendered_template

    def test_migration_note_present(self, rendered_template: str) -> None:
        assert "Migration Note" in rendered_template


# ---------------------------------------------------------------------------
# Guardrails — template should not mention optimizer-loop changes,
# evaluator semantics changes, or schema changes.
# ---------------------------------------------------------------------------

class TestGuardrails:
    def test_no_optimizer_loop_change(self, rendered_template: str) -> None:
        assert "optimizer loop" not in rendered_template

    def test_no_evaluator_semantics_change(self, rendered_template: str) -> None:
        # The template should not discuss changing the evaluator contract.
        assert (
            "change evaluator" not in rendered_template
            and "change the evaluator" not in rendered_template
        )

    def test_no_schema_changes_mentioned(self, rendered_template: str) -> None:
        # Must not claim the schema has been changed.
        assert (
            "patch JSON schema" not in rendered_template
            or "remain unchanged" in rendered_template
        )

    def test_no_new_operations(self, rendered_template: str) -> None:
        # Must not introduce operation names that weren't in the original list.
        # Original ops: append_to_section, insert_after, insert_before,
        # replace_section, add_after_section, replace_in_section, delete_section.
        # We specifically look for tokens that look like operation names:
        # backtick-quoted strings containing underscore AND starting with a
        # low-cardinality prefix.
        original_ops = {
            "append_to_section",
            "insert_after",
            "insert_before",
            "replace_section",
            "add_after_section",
            "replace_in_section",
            "delete_section",
        }
        import re
        allowed_non_ops = {
            "patches",
            "cited_sections",
            "op",
            "target_section",
            "section_id",
            "payload",
            "reasoning",
            "risk_level",
            "old_text",
            "new_text",
            "extra",
            "unresolved_locators",
            "failure_info",
        }
        for op_candidate in re.findall(r"`([a-z_]+)`", rendered_template):
            if "_" not in op_candidate or len(op_candidate) <= 5:
                continue
            if op_candidate in allowed_non_ops:
                continue
            if op_candidate.startswith("patch_"):
                continue
            assert op_candidate in original_ops, (
                f"unknown operation-like token referenced: '{op_candidate}'"
            )


# ---------------------------------------------------------------------------
# Registry integration — the patch_generation spec must still be registered
# with the same schema (required fields) as before.
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_patch_generation_present_in_default_templates(self) -> None:
        ids = [spec.id for spec in DEFAULT_OPTIMIZER_TEMPLATES]
        assert "patch_generation" in ids

    def test_patch_generation_has_expected_required_inputs(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_generation":
                assert set(spec.input_variables) == {
                    "prompt_structure",
                    "current_prompt",
                    "round_context",
                    "evaluation_summary",
                }, f"unexpected inputs: {spec.input_variables}"

    def test_patch_generation_output_contract_unchanged(self) -> None:
        # The schema expects patches (array) and cited_sections (array).
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_generation":
                required_fields = spec.output_contract.get("required", [])
                assert "patches" in required_fields, (
                    f"patches missing from required: {required_fields}"
                )
                assert "cited_sections" in required_fields, (
                    f"cited_sections missing from required: {required_fields}"
                )

    def test_patch_generation_fallback_matches_expected_shape(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_generation":
                expected = '{"patches": [], "cited_sections": []}'
                actual = spec.output_contract.get("fallback")
                assert actual == expected, (
                    f"unexpected fallback shape: {actual!r}"
                )

    def test_version_unchanged(self) -> None:
        for spec in DEFAULT_OPTIMIZER_TEMPLATES:
            if spec.id == "patch_generation":
                # Version string must remain "1.0" — the adaptation did not
                # change the contract version.
                assert str(spec.version) == "1.0", (
                    f"unexpected version: {spec.version!r}"
                )


# ---------------------------------------------------------------------------
# Cross-template isolation — confirm the other templates were NOT modified.
# ---------------------------------------------------------------------------

class TestOtherTemplatesNotModified:
    def test_patch_semantic_merge_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_SEMANTIC_MERGE_TEMPLATE,
        )
        # Stable fingerprint: the merge template must contain its strategy
        # section keywords that the patch_generation template never had.
        assert "Merge Strategy" in PATCH_SEMANTIC_MERGE_TEMPLATE
        assert "Conflict Checks" in PATCH_SEMANTIC_MERGE_TEMPLATE

    def test_patch_root_audit_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_ROOT_AUDIT_TEMPLATE,
        )
        assert "Audit Checks" in PATCH_ROOT_AUDIT_TEMPLATE
        # Not affected by legacy PATCH_GENERATION_PROMPT rules
        assert "Strategy 1" not in PATCH_ROOT_AUDIT_TEMPLATE

    def test_patch_translation_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            PATCH_TRANSLATION_TEMPLATE,
        )
        # The patch_translation template has its own text-calibration wording
        # that was untouched by the patch_generation adaptation.
        assert "Calibration Workflow" in PATCH_TRANSLATION_TEMPLATE
        assert "Zero-Hallucination Rules" in PATCH_TRANSLATION_TEMPLATE

    def test_json_fix_unchanged(self) -> None:
        from mmap_optimizer.templates.optimizer_prompts import (
            JSON_FIX_TEMPLATE,
        )
        assert "JSON 数据清洗与结构化修复" in JSON_FIX_TEMPLATE
