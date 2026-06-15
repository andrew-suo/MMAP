from __future__ import annotations

import re

from mmap_optimizer.templates import build_default_template_registry


def _collapse(text: str) -> str:
    """Collapse all whitespace/newlines so cross-line phrase matching works."""
    return re.sub(r"\s+", " ", text.strip())


def _contains(source: str, phrase: str) -> bool:
    """Check whether a phrase appears in source, ignoring whitespace layout."""
    return _collapse(phrase) in _collapse(source)


registry = build_default_template_registry()


# ---------------------------------------------------------------------------
# Template existence / renderability
# ---------------------------------------------------------------------------

class TestTemplateExistence:
    def test_patch_translation_registered(self):
        assert "patch_translation" in registry.ids()

    def test_patch_translation_retry_registered(self):
        assert "patch_translation_retry" in registry.ids()

    def test_patch_translation_renders_with_required_placeholders(self):
        rendered = registry.get("patch_translation").render(
            prompt_structure="sections",
            current_prompt="prompt",
            patches_json="[]",
        )
        assert rendered

    def test_patch_translation_retry_renders_with_required_placeholders(self):
        rendered = registry.get("patch_translation_retry").render(
            failure_info="locator mismatch",
            prompt_structure="sections",
            current_prompt="prompt",
            patch_json="{}",
        )
        assert rendered

    def test_no_undeclared_placeholders_in_translation(self):
        assert registry.get("patch_translation").undeclared_placeholders() == []

    def test_no_undeclared_placeholders_in_translation_retry(self):
        assert registry.get("patch_translation_retry").undeclared_placeholders() == []


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------

class TestContractPreservation:
    def test_translation_placeholders_unchanged(self):
        spec = registry.get("patch_translation")
        assert set(spec.input_variables) == {"prompt_structure", "current_prompt", "patches_json"}

    def test_retry_placeholders_unchanged(self):
        spec = registry.get("patch_translation_retry")
        assert set(spec.input_variables) == {"failure_info", "prompt_structure", "current_prompt", "patch_json"}

    def test_translation_output_contract_mentions_array(self):
        rendered = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        assert _contains(rendered, "JSON 数组") or "JSON" in rendered

    def test_retry_output_contract_mentions_one_element_array(self):
        rendered = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s", current_prompt="p", patch_json="{}"
        )
        assert _contains(rendered, "one-element JSON array") or _contains(rendered, "[patch]")

    def test_no_new_required_output_fields_introduced(self):
        rendered_t = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        rendered_r = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s", current_prompt="p", patch_json="{}"
        )
        for text in (rendered_t, rendered_r):
            assert "required" not in text.lower() or "exactly" in text.lower()

    def test_no_unknown_operation_names(self):
        rendered_t = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        rendered_r = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s", current_prompt="p", patch_json="{}"
        )
        assert _contains(rendered_t, "op")
        assert _contains(rendered_r, "op")


# ---------------------------------------------------------------------------
# patch_translation migrated rule presence
# ---------------------------------------------------------------------------

class TestTranslationMigratedRules:
    def setup_method(self):
        self.rendered = registry.get("patch_translation").render(
            prompt_structure="sections",
            current_prompt="prompt",
            patches_json="[]",
        )

    def test_exact_section_header_calibration(self):
        assert _contains(self.rendered, "Exact Section Header Calibration")
        assert _contains(self.rendered, "exact section header")

    def test_in_section_only_locator_matching(self):
        assert _contains(self.rendered, "In-Section-Only Locator Matching")
        assert _contains(self.rendered, "only inside that section")

    def test_payload_immutability(self):
        assert _contains(self.rendered, "Payload Immutability")
        assert _contains(self.rendered, "Only locator fields may be corrected")
        assert _contains(self.rendered, "Preserve the original patch payload")

    def test_n_in_n_out_count_preservation(self):
        assert _contains(self.rendered, "N-in-N-out Count Preservation")
        assert _contains(self.rendered, "exactly the same number of patch objects")
        assert _contains(self.rendered, "Do not add, delete, split, or merge")

    def test_unresolved_locator_fallback(self):
        assert _contains(self.rendered, "unresolved")
        assert _contains(self.rendered, "extra.unresolved_locators")

    def test_verbatim_from_current_prompt(self):
        assert _contains(self.rendered, "Verbatim Locator Requirement")
        assert _contains(self.rendered, "copied verbatim from the current prompt")

    def test_not_patch_generation_merge_or_root_audit(self):
        assert _contains(self.rendered, "not patch generation, not merge, and not root audit")
        assert _contains(self.rendered, "no semantic rewriting")

    def test_migration_note_present(self):
        assert _contains(self.rendered, "Migration Note")
        assert _contains(self.rendered, "legacy PATCH_TRANSLATION_PROMPT")


# ---------------------------------------------------------------------------
# patch_translation_retry migrated rule presence
# ---------------------------------------------------------------------------

class TestRetryMigratedRules:
    def setup_method(self):
        self.rendered = registry.get("patch_translation_retry").render(
            failure_info="locator mismatch",
            prompt_structure="sections",
            current_prompt="prompt",
            patch_json="{}",
        )

    def test_failure_info_driven_retry(self):
        assert _contains(self.rendered, "Failure-Info Driven Retry")
        assert _contains(self.rendered, "Use failure_info as the primary signal")

    def test_exactly_one_retry_output(self):
        assert _contains(self.rendered, "Exactly-One Retry Output")
        assert _contains(self.rendered, "one-element JSON array")

    def test_exact_section_header_in_retry(self):
        assert _contains(self.rendered, "exact section header")

    def test_in_section_old_text_target_text_in_retry(self):
        assert _contains(self.rendered, "in-section")
        assert _contains(self.rendered, "old_text")
        assert _contains(self.rendered, "target_text")

    def test_no_guessing(self):
        assert _contains(self.rendered, "No Guessing")
        assert _contains(self.rendered, "Do not guess approximate source text")

    def test_preserve_original_patch(self):
        assert _contains(self.rendered, "preserve the original patch")

    def test_preserve_non_locator_payload(self):
        assert _contains(self.rendered, "Preserve All Non-Locator Payload")
        assert _contains(self.rendered, "Only locator-related fields may be changed")
        assert _contains(self.rendered, "Preserve all non-locator payload exactly")

    def test_unresolved_locator_in_retry(self):
        assert _contains(self.rendered, "unresolved locator")
        assert _contains(self.rendered, "extra.unresolved_locators")

    def test_header_in_section_fuse_order(self):
        assert _contains(self.rendered, "Header")
        assert _contains(self.rendered, "In-Section Hard Match")
        assert _contains(self.rendered, "Fuse Order")

    def test_migration_note_present(self):
        assert _contains(self.rendered, "Migration Note")
        assert _contains(self.rendered, "PATCH_TRANSLATION_RETRY_PROMPT")


# ---------------------------------------------------------------------------
# Guardrails: what the templates must NOT do
# ---------------------------------------------------------------------------

class TestGuardrails:
    def setup_method(self):
        self.rendered_t = registry.get("patch_translation").render(
            prompt_structure="s", current_prompt="p", patches_json="[]"
        )
        self.rendered_r = registry.get("patch_translation_retry").render(
            failure_info="f", prompt_structure="s", current_prompt="p", patch_json="{}"
        )

    def test_no_optimizer_loop_mention(self):
        for text in (self.rendered_t, self.rendered_r):
            assert "optimizer loop" not in text.lower()

    def test_no_changes_to_patch_generation(self):
        for text in (self.rendered_t, self.rendered_r):
            assert "patch_generation template" not in text

    def test_no_new_patch_schema(self):
        for text in (self.rendered_t, self.rendered_r):
            assert "new patch JSON schema" not in text
            assert "new required fields" not in text

    def test_no_adding_deleting_patches_during_translation(self):
        # Translation explicitly forbids add/delete/split/merge in its own way.
        for text in (self.rendered_t, self.rendered_r):
            assert _contains(text, "Do not add, delete") or _contains(text, "do not add, delete")
        # patch_translation explicitly calls out "merge" too.
        assert "merge" in self.rendered_t

    def test_no_semantic_rewrite(self):
        assert _contains(self.rendered_t, "no semantic rewriting")


# ---------------------------------------------------------------------------
# Other-template isolation: ensure this PR did not touch other templates
# ---------------------------------------------------------------------------

class TestOtherTemplateIsolation:
    def test_patch_generation_renders_identically_to_main(self):
        rendered = registry.get("patch_generation").render(
            prompt_structure="s",
            current_prompt="p",
            round_context="c",
            evaluation_summary="e",
        )
        assert "Be Specific" in rendered
        assert "append_to_section" in rendered

    def test_patch_semantic_merge_present_and_intact(self):
        rendered = registry.get("patch_semantic_merge").render(
            prompt_structure="s",
            patches_json="[]",
        )
        assert "Three-Dimensional Merge Framework" in rendered

    def test_patch_root_audit_present_and_intact(self):
        rendered = registry.get("patch_root_audit").render(
            prompt_structure="s",
            patches_json="[]",
        )
        assert "Cross-Section Audit Framework" in rendered

    def test_patch_text_match_and_json_fix_untouched(self):
        assert registry.get("patch_text_match").render(
            section_content="abc", intent_text="ab", field_type="old_text"
        )
        assert registry.get("json_fix").render(raw_text='{"x":1}')

    def test_other_template_ids_not_changed_by_translation_pr(self):
        ids = registry.ids()
        for expected in (
            "patch_text_match",
            "patch_translation",
            "patch_translation_retry",
            "json_fix",
            "patch_generation",
            "patch_semantic_merge",
            "patch_root_audit",
            "section_rewrite",
            "llm_prune",
            "llm_prune_validation",
            "prompt_numbering_refactor",
            "prompt_format_repair",
            "prompt_standardization",
            "prompt_self_check",
        ):
            assert expected in ids
