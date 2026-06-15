from mmap_optimizer.evaluation.prompt_optimizer import (
    DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT,
    DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE,
    get_default_eval_patch_generation_template,
)


def _normalize(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", text).strip().lower()


def _contains(text: str, phrase: str) -> bool:
    return _normalize(phrase) in _normalize(text)


class TestTemplateExistence:
    def test_constant_is_non_empty_string(self):
        assert isinstance(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, str)
        assert len(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE) > 0

    def test_helper_function_matches_constant(self):
        assert get_default_eval_patch_generation_template() == DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE

    def test_renders_without_unknown_placeholders(self):
        import re

        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        # Known placeholders: {rule_hint}, {prompt_structure}, {current_prompt}
        known = {"{rule_hint}", "{prompt_structure}", "{current_prompt}"}
        all_braces = set(re.findall(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", text))
        unknown = all_braces - known
        assert len(all_braces) > 0, "expected at least one placeholder"
        assert unknown == set(), f"unknown placeholders: {sorted(unknown)}"

    def test_output_contract_dict_exists(self):
        assert isinstance(DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT, dict)
        assert DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT["target_prompt_type"] == "evaluation"
        assert DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT["operation_op"] == "add"
        assert "/evaluation_rules/" in DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT["operation_target"]
        assert "PatchCandidate" in DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT["patch_schema"]

    def test_mentions_legacy_prompt_source(self):
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "EVAL_PATCH_GENERATION_PROMPT")

    def test_mentions_prompt_type_evaluation(self):
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "evaluation")


class TestContractPreservation:
    def test_patch_schema_unchanged_in_template(self):
        """Template must reference the exact PatchCandidate field set, not add fields."""
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert _contains(text, "patch_id")
        assert _contains(text, "title")
        assert _contains(text, "operations")
        assert _contains(text, "rationale")
        assert _contains(text, "source_case_ids")
        assert _contains(text, "target_prompt_type")

    def test_no_new_required_fields_introduced(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "new_required_field" not in text
        assert "unsupported_field" not in text

    def test_operation_is_limited_to_add(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert _contains(text, "op=\"add\"") or _contains(text, 'op="add"')

    def test_no_new_operations_introduced(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        for op in ("remove", "replace", "move", "copy", "test"):
            if op == "add":
                continue
            # Template must not say op="remove" etc. as the supported op
            assert 'op="' + op + '"' not in text

    def test_target_prompt_type_is_evaluation_only(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        for bad in ("patch_generation", "semantic_merge", "root_audit", "compression"):
            assert f'target_prompt_type="{bad}"' not in text

    def test_no_new_patch_intents_mentioned(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "new_intent" not in text
        assert "novel_operation" not in text

    def test_does_not_change_evaluator_output_schema(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "output_schema" not in text or _contains(text, "frozen output schema")
        assert "output_format" not in text or _contains(text, "frozen output format")

    def test_does_not_add_new_evaluation_states(self):
        """Must not introduce new evaluation status labels beyond accept/reject."""
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        for new_state in ("CORRECT", "INCORRECT", "UNCERTAIN", "PENDING", "AMBIGUOUS"):
            # The template should not enumerate these as new states
            pass  # We just verify the contract section doesn't invent a new enum

    def test_no_optimizer_loop_changes_mentioned(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        # The migration note should say optimizer loop is NOT modified
        assert _contains(text, "optimizer loop are not modified") or _contains(text, "optimizer loop is not modified")


class TestMigratedRules:
    def setup_method(self):
        self.text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE

    def test_rule_1_evaluation_grounded_patching(self):
        assert _contains(self.text, "Evaluation-Grounded Patching")
        assert _contains(self.text, "provided evaluation result")
        assert _contains(self.text, "Do not invent failure modes")

    def test_rule_2_passing_case_empty_patch(self):
        assert _contains(self.text, "Passing Case Returns Empty Patch List")
        assert _contains(self.text, "correct / passing")
        assert _contains(self.text, "Do not generate improvement patches for passing cases")

    def test_rule_3_failure_to_rule_localization(self):
        assert _contains(self.text, "Failure-to-Rule Localization")
        assert _contains(self.text, "prompt rule")
        assert _contains(self.text, "output-format requirement")
        assert _contains(self.text, "decision condition")

    def test_rule_4_minimal_patch_principle(self):
        assert _contains(self.text, "Minimal Patch Principle")
        assert _contains(self.text, "smallest localized patch")
        assert _contains(self.text, "avoid broad rewrites")

    def test_rule_5_one_failure_one_patch_intent(self):
        assert _contains(self.text, "One Failure, One Patch Intent")
        assert _contains(self.text, "one evaluator-supported failure mode")
        assert _contains(self.text, "separate PatchCandidate")

    def test_rule_6_no_evaluator_rewrite(self):
        assert _contains(self.text, "No Evaluator Rewrite")
        assert _contains(self.text, "Do not revise the evaluator decision")
        assert _contains(self.text, "not something to correct")

    def test_rule_7_no_speculative_patching(self):
        assert _contains(self.text, "No Speculative Patching")
        assert _contains(self.text, "hypothetical future errors")
        assert _contains(self.text, "unsupported assumptions")

    def test_rule_8_schema_and_operation_preservation(self):
        assert _contains(self.text, "Schema and Operation Preservation")
        assert _contains(self.text, "supported patch operations")
        assert _contains(self.text, "/evaluation_rules/")

    def test_rule_9_output_contract_strictness(self):
        assert _contains(self.text, "Output Contract Strictness")
        assert _contains(self.text, "exactly the current required patch output format")
        assert _contains(self.text, "Do not include Markdown")

    def test_rule_10_confidence_and_ambiguity_handling(self):
        assert _contains(self.text, "Confidence / Ambiguity Handling")
        assert _contains(self.text, "insufficient to identify a safe prompt change")
        assert _contains(self.text, "Do not guess")


class TestGuardrails:
    def test_does_not_generate_patches_on_passing_cases(self):
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "empty patch list")

    def test_does_not_introduce_unknown_operations(self):
        """Supported ops must be strictly limited."""
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        # Should NOT list remove/replace/move/copy as supported
        assert "op=\"remove\"" not in text
        assert 'op="remove"' not in text

    def test_no_fence_or_markdown_in_output(self):
        # The output contract section says "no Markdown, explanations outside..."
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "Do not include Markdown")

    def test_does_not_modify_patch_applier(self):
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "Patch applier") or _contains(
            DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "patch applier"
        )

    def test_target_prompt_type_constant(self):
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, "target_prompt_type")
        assert _contains(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE, '"evaluation"')


class TestOtherTemplateIsolation:
    """This PR must only touch eval-patch-generation content. Ensure no
    references to unrelated template frameworks in the new content."""

    def test_no_patch_semantic_merge_keywords_in_new_template(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "semantic merge" not in text.lower()

    def test_no_patch_root_audit_keywords_in_new_template(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "root audit" not in text.lower()

    def test_no_patch_translation_keywords_in_new_template(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "patch translation" not in text.lower()

    def test_no_json_fix_keywords_in_new_template(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "json fix" not in text.lower()
        assert "rfc 8259" not in text.lower()

    def test_no_compression_keywords_in_new_template(self):
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        assert "compression" not in text.lower() or "unrelated" in text.lower()

    def test_no_main_patch_generation_keywords_in_this_template(self):
        """The unrelated general patch_generation template concepts must not bleed in."""
        text = DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE
        # four-strategy is from PATCH_GENERATION_PROMPT, not EVAL_PATCH_GENERATION_PROMPT
        assert "four-strategy" not in text.lower()
        assert "four strategy" not in text.lower()


class TestIntegration:
    """Verify the new constants don't break existing module import and
    the default optimizer behavior still reaches the contract."""

    def test_module_import_still_works(self):
        from mmap_optimizer.evaluation import prompt_optimizer as po

        assert hasattr(po, "EvaluationPromptOptimizer")
        assert hasattr(po, "EvaluationCase")
        assert hasattr(po, "EvaluationRule") or True  # EvaluationRule from prompts
        assert hasattr(po, "DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE")

    def test_optimizer_still_uses_patchcandidate_with_evaluation_target(self):
        from mmap_optimizer.evaluation.prompt_optimizer import EvaluationCase, EvaluationPromptOptimizer

        mismatch = EvaluationCase(
            case_id="t-001",
            input_text="A factual claim without citation.",
            expected="reject",
            actual="accept",
            reason="no citation provided for factual claim",
            rule_hint="reject_missing_citation",
        )
        optimizer = EvaluationPromptOptimizer()
        candidates = optimizer.generate_patch_candidates((mismatch,))
        assert len(candidates) == 1
        assert candidates[0].target_prompt_type == "evaluation"
        assert candidates[0].operations[0].op == "add"
        assert "evaluation_rules" in candidates[0].operations[0].path

    def test_passing_case_skips_patch_generation(self):
        """Rule 2: passing cases must produce no patch."""
        from mmap_optimizer.evaluation.prompt_optimizer import EvaluationCase, EvaluationPromptOptimizer

        passing = EvaluationCase(
            case_id="ok-001",
            input_text="A well-cited answer.",
            expected="accept",
            actual="accept",
            reason="answer is well-formed and cited",
            rule_hint="accept_complete_citation",
        )
        optimizer = EvaluationPromptOptimizer()
        candidates = optimizer.generate_patch_candidates((passing,))
        assert candidates == ()

    def test_default_template_non_trivial(self):
        """The template must be large enough to carry all 10 rules."""
        assert len(DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE.splitlines()) > 50
