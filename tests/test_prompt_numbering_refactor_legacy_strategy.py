"""Contract tests for the PROMPT_REFACTOR_PROMPT legacy strategy adaptation.

These tests verify the deterministic text-level contract of the enriched
``PROMPT_NUMBERING_REFACTOR_TEMPLATE`` in
:mod:`mmap_optimizer.templates.optimizer_prompts`. They do not invoke a
language model, do not touch the optimizer loop, and do not modify any
runtime behavior.

A separate test module (``test_prompt_numbering_refactor_utility``) covers
the deterministic code utility in ``mmap_optimizer.prompt.numbering_refactor``.
"""

from mmap_optimizer.templates.optimizer_prompts import PROMPT_NUMBERING_REFACTOR_TEMPLATE


def _normalize(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


class TestTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(PROMPT_NUMBERING_REFACTOR_TEMPLATE, str)
        assert len(PROMPT_NUMBERING_REFACTOR_TEMPLATE) > 0

    def test_required_placeholders_present(self):
        assert "{current_prompt}" in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_unknown_placeholders(self):
        import re

        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        known = {"{current_prompt}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_mentions_legacy_prompt_source(self):
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "PROMPT_REFACTOR_PROMPT")

    def test_role_present(self):
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "Role")
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "只修复结构化 prompt 的编号")


class TestContractPreservation:
    def test_output_is_refactored_prompt_body_only(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert _contains(text, "仅修复后的 prompt body")
        assert _contains(text, "无 header")

    def test_no_new_required_fields_introduced(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "new_required_field" not in text
        assert "unsupported_field" not in text

    def test_placeholders_unchanged(self):
        assert "{current_prompt}" in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_fallback_behavior_preserved(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert _contains(text, "ambiguity fallback") or _contains(text, "保留原始文本")

    def test_no_new_patch_operations(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "PatchOperation" not in text
        assert "op=" not in text

    def test_no_new_patch_intents(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "new_intent" not in text
        assert "novel_operation" not in text


class TestMigratedRules:
    def setup_method(self):
        self.text = PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_rule_1_numbering_only_refactor(self):
        assert _contains(self.text, "Numbering-Only Refactor")
        assert _contains(self.text, "只重编编号")
        assert _contains(self.text, "不得改变业务逻辑")

    def test_rule_2_preserve_semantic_content(self):
        assert _contains(self.text, "Preserve Semantic Content")
        assert _contains(self.text, "精确保留每条原始规则")
        assert _contains(self.text, "占位符")
        assert _contains(self.text, "变量")

    def test_rule_3_fix_duplicate_skipped_inconsistent_numbering(self):
        assert _contains(self.text, "Fix Duplicate / Skipped / Inconsistent Numbering")
        assert _contains(self.text, "修复重复编号")
        assert _contains(self.text, "跳过编号")
        assert _contains(self.text, "不一致的编号样式")

    def test_rule_4_preserve_hierarchy(self):
        assert _contains(self.text, "Preserve Hierarchy")
        assert _contains(self.text, "保留原始标题层级")
        assert _contains(self.text, "父子关系")

    def test_rule_5_preserve_cross_references(self):
        assert _contains(self.text, "Preserve Cross-References When Possible")
        assert _contains(self.text, "交叉引用")
        assert _contains(self.text, "见第 3 步")

    def test_rule_6_placeholder_and_code_block_protection(self):
        assert _contains(self.text, "Placeholder and Code Block Protection")
        assert _contains(self.text, "不得修改占位符")
        assert _contains(self.text, "代码块")

    def test_rule_7_minimal_edit_principle(self):
        assert _contains(self.text, "Minimal Edit Principle")
        assert _contains(self.text, "最小可能编号编辑")

    def test_rule_8_no_global_standardization(self):
        assert _contains(self.text, "No Global Standardization")
        assert _contains(self.text, "七段式结构")
        assert _contains(self.text, "不得将 prompt 规范化为新的风格")

    def test_rule_9_ambiguity_fallback(self):
        assert _contains(self.text, "Ambiguity Fallback")
        assert _contains(self.text, "保留原始文本")
        assert _contains(self.text, "避免推测性重排")

    def test_rule_10_output_refactored_prompt_only(self):
        assert _contains(self.text, "Output Refactored Prompt Only")
        assert _contains(self.text, "不得包含解释")
        assert _contains(self.text, "Markdown 包装器")
        assert _contains(self.text, "代码 fence")


class TestGuardrails:
    def test_does_not_allow_business_logic_changes(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert _contains(text, "不得改变业务逻辑")

    def test_does_not_allow_arbitrary_standardization(self):
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "不得将 prompt 规范化为新的风格")

    def test_no_optimizer_loop_changes_mentioned(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert _contains(text, "optimizer loop") and _contains(text, "未被修改")

    def test_no_wrappers_or_code_fence(self):
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "不得包含解释")
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "Markdown 包装器")
        assert _contains(PROMPT_NUMBERING_REFACTOR_TEMPLATE, "代码 fence")

    def test_no_new_placeholders(self):
        import re

        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        known = {"{current_prompt}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        assert all_braces == known

    def test_eval_prompt_not_migrated_documented(self):
        """PROMPT_REFACTOR_EVAL_PROMPT has no current target; migration note must document this."""
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert _contains(text, "PROMPT_REFACTOR_EVAL_PROMPT")
        assert _contains(text, "暂不迁移") or _contains(text, "无对应目标")


class TestOtherTemplateIsolation:
    def test_no_patch_generation_keywords(self):
        text = PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "patch_generation" not in text
        assert "four-strategy" not in text.lower()
        assert "PATCH_GENERATION_PROMPT" not in text

    def test_no_patch_semantic_merge_keywords(self):
        assert "patch_semantic_merge" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "semantic merge" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE.lower()

    def test_no_patch_root_audit_keywords(self):
        assert "patch_root_audit" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "root audit" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE.lower()

    def test_no_patch_translation_keywords(self):
        assert "patch_translation" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_json_fix_keywords(self):
        assert "json_fix" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "JSON_FIX_PROMPT" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_section_rewrite_keywords(self):
        assert "section_rewrite" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "PROMPT_REPLACE_SECTION_TEMPLATE" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_prompt_format_repair_keywords(self):
        assert "prompt_format_repair" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "PROMPT_FORMAT_REPAIR_PROMPT" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_eval_patch_generation_keywords(self):
        assert "eval_patch" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert "EVAL_PATCH_GENERATION" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE

    def test_no_compression_keywords(self):
        assert "compression template" not in PROMPT_NUMBERING_REFACTOR_TEMPLATE.lower()


class TestIntegration:
    def test_module_import_still_works(self):
        from mmap_optimizer.templates import optimizer_prompts as op

        assert hasattr(op, "PROMPT_NUMBERING_REFACTOR_TEMPLATE")
        assert hasattr(op, "DEFAULT_OPTIMIZER_TEMPLATES")

    def test_prompt_numbering_refactor_spec_in_registry(self):
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES

        specs_by_id = {s.id: s for s in DEFAULT_OPTIMIZER_TEMPLATES}
        assert "prompt_numbering_refactor" in specs_by_id
        spec = specs_by_id["prompt_numbering_refactor"]
        assert spec.template == PROMPT_NUMBERING_REFACTOR_TEMPLATE
        assert spec.input_variables == ["current_prompt"]
        assert spec.output_contract["type"] == "text"

    def test_template_non_trivial(self):
        """The template must be large enough to carry all 10 rules."""
        assert len(PROMPT_NUMBERING_REFACTOR_TEMPLATE.splitlines()) > 30
