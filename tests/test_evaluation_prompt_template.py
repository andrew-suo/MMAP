from __future__ import annotations

import re

from mmap_optimizer.prompts import (
    DEFAULT_EVALUATION_OUTPUT_SCHEMA,
    DEFAULT_EVALUATION_PROMPT_SYSTEM,
    EvaluationRule,
    PromptIR,
    PromptVersion,
    make_default_evaluation_prompt_ir,
)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _contains(source: str, phrase: str) -> bool:
    return _collapse(phrase) in _collapse(source)


def _rendered() -> str:
    """Render a default evaluation prompt IR so we can inspect its text."""
    return make_default_evaluation_prompt_ir().render()


# ---------------------------------------------------------------------------
# Template / Constant existence
# ---------------------------------------------------------------------------


class TestExistence:
    def test_default_system_constant_exists(self):
        assert isinstance(DEFAULT_EVALUATION_PROMPT_SYSTEM, str)
        assert DEFAULT_EVALUATION_PROMPT_SYSTEM.strip()

    def test_default_output_schema_is_dict(self):
        assert isinstance(DEFAULT_EVALUATION_OUTPUT_SCHEMA, dict)
        assert "decision" in DEFAULT_EVALUATION_OUTPUT_SCHEMA
        assert "reason" in DEFAULT_EVALUATION_OUTPUT_SCHEMA

    def test_make_default_evaluation_prompt_ir_runs(self):
        ir = make_default_evaluation_prompt_ir()
        assert isinstance(ir, PromptIR)
        assert ir.prompt_type == "evaluation"
        assert ir.output_format == "json"
        rendered = ir.render()
        assert rendered
        assert "Evaluation rules:" in rendered


# ---------------------------------------------------------------------------
# Contract preservation
# ---------------------------------------------------------------------------


class TestContractPreservation:
    def test_output_schema_unmodified(self):
        """Output schema must remain the current contract: decision + reason."""
        ir = make_default_evaluation_prompt_ir()
        assert dict(ir.output_schema) == {"decision": "string", "reason": "string"}

    def test_output_format_is_json(self):
        ir = make_default_evaluation_prompt_ir()
        assert ir.output_format == "json"

    def test_prompt_type_is_evaluation(self):
        ir = make_default_evaluation_prompt_ir()
        assert ir.prompt_type == "evaluation"

    def test_no_new_required_fields_introduced(self):
        ir = make_default_evaluation_prompt_ir()
        schema_keys = set(dict(ir.output_schema).keys())
        # Only the original "decision" and "reason" — nothing else.
        assert schema_keys <= {"decision", "reason"}

    def test_evaluation_rules_can_be_appended_without_schema_change(self):
        """Adding evaluation rules must not change output schema."""
        ir = make_default_evaluation_prompt_ir()
        new_ir = ir.with_rules(
            (EvaluationRule("r1", "condition text", "accept"),)
        )
        assert dict(new_ir.output_schema) == dict(ir.output_schema)
        assert new_ir.output_format == ir.output_format
        assert "[r1]" in new_ir.render()

    def test_rendered_includes_evaluation_rules_section(self):
        rendered = _rendered()
        assert "Evaluation rules:" in rendered

    def test_rendered_includes_output_format_label(self):
        rendered = _rendered()
        assert "Output format:" in rendered
        assert "json" in rendered.lower()

    def test_rendered_includes_output_schema_label(self):
        rendered = _rendered()
        assert "Output schema:" in rendered


# ---------------------------------------------------------------------------
# Migrated rule presence in rendered template
# ---------------------------------------------------------------------------


class TestMigratedRules:
    def setup_method(self):
        self.rendered = _rendered()

    def test_eval_blind_context_discipline(self):
        assert _contains(self.rendered, "Eval-Blind Context Discipline")
        assert _contains(self.rendered, "Evaluate only from the provided prompt")
        assert _contains(self.rendered, "Do not use outside knowledge")

    def test_passing_case_protection(self):
        assert _contains(self.rendered, "Passing Case Protection")
        assert _contains(self.rendered, "mark it as correct / pass")
        assert _contains(self.rendered, "Do not invent improvement suggestions for passing cases")

    def test_failure_localization(self):
        assert _contains(self.rendered, "Failure Localization")
        assert _contains(self.rendered, "which prompt rule, output-format requirement, or decision condition was violated")

    def test_separate_task_and_formatting_failure(self):
        assert _contains(self.rendered, "Separate Task Failure from Formatting Failure")
        assert _contains(self.rendered, "semantic / task-decision failures")
        assert _contains(self.rendered, "output-format / schema failures")

    def test_evidence_grounded_judgement(self):
        assert _contains(self.rendered, "Evidence-Grounded Judgement")
        assert _contains(self.rendered, "grounded in observable evidence")

    def test_no_patch_generation_during_evaluation(self):
        assert _contains(self.rendered, "No Patch Generation During Evaluation")
        assert _contains(self.rendered, "Do not generate patch objects")
        assert _contains(self.rendered, "rewrite prompt sections")
        assert _contains(self.rendered, "propose concrete patch operations")

    def test_minimal_actionable_failure_reason(self):
        assert _contains(self.rendered, "Minimal Actionable Failure Reason")
        assert _contains(self.rendered, "concise, actionable failure reason")

    def test_output_contract_strictness(self):
        assert _contains(self.rendered, "Output Contract Strictness")
        assert _contains(self.rendered, "Return exactly the current required evaluation output format")

    def test_ambiguity_handling(self):
        assert _contains(self.rendered, "Ambiguity Handling")
        assert _contains(self.rendered, "use the existing uncertainty / invalid / inconclusive mechanism")
        assert _contains(self.rendered, "without inventing a new status")

    def test_migration_note_present(self):
        assert _contains(self.rendered, "Migration Note")
        assert _contains(self.rendered, "EVALUATION_PROMPT")

    def test_no_optimizer_loop_mention(self):
        """The system text must not instruct modification of the optimizer loop.
        It may only state (in a migration-note sense) that optimizer loop is
        NOT affected."""
        assert "optimizer loop must" not in self.rendered.lower()
        assert "modify the optimizer" not in self.rendered.lower()
        assert "change the optimizer" not in self.rendered.lower()

    def test_no_new_status_labels_mentioned(self):
        # Template must not invent new labels beyond what the contract supports.
        assert "new_status" not in self.rendered
        assert "{" + '"new"' not in self.rendered  # no JSON inventing new fields


# ---------------------------------------------------------------------------
# Guardrails: Output schema / format must not change
# ---------------------------------------------------------------------------


class TestGuardrails:
    def test_default_system_does_not_introduce_new_output_fields(self):
        """The system text should not dictate new output fields beyond the
        existing schema."""
        rendered = _rendered()
        # The system text must not list new fields beyond decision / reason.
        assert '"field"' not in rendered or '"fields"' not in rendered

    def test_evaluation_label_vocabulary_not_enlarged(self):
        """Template must not introduce a new status vocabulary. The decision
        space (accept / reject / OK / NG / UNCERTAIN / correct / wrong ...) is
        intentionally left to the evaluation_rules — not hard-coded here."""
        ir = make_default_evaluation_prompt_ir()
        # decision space is empty until rules are layered on top.
        assert len(ir.evaluation_rules) == 0

    def test_output_format_remains_json(self):
        ir = make_default_evaluation_prompt_ir()
        assert ir.output_format == "json"

    def test_patch_operations_not_mentioned_in_system(self):
        assert "PatchOperation" not in DEFAULT_EVALUATION_PROMPT_SYSTEM
        assert "patch validator" not in DEFAULT_EVALUATION_PROMPT_SYSTEM.lower()

    def test_system_does_not_mention_compression_or_fewshot(self):
        assert "compression" not in DEFAULT_EVALUATION_PROMPT_SYSTEM.lower()
        assert "few-shot" not in DEFAULT_EVALUATION_PROMPT_SYSTEM.lower()


# ---------------------------------------------------------------------------
# Round-trip: PromptVersion can wrap the evaluation PromptIR and be bumped
# ---------------------------------------------------------------------------


class TestPromptVersionRoundTrip:
    def test_prompt_version_wraps_default_ir(self):
        ir = make_default_evaluation_prompt_ir()
        pv = PromptVersion(version="1.0.0", prompt_ir=ir)
        assert pv.prompt_ir.prompt_type == "evaluation"
        assert pv.version == "1.0.0"

    def test_prompt_version_bump_preserves_contract(self):
        ir = make_default_evaluation_prompt_ir()
        pv = PromptVersion(version="1.0.0", prompt_ir=ir)
        next_ir = ir.with_rules(
            (EvaluationRule("r1", "condition", "accept", "explanation"),)
        )
        next_pv = pv.bump(next_ir, "patch-1")
        assert next_pv.version == "1.0.1"
        assert dict(next_pv.prompt_ir.output_schema) == {"decision": "string", "reason": "string"}
        assert next_pv.prompt_ir.output_format == "json"
        assert "[r1]" in next_pv.prompt_ir.render()
