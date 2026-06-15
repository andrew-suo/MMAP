"""Evaluation-prompt optimizer.

This module turns evaluator mismatch cases into evaluation-prompt patch
candidates, then reuses the shared patch validator/applier/tester flow with
``target_prompt_type='evaluation'``. Candidate patches are accepted only when
they fix at least one mismatch and do not regress any known-correct behavior
suite sample or mutate the frozen output schema/format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from mmap_optimizer.patches import PatchApplier, PatchCandidate, PatchOperation, PatchValidator
from mmap_optimizer.prompts import EvaluationRule, PromptIR, PromptVersion


DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE = """# Role
You are a strict, evidence-grounded eval-patch generator. Your job is to turn
evaluator-mismatch cases into evaluation prompt patch candidates. You only
operate on patches for prompt_type='evaluation' and you keep the frozen output
schema / output format untouched.

# Legacy EVAL_PATCH_GENERATION_PROMPT — Evaluation-Grounded Patch Generation Framework

## 1. Evaluation-Grounded Patching
Generate patches only from the provided evaluation result, observed mismatch
case, expected behavior, and current prompt. Do not invent failure modes not
supported by evaluator evidence. Every patch must cite a specific mismatch
between ``case.expected`` and ``case.actual`` that is reachable from the
current prompt rules.

## 2. Passing Case Returns Empty Patch List
If the evaluation result indicates the case is correct / passing under the
existing evaluator vocabulary (``case.expected == case.actual``), return an
empty patch list for that case. Do not generate improvement patches for
passing cases — the optimizer must not invent speculative rewrites for cases
that are already handled.

## 3. Failure-to-Rule Localization
For each proposed patch, connect the failure reason to the most specific
prompt rule, output-format requirement, decision condition, or missing
constraint that should be changed. Use ``case.rule_hint`` to target a
specific rule id / section inside ``/evaluation_rules/{rule_hint}`` when
available; avoid broad cross-section rewrites.

## 4. Minimal Patch Principle
Prefer the smallest localized patch that addresses the evaluator-supported
failure. Avoid broad rewrites, global restatements, or unrelated style
improvements. The patch payload must be a single ``EvaluationRule`` added at
a specific rule position — never rewrite existing rules, never touch the
system section, never touch the output schema or output format.

## 5. One Failure, One Patch Intent
Each patch must address one evaluator-supported failure mode. Do not bundle
unrelated failures into one patch unless they target the same rule_hint and
the same missing decision. Separate mismatches → separate PatchCandidate
instances.

## 6. No Evaluator Rewrite
Do not revise the evaluator decision, evaluator explanation, expected answer,
or model output. Treat evaluation evidence as input evidence, not something
to correct. The patch modifies the prompt rules, not the ground truth.

## 7. No Speculative Patching
Do not patch for hypothetical future errors, general best practices, or
unsupported assumptions. Patch only failures demonstrated in the provided
evaluation context. If a case has ``case.expected == case.actual``, it must
be skipped (see Rule 2), not preemptively hardened.

## 8. Schema and Operation Preservation
Use only the current supported patch operations and fields: a single
``PatchOperation`` with ``op="add"`` targeting ``/evaluation_rules/{rule_hint}``
with an ``EvaluationRule`` payload. Do not add new operations, new fields,
new patch intents, or non-schema metadata. ``target_prompt_type`` is fixed
at ``"evaluation"``.

## 9. Output Contract Strictness
Return exactly the current required patch output format: a tuple of
``PatchCandidate`` objects with immutable ``patch_id``, ``title``,
``operations``, ``rationale``, ``source_case_ids``, and
``target_prompt_type="evaluation"``. Do not include Markdown, explanations
outside the dataclass fields, extra commentary, or fields not defined by the
current contract.

## 10. Confidence / Ambiguity Handling
If the evaluator evidence is insufficient to identify a safe prompt change
(no ``rule_hint``, no distinguishable expected vs actual, or the case would
require rewriting a rule that governs a known-correct sample), return no
patch for that failure or defer to the closest existing fallback according
to the current contract. Do not guess.

# Migration Note
This eval-patch-generation template has been enriched with the
evaluation-grounded patch generation framework inherited from the legacy
EVAL_PATCH_GENERATION_PROMPT.
- The frozen patch output contract, PatchCandidate dataclass, and
  PatchOperation op-set remain unchanged.
- The frozen evaluation prompt output schema / output format remain
  unchanged.
- Patch applier, validator, and optimizer loop are not modified.
- No unrelated template is affected.
"""


DEFAULT_EVAL_PATCH_GENERATION_OUTPUT_CONTRACT: dict[str, str] = {
    "target_prompt_type": "evaluation",
    "operation_op": "add",
    "operation_target": "/evaluation_rules/{rule_hint}",
    "patch_schema": "PatchCandidate(patch_id, title, operations, rationale, source_case_ids, target_prompt_type)",
}


def get_default_eval_patch_generation_template() -> str:
    """Return the evaluation-patch-generation rule template.

    This template adapts the legacy ``EVAL_PATCH_GENERATION_PROMPT``
    strategy into the current evaluation-prompt-optimizer flow. It is
    exposed as a module-level constant for introspection, tests, and
    future LLM-backed candidate generation.
    """
    return DEFAULT_EVAL_PATCH_GENERATION_TEMPLATE


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    input_text: str
    expected: str
    actual: str
    reason: str
    rule_hint: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BehaviorSuiteResult:
    fixed_cases: tuple[str, ...]
    broken_cases: tuple[str, ...]
    schema_violations: tuple[str, ...] = ()
    output_format_violations: tuple[str, ...] = ()


@dataclass(frozen=True)
class PatchDecision:
    candidate: PatchCandidate
    result: BehaviorSuiteResult
    reason: str = ""


@dataclass(frozen=True)
class OptimizationReport:
    accepted_patches: tuple[PatchDecision, ...]
    rejected_patches: tuple[PatchDecision, ...]
    fixed_eval_cases: tuple[str, ...]
    broken_eval_cases: tuple[str, ...]
    schema_violations: tuple[str, ...]
    output_format_violations: tuple[str, ...]


class EvaluationHarness(Protocol):
    def evaluate(self, prompt_ir: PromptIR, case: EvaluationCase) -> str:
        """Return the evaluator output for ``case`` under ``prompt_ir``."""


class RuleBasedEvaluationHarness:
    """Deterministic harness used for behavior-suite regression tests.

    A case is affected by a rule when the case's ``rule_hint`` matches the rule
    id. If no prompt rule matches, the case keeps its recorded ``actual`` value.
    This keeps the optimizer deterministic while allowing tests to verify that
    a generated rule fixes the intended mismatch without changing unrelated
    correct examples.
    """

    def evaluate(self, prompt_ir: PromptIR, case: EvaluationCase) -> str:
        for rule in prompt_ir.evaluation_rules:
            if case.rule_hint == rule.rule_id:
                return rule.decision
        return case.actual


class EvalPromptBehaviorSuite:
    """Checks that patches fix mismatches and preserve known-correct samples."""

    def __init__(self, correct_cases: tuple[EvaluationCase, ...], harness: EvaluationHarness | None = None) -> None:
        self.correct_cases = tuple(correct_cases)
        self.harness = harness or RuleBasedEvaluationHarness()

    def test(
        self,
        prompt_ir: PromptIR,
        mismatch_cases: tuple[EvaluationCase, ...],
        *,
        original_schema: dict[str, object],
        original_output_format: str,
    ) -> BehaviorSuiteResult:
        fixed_cases = tuple(
            case.case_id
            for case in mismatch_cases
            if self.harness.evaluate(prompt_ir, case) == case.expected
        )
        broken_cases = tuple(
            case.case_id
            for case in self.correct_cases
            if self.harness.evaluate(prompt_ir, case) != case.expected
        )
        schema_violations = () if dict(prompt_ir.output_schema) == original_schema else ("output_schema changed",)
        output_format_violations = () if prompt_ir.output_format == original_output_format else ("output_format changed",)
        return BehaviorSuiteResult(
            fixed_cases=fixed_cases,
            broken_cases=broken_cases,
            schema_violations=schema_violations,
            output_format_violations=output_format_violations,
        )


class EvaluationPromptOptimizer:
    """Generate, validate, apply, and test evaluation prompt patches."""

    def __init__(
        self,
        *,
        validator: PatchValidator | None = None,
        applier: PatchApplier | None = None,
        behavior_suite: EvalPromptBehaviorSuite | None = None,
    ) -> None:
        self.validator = validator or PatchValidator(target_prompt_type="evaluation")
        self.applier = applier or PatchApplier()
        self.behavior_suite = behavior_suite or EvalPromptBehaviorSuite(())

    def generate_patch_candidates(self, mismatch_cases: tuple[EvaluationCase, ...]) -> tuple[PatchCandidate, ...]:
        candidates: list[PatchCandidate] = []
        for case in mismatch_cases:
            if case.expected == case.actual:
                continue
            rule = EvaluationRule(
                rule_id=case.rule_hint,
                condition=case.reason,
                decision=case.expected,
                explanation=f"Generated from evaluator mismatch {case.case_id}: actual={case.actual!r}.",
            )
            candidates.append(
                PatchCandidate(
                    patch_id=f"eval-{case.case_id}-{case.rule_hint}",
                    title=f"Fix evaluation mismatch {case.case_id}",
                    operations=(PatchOperation("add", f"/evaluation_rules/{case.rule_hint}", rule),),
                    rationale=case.reason,
                    source_case_ids=(case.case_id,),
                    target_prompt_type="evaluation",
                )
            )
        return tuple(candidates)

    def optimize(
        self,
        prompt_version: PromptVersion,
        mismatch_cases: tuple[EvaluationCase, ...],
    ) -> tuple[PromptVersion, OptimizationReport]:
        if prompt_version.prompt_ir.prompt_type != "evaluation":
            raise ValueError("EvaluationPromptOptimizer requires prompt_type='evaluation'")

        current_version = prompt_version
        accepted: list[PatchDecision] = []
        rejected: list[PatchDecision] = []
        fixed_eval_cases: list[str] = []
        broken_eval_cases: list[str] = []
        schema_violations: list[str] = []
        output_format_violations: list[str] = []
        original_schema = dict(prompt_version.prompt_ir.output_schema)
        original_output_format = prompt_version.prompt_ir.output_format

        for candidate in self.generate_patch_candidates(mismatch_cases):
            validation = self.validator.validate(candidate)
            if not validation.valid:
                result = BehaviorSuiteResult(
                    fixed_cases=(),
                    broken_cases=(),
                    schema_violations=validation.schema_violations,
                    output_format_violations=validation.output_format_violations,
                )
                rejected.append(PatchDecision(candidate, result, "; ".join(validation.reasons)))
                schema_violations.extend(validation.schema_violations)
                output_format_violations.extend(validation.output_format_violations)
                continue

            patched_ir = self.applier.apply(current_version.prompt_ir, candidate)
            result = self.behavior_suite.test(
                patched_ir,
                mismatch_cases,
                original_schema=original_schema,
                original_output_format=original_output_format,
            )
            newly_fixed = tuple(case_id for case_id in result.fixed_cases if case_id in candidate.source_case_ids)
            if newly_fixed and not result.broken_cases and not result.schema_violations and not result.output_format_violations:
                current_version = current_version.bump(patched_ir, candidate.patch_id)
                accepted.append(PatchDecision(candidate, result, "accepted"))
                fixed_eval_cases.extend(case_id for case_id in result.fixed_cases if case_id not in fixed_eval_cases)
            else:
                reason = "no targeted mismatch fixed"
                if result.broken_cases:
                    reason = "behavior suite regression"
                elif result.schema_violations or result.output_format_violations:
                    reason = "frozen schema/output format changed"
                rejected.append(PatchDecision(candidate, result, reason))
                broken_eval_cases.extend(case_id for case_id in result.broken_cases if case_id not in broken_eval_cases)
                schema_violations.extend(result.schema_violations)
                output_format_violations.extend(result.output_format_violations)

        report = OptimizationReport(
            accepted_patches=tuple(accepted),
            rejected_patches=tuple(rejected),
            fixed_eval_cases=tuple(fixed_eval_cases),
            broken_eval_cases=tuple(broken_eval_cases),
            schema_violations=tuple(schema_violations),
            output_format_violations=tuple(output_format_violations),
        )
        return current_version, report
