from mmap_optimizer.evaluation.prompt_optimizer import (
    EvalPromptBehaviorSuite,
    EvaluationCase,
    EvaluationPromptOptimizer,
)
from mmap_optimizer.patches import PatchCandidate, PatchOperation, PatchValidator
from mmap_optimizer.prompts import EvaluationRule, PromptIR, PromptVersion


def make_prompt_version() -> PromptVersion:
    return PromptVersion(
        version="1.0.0",
        prompt_ir=PromptIR(
            system="Evaluate the answer and return only the frozen JSON schema.",
            evaluation_rules=(
                EvaluationRule(
                    rule_id="accept_complete_citation",
                    condition="the answer includes a complete citation and directly answers the question",
                    decision="accept",
                    explanation="Known-good answer should pass.",
                ),
            ),
            output_schema={"decision": "string", "reason": "string"},
            output_format="json",
            prompt_type="evaluation",
        ),
    )


def test_misclassification_rule_repair_generates_and_accepts_eval_patch():
    prompt_version = make_prompt_version()
    mismatch = EvaluationCase(
        case_id="missing-citation-001",
        input_text="The answer makes a factual claim without any citation.",
        expected="reject",
        actual="accept",
        reason="the answer has no citation for a factual claim",
        rule_hint="reject_missing_citation",
    )
    correct = EvaluationCase(
        case_id="complete-citation-001",
        input_text="The answer contains a cited factual claim.",
        expected="accept",
        actual="accept",
        reason="the answer directly answers the question and cites evidence",
        rule_hint="accept_complete_citation",
    )

    optimizer = EvaluationPromptOptimizer(
        behavior_suite=EvalPromptBehaviorSuite((correct,)),
    )

    next_version, report = optimizer.optimize(prompt_version, (mismatch,))

    assert next_version.version == "1.0.1"
    assert next_version.prompt_ir.prompt_type == "evaluation"
    assert len(report.accepted_patches) == 1
    assert report.accepted_patches[0].candidate.target_prompt_type == "evaluation"
    assert report.fixed_eval_cases == ("missing-citation-001",)
    assert report.broken_eval_cases == ()
    assert any(rule.rule_id == "reject_missing_citation" for rule in next_version.prompt_ir.evaluation_rules)


def test_known_correct_evaluation_samples_do_not_regress():
    prompt_version = make_prompt_version()
    mismatch = EvaluationCase(
        case_id="overbroad-001",
        input_text="The answer is good but was marked incorrectly in a specific fixture.",
        expected="reject",
        actual="accept",
        reason="an overbroad rule would reject all complete citations",
        rule_hint="accept_complete_citation",
    )
    correct = EvaluationCase(
        case_id="complete-citation-001",
        input_text="The answer contains a cited factual claim.",
        expected="accept",
        actual="accept",
        reason="the answer directly answers the question and cites evidence",
        rule_hint="accept_complete_citation",
    )
    optimizer = EvaluationPromptOptimizer(behavior_suite=EvalPromptBehaviorSuite((correct,)))

    next_version, report = optimizer.optimize(prompt_version, (mismatch,))

    assert next_version.version == "1.0.0"
    assert report.accepted_patches == ()
    assert len(report.rejected_patches) == 1
    assert report.rejected_patches[0].reason == "behavior suite regression"
    assert report.broken_eval_cases == ("complete-citation-001",)


def test_output_format_and_frozen_schema_are_not_modifiable():
    validator = PatchValidator(target_prompt_type="evaluation")
    schema_candidate = PatchCandidate(
        patch_id="schema-change",
        title="Attempt schema change",
        operations=(PatchOperation("replace", "/output_schema/decision", {"enum": ["accept"]}),),
        rationale="schema must remain frozen",
        target_prompt_type="evaluation",
    )
    format_candidate = PatchCandidate(
        patch_id="format-change",
        title="Attempt format change",
        operations=(PatchOperation("replace", "/output_format", "markdown"),),
        rationale="format must remain frozen",
        target_prompt_type="evaluation",
    )

    schema_result = validator.validate(schema_candidate)
    format_result = validator.validate(format_candidate)

    assert not schema_result.valid
    assert schema_result.schema_violations == ("schema is frozen: /output_schema/decision",)
    assert not format_result.valid
    assert format_result.output_format_violations == ("output format is frozen: /output_format",)
