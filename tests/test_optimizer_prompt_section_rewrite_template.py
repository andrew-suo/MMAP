from mmap_optimizer.templates.optimizer_prompts import SECTION_REWRITE_TEMPLATE


def _normalize(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


class TestTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(SECTION_REWRITE_TEMPLATE, str)
        assert len(SECTION_REWRITE_TEMPLATE) > 0

    def test_required_placeholders_present(self):
        assert "{section_header}" in SECTION_REWRITE_TEMPLATE
        assert "{section_content}" in SECTION_REWRITE_TEMPLATE
        assert "{optimization_instruction}" in SECTION_REWRITE_TEMPLATE

    def test_no_unknown_placeholders(self):
        import re

        text = SECTION_REWRITE_TEMPLATE
        known = {"{section_header}", "{section_content}", "{optimization_instruction}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert len(all_braces) > 0, "expected at least one placeholder"
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_mentions_legacy_prompt_source(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "PROMPT_REPLACE_SECTION_TEMPLATE")

    def test_mentions_section_rewrite_role(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "重写单个 prompt section")


class TestContractPreservation:
    def test_output_contract_is_text_only(self):
        """Current contract: raw section text only, no headers, no code blocks."""
        text = SECTION_REWRITE_TEMPLATE
        assert _contains(text, "仅输出 section body")
        assert _contains(text, "不包含 Markdown")
        # Note: template says "不输出 heading" not "不包含 header"
        assert _contains(text, "不输出 heading")

    def test_no_new_required_fields_introduced(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "new_required_field" not in text
        assert "unsupported_field" not in text

    def test_placeholders_unchanged(self):
        text = SECTION_REWRITE_TEMPLATE
        # Must preserve the exact placeholder names
        assert "{section_header}" in text
        assert "{section_content}" in text
        assert "{optimization_instruction}" in text

    def test_fallback_behavior_preserved(self):
        text = SECTION_REWRITE_TEMPLATE
        assert _contains(text, "保持原 section 内容") or _contains(text, "fallback")

    def test_no_new_operations_introduced(self):
        """Section rewrite is not a patch operation generator."""
        text = SECTION_REWRITE_TEMPLATE
        # Should not mention patch operations like add/remove/replace
        assert "PatchOperation" not in text
        assert "op=\"add\"" not in text
        assert 'op="add"' not in text

    def test_no_new_patch_intent_introduced(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "new_intent" not in text
        assert "novel_operation" not in text


class TestMigratedRules:
    def setup_method(self):
        self.text = SECTION_REWRITE_TEMPLATE

    def test_rule_1_target_section_only_rewrite(self):
        assert _contains(self.text, "Target-Section-Only Rewrite")
        assert _contains(self.text, "只重写指定的目标 section")
        assert _contains(self.text, "不得修改、重排、总结、删除或添加任何其他 section")

    def test_rule_2_preserve_section_boundary(self):
        assert _contains(self.text, "Preserve Section Boundary")
        assert _contains(self.text, "保持目标 section 的边界")
        assert _contains(self.text, "同一 section 身份内")

    def test_rule_3_preserve_placeholders_and_variables(self):
        assert _contains(self.text, "Preserve Placeholders and Variables")
        assert _contains(self.text, "保持所有现有占位符")
        assert _contains(self.text, "{section_header}")
        assert _contains(self.text, "{section_content}")
        assert _contains(self.text, "{optimization_instruction}")

    def test_rule_4_minimal_rewrite_principle(self):
        assert _contains(self.text, "Minimal Rewrite Principle")
        assert _contains(self.text, "最小重写")
        assert _contains(self.text, "避免广泛的风格重写")

    def test_rule_5_preserve_unrelated_constraints(self):
        assert _contains(self.text, "Preserve Unrelated Constraints")
        assert _contains(self.text, "保留原 section 中所有无关约束")

    def test_rule_6_no_semantic_drift(self):
        assert _contains(self.text, "No Semantic Drift")
        assert _contains(self.text, "不得改变未被请求编辑直接针对的规则的预期含义")

    def test_rule_7_no_section_creation_or_deletion(self):
        assert _contains(self.text, "No Section Creation or Deletion")
        assert _contains(self.text, "不得创建新 section")
        # Template has "删除 section" and "合并 section" in the same line
        assert _contains(self.text, "删除 section")
        assert _contains(self.text, "合并 section")

    def test_rule_8_output_contract_strictness(self):
        assert _contains(self.text, "Output Contract Strictness")
        assert _contains(self.text, "严格返回当前要求的输出格式")
        assert _contains(self.text, "不包含 Markdown")

    def test_rule_9_failure_ambiguity_fallback(self):
        assert _contains(self.text, "Failure / Ambiguity Fallback")
        assert _contains(self.text, "无法在不违反 section 边界")
        assert _contains(self.text, "不要猜测")

    def test_rule_10_patch_intent_fidelity(self):
        assert _contains(self.text, "Patch-Intent Fidelity")
        assert _contains(self.text, "重写必须仅实现请求的 patch intent")
        assert _contains(self.text, "不得添加额外改进")


class TestGuardrails:
    def test_does_not_allow_cross_section_edits(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "不得修改、重排、总结、删除或添加任何其他 section")

    def test_does_not_allow_section_creation_deletion(self):
        text = SECTION_REWRITE_TEMPLATE
        assert _contains(text, "不得创建新 section")
        assert _contains(text, "删除 section")

    def test_does_not_allow_broad_global_rewrite(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "避免广泛的风格重写")

    def test_no_optimizer_loop_mention(self):
        """Migration note should state optimizer loop is NOT modified."""
        text = SECTION_REWRITE_TEMPLATE
        assert _contains(text, "optimizer loop") and _contains(text, "未被修改")

    def test_no_fence_or_markdown_in_output(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "不包含 Markdown")
        assert _contains(SECTION_REWRITE_TEMPLATE, "代码 fence") or _contains(
            SECTION_REWRITE_TEMPLATE, "fence"
        )

    def test_output_is_section_body_only(self):
        assert _contains(SECTION_REWRITE_TEMPLATE, "仅输出 section body")


class TestOtherTemplateIsolation:
    """This PR must only touch section_rewrite content. Ensure no references to
    unrelated template frameworks in the new content."""

    def test_no_patch_generation_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        # four-strategy is from PATCH_GENERATION_PROMPT
        assert "four-strategy" not in text.lower()
        assert "four strategy" not in text.lower()
        assert "PASS/CORRECT" not in text

    def test_no_patch_semantic_merge_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "semantic merge" not in text.lower()
        assert "patch_semantic_merge" not in text.lower()

    def test_no_patch_root_audit_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "root audit" not in text.lower()
        assert "patch_root_audit" not in text.lower()

    def test_no_patch_translation_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "patch translation" not in text.lower()
        assert "patch_translation" not in text.lower()

    def test_no_json_fix_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "json fix" not in text.lower()
        assert "rfc 8259" not in text.lower()

    def test_no_eval_patch_generation_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        assert "eval patch generation" not in text.lower()
        assert "EVAL_PATCH_GENERATION" not in text

    def test_no_compression_keywords_in_section_rewrite(self):
        text = SECTION_REWRITE_TEMPLATE
        # compression is a separate template
        assert "compression template" not in text.lower()


class TestIntegration:
    """Verify the modified template doesn't break existing module import."""

    def test_module_import_still_works(self):
        from mmap_optimizer.templates import optimizer_prompts as op

        assert hasattr(op, "SECTION_REWRITE_TEMPLATE")
        assert hasattr(op, "DEFAULT_OPTIMIZER_TEMPLATES")

    def test_section_rewrite_spec_in_registry(self):
        from mmap_optimizer.templates.optimizer_prompts import DEFAULT_OPTIMIZER_TEMPLATES

        specs_by_id = {s.id: s for s in DEFAULT_OPTIMIZER_TEMPLATES}
        assert "section_rewrite" in specs_by_id
        spec = specs_by_id["section_rewrite"]
        assert spec.template == SECTION_REWRITE_TEMPLATE
        assert spec.input_variables == ["section_header", "section_content", "optimization_instruction"]
        assert spec.output_contract["type"] == "text"

    def test_template_non_trivial(self):
        """The template must be large enough to carry all 10 rules."""
        assert len(SECTION_REWRITE_TEMPLATE.splitlines()) > 30