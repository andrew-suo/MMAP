from mmap_optimizer.templates.optimizer_prompts import PROMPT_FORMAT_REPAIR_TEMPLATE


def _normalize(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


class TestTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(PROMPT_FORMAT_REPAIR_TEMPLATE, str)
        assert len(PROMPT_FORMAT_REPAIR_TEMPLATE) > 0

    def test_required_placeholders_present(self):
        assert "{issues_description}" in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "{original_prompt}" in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_no_unknown_placeholders(self):
        import re

        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        known = {"{issues_description}", "{original_prompt}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_mentions_legacy_prompt_source(self):
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "PROMPT_FORMAT_REPAIR_PROMPT")

    def test_role_present(self):
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "Role")


class TestContractPreservation:
    def test_output_is_repaired_prompt_text_only(self):
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "只输出修复后的 prompt 文本")
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "Output Repaired Prompt Only")

    def test_no_new_required_fields_introduced(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "new_required_field" not in text
        assert "unsupported_field" not in text

    def test_placeholders_unchanged(self):
        assert "{issues_description}" in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "{original_prompt}" in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_fallback_behavior_preserved(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert _contains(text, "ambiguity fallback") or _contains(text, "保留原始文本")

    def test_no_new_operations_introduced(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "PatchOperation" not in text
        assert "op=" not in text or "op=" not in text

    def test_no_new_patch_intents_introduced(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "new_intent" not in text
        assert "novel_operation" not in text


class TestMigratedRules:
    def setup_method(self):
        self.text = PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_rule_1_format_only_repair(self):
        assert _contains(self.text, "Format-Only Repair")
        assert _contains(self.text, "只修复格式")
        assert _contains(self.text, "不得改变业务逻辑")

    def test_rule_2_preserve_all_semantic_content(self):
        assert _contains(self.text, "Preserve All Semantic Content")
        assert _contains(self.text, "保留每条原始规则")
        assert _contains(self.text, "占位符")
        assert _contains(self.text, "变量")

    def test_rule_3_markdown_structure_repair(self):
        assert _contains(self.text, "Markdown Structure Repair")
        assert _contains(self.text, "Markdown 标题层级")
        assert _contains(self.text, "列表缩进")
        assert _contains(self.text, "代码 fence")
        assert _contains(self.text, "表格对齐")

    def test_rule_4_no_section_semantic_drift(self):
        assert _contains(self.text, "No Section Semantic Drift")
        assert _contains(self.text, "不得在改变含义的情况下跨 section 移动内容")

    def test_rule_5_placeholder_preservation(self):
        assert _contains(self.text, "Placeholder Preservation")
        assert _contains(self.text, "精确保留占位符")
        assert _contains(self.text, "花括号")

    def test_rule_6_output_contract_preservation(self):
        assert _contains(self.text, "Output Contract Preservation")
        assert _contains(self.text, "精确保留 prompt 的输出格式要求")
        assert _contains(self.text, "输出字段")

    def test_rule_7_minimal_edit_principle(self):
        assert _contains(self.text, "Minimal Edit Principle")
        assert _contains(self.text, "最小可能的格式编辑")

    def test_rule_8_no_global_standardization(self):
        assert _contains(self.text, "No Global Standardization")
        assert _contains(self.text, "七段式结构")
        assert _contains(self.text, "不得将 prompt 规范化为新的风格")

    def test_rule_9_ambiguity_fallback(self):
        assert _contains(self.text, "Ambiguity Fallback")
        assert _contains(self.text, "保留原始文本")
        assert _contains(self.text, "避免推测性重排")

    def test_rule_10_output_repaired_prompt_only(self):
        assert _contains(self.text, "Output Repaired Prompt Only")
        assert _contains(self.text, "不得包含解释")
        assert _contains(self.text, "标签")
        assert _contains(self.text, "评注")


class TestGuardrails:
    def test_does_not_allow_business_logic_changes(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert _contains(text, "不得改变业务逻辑")
        assert _contains(text, "任务规则")

    def test_does_not_allow_arbitrary_standardization(self):
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "不得将 prompt 规范化为新的风格")

    def test_no_optimizer_loop_changes_mentioned(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert _contains(text, "optimizer loop") and _contains(text, "未被修改")

    def test_no_wrappers_or_code_fence(self):
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "不得包含解释")
        assert _contains(PROMPT_FORMAT_REPAIR_TEMPLATE, "代码 fence")

    def test_no_new_placeholders(self):
        import re

        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        known = {"{issues_description}", "{original_prompt}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        assert all_braces == known


class TestOtherTemplateIsolation:
    def test_no_patch_generation_keywords(self):
        text = PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "patch_generation" not in text
        assert "four-strategy" not in text.lower()
        assert "PATCH_GENERATION_PROMPT" not in text

    def test_no_patch_semantic_merge_keywords(self):
        assert "patch_semantic_merge" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "semantic merge" not in PROMPT_FORMAT_REPAIR_TEMPLATE.lower()

    def test_no_patch_root_audit_keywords(self):
        assert "patch_root_audit" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "root audit" not in PROMPT_FORMAT_REPAIR_TEMPLATE.lower()

    def test_no_patch_translation_keywords(self):
        assert "patch_translation" not in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_no_json_fix_keywords(self):
        assert "json_fix" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "JSON_FIX_PROMPT" not in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_no_section_rewrite_keywords(self):
        assert "section_rewrite" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "PROMPT_REPLACE_SECTION_TEMPLATE" not in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_no_eval_patch_generation_keywords(self):
        assert "eval_patch" not in PROMPT_FORMAT_REPAIR_TEMPLATE
        assert "EVAL_PATCH_GENERATION" not in PROMPT_FORMAT_REPAIR_TEMPLATE

    def test_no_compression_keywords(self):
        assert "compression" not in PROMPT_FORMAT_REPAIR_TEMPLATE.lower()


class TestIntegration:
    def test_module_import_still_works(self):
        from mmap_optimizer.templates import optimizer_prompts as op

        assert hasattr(op, "PROMPT_FORMAT_REPAIR_TEMPLATE")
        assert hasattr(op, "DEFAULT_OPTIMIZER_TEMPLATES")

    def test_prompt_format_repair_spec_in_registry(self):
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES

        specs_by_id = {s.id: s for s in DEFAULT_OPTIMIZER_TEMPLATES}
        assert "prompt_format_repair" in specs_by_id
        spec = specs_by_id["prompt_format_repair"]
        assert spec.template == PROMPT_FORMAT_REPAIR_TEMPLATE
        assert spec.input_variables == ["issues_description", "original_prompt"]
        assert spec.output_contract["type"] == "text"

    def test_template_non_trivial(self):
        assert len(PROMPT_FORMAT_REPAIR_TEMPLATE.splitlines()) > 30
