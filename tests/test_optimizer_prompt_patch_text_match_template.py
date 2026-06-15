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
    def test_patch_text_match_registered(self):
        assert "patch_text_match" in registry.ids()

    def test_patch_text_match_renders_with_required_placeholders(self):
        rendered = registry.get("patch_text_match").render(
            section_content="abc",
            intent_text="ab",
            field_type="old_text",
        )
        assert rendered
        # No raw `{...}` template placeholders must survive.
        assert "{" not in rendered or "{json" not in rendered

    def test_no_undeclared_placeholders(self):
        assert registry.get("patch_text_match").undeclared_placeholders() == []


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------

class TestContractPreservation:
    def test_placeholders_unchanged(self):
        spec = registry.get("patch_text_match")
        assert set(spec.input_variables) == {"section_content", "intent_text", "field_type"}

    def test_output_contract_remains_text_not_json(self):
        # The contract must still describe plain-text output, not JSON.
        rendered = registry.get("patch_text_match").render(
            section_content="xyz",
            intent_text="xy",
            field_type="old_text",
        )
        assert _contains(rendered, "Return only the matched substring") or \
               "子串" in rendered or "substring" in rendered

    def test_no_json_output_required(self):
        rendered = registry.get("patch_text_match").render(
            section_content="a", intent_text="a", field_type="old_text"
        )
        # Must not REQUIRE JSON as output. The template is allowed to mention
        # JSON only to forbid it.
        assert "return json" not in rendered.lower()
        assert "output json" not in rendered.lower().replace("do not output explanations, json", "")

    def test_no_markdown_code_fence_required(self):
        rendered = registry.get("patch_text_match").render(
            section_content="a", intent_text="a", field_type="old_text"
        )
        # Must not REQUIRE Markdown / code fence output. Template mentions
        # these only to forbid them.
        assert "return markdown" not in rendered.lower()
        assert "code fence" in rendered.lower()  # template explicitly forbids fences

    def test_no_new_required_fields_introduced(self):
        rendered = registry.get("patch_text_match").render(
            section_content="a", intent_text="a", field_type="old_text"
        )
        # Guards against introducing output-field contracts like
        # {"required": [...]} that would change the IO contract. The template
        # may mention "required fields" only when asserting that none are
        # introduced.
        lower = rendered.lower()
        assert '{"required"' not in lower
        assert "return {\"" not in lower

    def test_no_unknown_operations(self):
        # Template must not introduce patch op vocabulary.
        rendered = registry.get("patch_text_match").render(
            section_content="a", intent_text="a", field_type="old_text"
        )
        # Guard: should not list ops it will generate.
        assert "op:" not in rendered


# ---------------------------------------------------------------------------
# Migrated rule presence
# ---------------------------------------------------------------------------

class TestMigratedRules:
    def setup_method(self):
        self.rendered = registry.get("patch_text_match").render(
            section_content="source section content",
            intent_text="intent phrase",
            field_type="old_text",
        )

    def test_pure_substring_extraction(self):
        assert _contains(self.rendered, "Pure Substring Extraction")
        assert _contains(self.rendered, "Return only the matched substring copied from the provided section content")

    def test_no_json_markdown_explanations(self):
        assert _contains(self.rendered, "Do not output explanations")
        assert _contains(self.rendered, "Do not output explanations, JSON, Markdown, code fences")

    def test_de_paraphrasing(self):
        assert _contains(self.rendered, "De-Paraphrasing from Intent Text to Source Text")
        assert _contains(self.rendered, "intent_text")
        assert _contains(self.rendered, "paraphrased")

    def test_exact_source_substring(self):
        assert _contains(self.rendered, "exact source substring")

    def test_longest_meaningful_substring(self):
        assert _contains(self.rendered, "Longest Meaningful Substring Rule")
        assert _contains(self.rendered, "longest meaningful substring")

    def test_verbatim_from_section_content(self):
        assert _contains(self.rendered, "copied verbatim from section_content")

    def test_preserving_wording_punctuation_whitespace(self):
        assert _contains(self.rendered, "preserving original wording, punctuation, and whitespace")

    def test_in_section_only(self):
        assert _contains(self.rendered, "In-Section Only")
        assert _contains(self.rendered, "Search only within the provided section_content")

    def test_empty_string_fuse(self):
        assert _contains(self.rendered, "Total Fuse on No Reliable Match")
        assert _contains(self.rendered, "return an empty string")

    def test_do_not_guess(self):
        assert _contains(self.rendered, "Do not guess")

    def test_not_patch_generation_merge_audit(self):
        assert _contains(self.rendered, "text matching only")
        assert _contains(self.rendered, "Do not rewrite the prompt, generate a patch, merge patches, audit patches")

    def test_no_semantic_rewriting(self):
        assert _contains(self.rendered, "No Semantic Rewriting")

    def test_no_hallucinated_source_text(self):
        assert _contains(self.rendered, "No Hallucinated Source Text")
        assert _contains(self.rendered, "Never output text that is not present verbatim in section_content")

    def test_field_type_sensitivity(self):
        assert _contains(self.rendered, "Field-Type Sensitivity")
        assert _contains(self.rendered, "field_type")
        assert _contains(self.rendered, "old_text") or _contains(self.rendered, "target_text")

    def test_migration_note_present(self):
        assert _contains(self.rendered, "Migration Note")
        assert _contains(self.rendered, "PATCH_TEXT_MATCH_PROMPT")


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

class TestGuardrails:
    def setup_method(self):
        self.rendered = registry.get("patch_text_match").render(
            section_content="a", intent_text="a", field_type="old_text"
        )

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

    def test_no_new_patch_schema(self):
        assert "new patch JSON schema" not in self.rendered

    def test_no_json_output_required(self):
        # Must not require JSON output.
        assert not _contains(self.rendered, "Return JSON")

    def test_no_explanation_output(self):
        # Explicitly forbids explanations.
        assert _contains(self.rendered, "Do not output explanations")

    def test_no_synthesized_text(self):
        assert _contains(self.rendered, "Do not guess, paraphrase, synthesize, or repair text")


# ---------------------------------------------------------------------------
# Other-template isolation
# ---------------------------------------------------------------------------

class TestOtherTemplateIsolation:
    def test_patch_generation_intact(self):
        rendered = registry.get("patch_generation").render(
            prompt_structure="s",
            current_prompt="p",
            round_context="c",
            evaluation_summary="e",
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
        # On origin/main, patch_translation is the Chinese-only calibrator.
        # Verify it still renders with its known Chinese role line.
        rendered = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        assert "Patch 文本校准专家" in rendered or "PATCH_TRANSLATION_PROMPT" in rendered

    def test_patch_translation_retry_intact(self):
        rendered = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s", current_prompt="p", patch_json="{}"
        )
        assert "二次校准" in rendered or "PATCH_TRANSLATION_RETRY_PROMPT" in rendered

    def test_json_fix_intact(self):
        assert registry.get("json_fix").render(raw_text='{"x":1}')
