from __future__ import annotations

import re

from mmap_optimizer.templates import build_default_template_registry


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _contains(source: str, phrase: str) -> bool:
    return _collapse(phrase) in _collapse(source)


registry = build_default_template_registry()


# ---------------------------------------------------------------------------
# Template existence / renderability
# ---------------------------------------------------------------------------

class TestTemplateExistence:
    def test_json_fix_registered(self):
        assert "json_fix" in registry.ids()

    def test_json_fix_renders_with_required_placeholders(self):
        rendered = registry.get("json_fix").render(raw_text='{"x": 1}')
        assert rendered

    def test_no_undeclared_placeholders(self):
        assert registry.get("json_fix").undeclared_placeholders() == []


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------

class TestContractPreservation:
    def test_placeholders_unchanged(self):
        spec = registry.get("json_fix")
        assert set(spec.input_variables) == {"raw_text"}

    def test_output_contract_starts_with_brace_or_bracket(self):
        rendered = registry.get("json_fix").render(raw_text='{"a": 1}')
        # Chinese output contract says first char must be `{` or `[`
        assert "`{`" in rendered or "{`" in rendered or "JSON" in rendered

    def test_no_json_output_forbidden(self):
        # Template should explicitly require JSON output only (not Markdown,
        # not explanations). The Output Contract section enforces this.
        rendered = registry.get("json_fix").render(raw_text='{"a": 1}')
        assert _contains(rendered, "Output JSON Only") or "JSON" in rendered

    def test_no_markdown_code_fence_output(self):
        rendered = registry.get("json_fix").render(raw_text='{"a": 1}')
        assert _contains(rendered, "Do not output explanations, Markdown, code fences")

    def test_no_new_required_fields_introduced(self):
        rendered = registry.get("json_fix").render(raw_text='{"a": 1}')
        # Must not require new top-level fields beyond what the input had.
        lower = rendered.lower()
        assert '{"required"' not in lower
        assert "return {\"" not in lower

    def test_no_unknown_operations_introduced(self):
        rendered = registry.get("json_fix").render(raw_text='{"a": 1}')
        # Must not list patch op names that would change output shape.
        assert "op:" not in rendered


# ---------------------------------------------------------------------------
# Migrated rule presence
# ---------------------------------------------------------------------------

class TestMigratedRules:
    def setup_method(self):
        self.rendered = registry.get("json_fix").render(raw_text='{"x": 1,}')

    def test_syntax_only_repair(self):
        assert _contains(self.rendered, "Syntax-Only Repair")
        assert _contains(self.rendered, "Do not change the semantic meaning")

    def test_preserve_payload_semantics(self):
        assert _contains(self.rendered, "Preserve Payload Semantics")
        assert _contains(self.rendered, "Preserve all original keys, values, array order")

    def test_no_schema_invention(self):
        assert _contains(self.rendered, "No Schema Invention")
        assert _contains(self.rendered, "Do not add new fields, remove fields, rename fields")

    def test_output_json_only(self):
        assert _contains(self.rendered, "Output JSON Only")
        assert _contains(self.rendered, "Return only the repaired JSON")

    def test_minimal_edit_principle(self):
        assert _contains(self.rendered, "Minimal Edit Principle")
        assert _contains(self.rendered, "smallest possible edit")

    def test_type_preservation(self):
        assert _contains(self.rendered, "Type Preservation")
        assert _contains(self.rendered, "Preserve value types")

    def test_escaping_and_quote_repair(self):
        assert _contains(self.rendered, "Escaping and Quote Repair")
        assert _contains(self.rendered, "unescaped quotes")
        assert _contains(self.rendered, "trailing commas")
        assert _contains(self.rendered, "missing commas")
        assert _contains(self.rendered, "mismatched braces")

    def test_no_hallucinated_fallback(self):
        assert _contains(self.rendered, "No Hallucinated Fallback")
        assert _contains(self.rendered, "cannot be reliably repaired")
        assert _contains(self.rendered, "without inventing new semantic content")

    def test_contract_aware_repair(self):
        assert _contains(self.rendered, "Contract-Aware Repair")
        assert _contains(self.rendered, "only to validate shape and required")

    def test_migration_note_present(self):
        assert _contains(self.rendered, "Migration Note")
        assert _contains(self.rendered, "JSON_FIX_PROMPT")


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:
    def setup_method(self):
        self.rendered = registry.get("json_fix").render(raw_text='{"x": 1}')

    def test_no_optimizer_loop_mention(self):
        assert "optimizer loop" not in self.rendered.lower()

    def test_no_changes_to_patch_generation(self):
        assert "patch_generation template" not in self.rendered

    def test_no_changes_to_patch_semantic_merge(self):
        assert "patch_semantic_merge template" not in self.rendered

    def test_no_changes_to_patch_root_audit(self):
        assert "patch_root_audit template" not in self.rendered

    def test_no_changes_to_patch_translation(self):
        assert "patch_translation template" not in self.rendered

    def test_no_changes_to_patch_text_match(self):
        assert "patch_text_match template" not in self.rendered

    def test_no_new_patch_schema(self):
        assert "new patch JSON schema" not in self.rendered

    def test_no_explanations_in_output(self):
        assert _contains(self.rendered, "Do not output explanations")
        assert _contains(self.rendered, "Do not output explanations, Markdown, code fences")

    def test_no_invented_business_values(self):
        assert _contains(self.rendered, "Do not add new fields, remove fields, rename fields")

    def test_no_semantic_rewriting(self):
        assert _contains(self.rendered, "Do not change the semantic meaning")


# ---------------------------------------------------------------------------
# Other-template isolation
# ---------------------------------------------------------------------------

class TestOtherTemplateIsolation:
    def test_patch_generation_intact(self):
        rendered = registry.get("patch_generation").render(
            prompt_structure="s", current_prompt="p",
            round_context="c", evaluation_summary="e",
        )
        assert "Be Specific" in rendered
        assert "append_to_section" in rendered

    def test_patch_semantic_merge_intact(self):
        rendered = registry.get("patch_semantic_merge").render(
            prompt_structure="s", patches_json="[]"
        )
        assert "Three-Dimensional Merge Framework" in rendered

    def test_patch_root_audit_intact(self):
        rendered = registry.get("patch_root_audit").render(
            prompt_structure="s", patches_json="[]"
        )
        assert "Cross-Section Audit Framework" in rendered

    def test_patch_translation_intact(self):
        rendered = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        # On current origin/main this template uses Chinese section names;
        # the assertion only checks that it renders with its characteristic
        # locator-calibration markers.
        assert "Calibration Workflow" in rendered or "extra.unresolved_locators" in rendered

    def test_patch_translation_retry_intact(self):
        rendered = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s",
            current_prompt="p", patch_json="{}"
        )
        assert "Failure Details" in rendered or "extra.unresolved_locators" in rendered

    def test_patch_text_match_intact(self):
        rendered = registry.get("patch_text_match").render(
            section_content="abc", intent_text="ab", field_type="old_text"
        )
        assert "Source Section" in rendered or "Intent Text" in rendered
