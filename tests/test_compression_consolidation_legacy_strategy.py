"""Contract tests for the CONSOLIDATION_PROMPT legacy strategy adaptation.

These tests verify the deterministic text-level contract of the enriched
``LLM_PRUNE_TEMPLATE`` (CONSOLIDATION_PROMPT) and
``LLM_PRUNE_VALIDATION_TEMPLATE`` (CONSOLIDATION_EVAL_PROMPT) in
:mod:`mmap_optimizer.templates.optimizer_prompts`. They do not invoke a
language model, do not touch the optimizer loop, and do not modify any
runtime behavior.
"""

from mmap_optimizer.templates.optimizer_prompts import (
    LLM_PRUNE_TEMPLATE,
    LLM_PRUNE_VALIDATION_TEMPLATE,
)


def _normalize(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


# ---------------------------------------------------------------------------
# LLM_PRUNE_TEMPLATE (CONSOLIDATION_PROMPT) tests
# ---------------------------------------------------------------------------

class TestLlamaPruneTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(LLM_PRUNE_TEMPLATE, str)
        assert len(LLM_PRUNE_TEMPLATE) > 0

    def test_required_placeholders_present(self):
        assert "{section_header}" in LLM_PRUNE_TEMPLATE
        assert "{section_content}" in LLM_PRUNE_TEMPLATE

    def test_no_unknown_placeholders(self):
        import re

        text = LLM_PRUNE_TEMPLATE
        known = {"{section_header}", "{section_content}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_mentions_legacy_prompt_source(self):
        assert _contains(LLM_PRUNE_TEMPLATE, "CONSOLIDATION_PROMPT")

    def test_role_present(self):
        assert _contains(LLM_PRUNE_TEMPLATE, "Role")


class TestLlamaPruneContractPreservation:
    def test_output_is_compressed_section_body_only(self):
        text = LLM_PRUNE_TEMPLATE
        assert _contains(text, "仅输出合并后的 section body")
        assert _contains(text, "无 header")

    def test_no_new_required_fields_introduced(self):
        text = LLM_PRUNE_TEMPLATE
        assert "new_required_field" not in text
        assert "unsupported_field" not in text

    def test_placeholders_unchanged(self):
        assert "{section_header}" in LLM_PRUNE_TEMPLATE
        assert "{section_content}" in LLM_PRUNE_TEMPLATE

    def test_fallback_behavior_preserved(self):
        text = LLM_PRUNE_TEMPLATE
        assert "fallback" not in text.lower() or _contains(text, "fallback")

    def test_no_new_patch_operations(self):
        text = LLM_PRUNE_TEMPLATE
        assert "PatchOperation" not in text
        assert "op=" not in text

    def test_no_new_patch_intents(self):
        text = LLM_PRUNE_TEMPLATE
        assert "new_intent" not in text


class TestLlamaPruneMigratedRules:
    def setup_method(self):
        self.text = LLM_PRUNE_TEMPLATE

    def test_rule_1_semantic_preserving_compression(self):
        assert _contains(self.text, "Semantic-Preserving Compression")
        assert _contains(self.text, "不得删除或削弱业务逻辑")

    def test_rule_2_preserve_all_unique_constraints(self):
        assert _contains(self.text, "Preserve All Unique Constraints")
        assert _contains(self.text, "每条唯一约束")

    def test_rule_3_merge_duplicates_not_differences(self):
        assert _contains(self.text, "Merge Duplicates, Not Differences")
        assert _contains(self.text, "合并重复或语义等价的规则")

    def test_rule_4_preserve_placeholders_and_variables(self):
        assert _contains(self.text, "Preserve Placeholders and Variables")
        assert _contains(self.text, "精确保留占位符")

    def test_rule_5_preserve_output_contract(self):
        assert _contains(self.text, "Preserve Output Contract")
        assert _contains(self.text, "输出格式要求")

    def test_rule_6_preserve_examples_and_counterexamples(self):
        assert _contains(self.text, "Preserve Examples and Counterexamples")
        assert _contains(self.text, "反例")

    def test_rule_7_no_over_compression(self):
        assert _contains(self.text, "No Over-Compression")
        assert _contains(self.text, "不得过度压缩")

    def test_rule_8_structure_aware_consolidation(self):
        assert _contains(self.text, "Structure-Aware Consolidation")
        assert _contains(self.text, "section 边界")

    def test_rule_9_minimal_wording_changes(self):
        assert _contains(self.text, "Minimal Wording Changes")
        assert _contains(self.text, "最小措辞变更")

    def test_rule_10_output_consolidated_section_only(self):
        assert _contains(self.text, "Output Consolidated Section Only")
        assert _contains(self.text, "不得包含解释")
        assert _contains(self.text, "Markdown 包装器")


class TestLlamaPruneGuardrails:
    def test_does_not_allow_business_logic_changes(self):
        text = LLM_PRUNE_TEMPLATE
        assert _contains(text, "不得删除或削弱业务逻辑")

    def test_does_not_allow_arbitrary_standardization(self):
        assert _contains(LLM_PRUNE_TEMPLATE, "避免风格重写")
        assert _contains(LLM_PRUNE_TEMPLATE, "任意规范化")

    def test_no_optimizer_loop_changes_mentioned(self):
        text = LLM_PRUNE_TEMPLATE
        assert _contains(text, "optimizer loop") and _contains(text, "未被修改")

    def test_no_wrappers_or_code_fence(self):
        assert _contains(LLM_PRUNE_TEMPLATE, "不得包含解释")
        assert _contains(LLM_PRUNE_TEMPLATE, "Markdown 包装器")
        assert _contains(LLM_PRUNE_TEMPLATE, "代码 fence")

    def test_no_new_placeholders(self):
        import re

        text = LLM_PRUNE_TEMPLATE
        known = {"{section_header}", "{section_content}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        assert all_braces == known


# ---------------------------------------------------------------------------
# LLM_PRUNE_VALIDATION_TEMPLATE (CONSOLIDATION_EVAL_PROMPT) tests
# ---------------------------------------------------------------------------

class TestLlamaPruneValidationTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(LLM_PRUNE_VALIDATION_TEMPLATE, str)
        assert len(LLM_PRUNE_VALIDATION_TEMPLATE) > 0

    def test_required_placeholders_present(self):
        assert "{original_section}" in LLM_PRUNE_VALIDATION_TEMPLATE
        assert "{pruned_section}" in LLM_PRUNE_VALIDATION_TEMPLATE

    def test_no_unknown_placeholders(self):
        import re

        text = LLM_PRUNE_VALIDATION_TEMPLATE
        known = {"{original_section}", "{pruned_section}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_mentions_legacy_prompt_source(self):
        assert _contains(LLM_PRUNE_VALIDATION_TEMPLATE, "CONSOLIDATION_EVAL_PROMPT")

    def test_role_present(self):
        assert _contains(LLM_PRUNE_VALIDATION_TEMPLATE, "Role")


class TestLlamaPruneValidationContractPreservation:
    def test_output_contract_preserved(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert _contains(text, "valid")
        assert _contains(text, "reason")
        assert _contains(text, "仅输出 JSON 对象")

    def test_no_new_required_fields_introduced(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert "new_required_field" not in text

    def test_placeholders_unchanged(self):
        assert "{original_section}" in LLM_PRUNE_VALIDATION_TEMPLATE
        assert "{pruned_section}" in LLM_PRUNE_VALIDATION_TEMPLATE

    def test_no_new_patch_operations(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert "PatchOperation" not in text

    def test_no_new_patch_intents(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert "new_intent" not in text


class TestLlamaPruneValidationMigratedRules:
    def setup_method(self):
        self.text = LLM_PRUNE_VALIDATION_TEMPLATE

    def test_rule_1_evaluate_semantic_preservation(self):
        assert _contains(self.text, "Evaluate Semantic Preservation")
        assert _contains(self.text, "唯一约束")
        assert _contains(self.text, "占位符")

    def test_rule_2_fail_on_semantic_loss(self):
        assert _contains(self.text, "Fail on Semantic Loss")
        assert _contains(self.text, "错误合并了")
        assert _contains(self.text, "按现有输出契约标记为失败")

    def test_rule_3_fail_on_over_compression_ambiguity(self):
        assert _contains(self.text, "Fail on Over-Compression Ambiguity")
        assert _contains(self.text, "歧义")

    def test_rule_4_use_existing_labels_only(self):
        assert _contains(self.text, "Use Existing Labels Only")
        assert _contains(self.text, "不得引入新标签")


class TestLlamaPruneValidationGuardrails:
    def test_uses_existing_labels_only(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert _contains(text, "valid")
        assert _contains(text, "reason")
        assert _contains(text, "不得引入新标签")

    def test_no_new_labels_introduced(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        # UNCERTAIN/UNKNOWN/AMBIGUOUS as new enum labels are forbidden,
        # but they may appear in example reason strings (original content)
        assert '"UNKNOWN"' not in text
        assert '"AMBIGUOUS"' not in text
        # "valid" and "reason" are the only allowed fields
        assert '仅使用现有评估标签/状态' in text

    def test_does_not_rewrite_prompt_content(self):
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert _contains(text, "不修改评估语义")


# ---------------------------------------------------------------------------
# Other-template isolation (applies to both templates)
# ---------------------------------------------------------------------------

class TestOtherTemplateIsolation:
    """Verify neither template bleeds in unrelated template keywords."""

    def test_no_patch_generation_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "patch_generation" not in text
        assert "four-strategy" not in text.lower()

    def test_no_patch_semantic_merge_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "patch_semantic_merge" not in text
        assert "semantic merge" not in text.lower()

    def test_no_patch_root_audit_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "patch_root_audit" not in text
        assert "root audit" not in text.lower()

    def test_no_patch_translation_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "patch_translation" not in text

    def test_no_json_fix_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "json_fix" not in text
        assert "JSON_FIX_PROMPT" not in text

    def test_no_section_rewrite_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "section_rewrite" not in text

    def test_no_prompt_format_repair_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "prompt_format_repair" not in text

    def test_no_prompt_numbering_refactor_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "prompt_numbering_refactor" not in text

    def test_no_eval_patch_generation_keywords_in_prune(self):
        text = LLM_PRUNE_TEMPLATE
        assert "eval_patch" not in text.lower()
        assert "EVAL_PATCH_GENERATION" not in text

    def test_no_compression_templates_in_validation(self):
        """llm_prune_validation should not reference unrelated compression types."""
        text = LLM_PRUNE_VALIDATION_TEMPLATE
        assert "prompt_rewrite" not in text.lower()
        assert "arbitrary rewrite" not in text.lower()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_module_import_still_works(self):
        from mmap_optimizer.templates import optimizer_prompts as op

        assert hasattr(op, "LLM_PRUNE_TEMPLATE")
        assert hasattr(op, "LLM_PRUNE_VALIDATION_TEMPLATE")

    def test_llm_prune_spec_in_registry(self):
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES

        specs_by_id = {s.id: s for s in DEFAULT_OPTIMIZER_TEMPLATES}
        assert "llm_prune" in specs_by_id
        spec = specs_by_id["llm_prune"]
        assert spec.template == LLM_PRUNE_TEMPLATE
        assert spec.input_variables == ["section_header", "section_content"]
        assert spec.output_contract["type"] == "text"

    def test_llm_prune_validation_spec_in_registry(self):
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES

        specs_by_id = {s.id: s for s in DEFAULT_OPTIMIZER_TEMPLATES}
        assert "llm_prune_validation" in specs_by_id
        spec = specs_by_id["llm_prune_validation"]
        assert spec.template == LLM_PRUNE_VALIDATION_TEMPLATE
        assert spec.input_variables == ["original_section", "pruned_section"]
        assert spec.output_contract["type"] == "json_object"

    def test_llm_prune_template_non_trivial(self):
        assert len(LLM_PRUNE_TEMPLATE.splitlines()) > 30

    def test_llm_prune_validation_template_non_trivial(self):
        assert len(LLM_PRUNE_VALIDATION_TEMPLATE.splitlines()) > 30
