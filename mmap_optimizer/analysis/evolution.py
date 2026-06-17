from __future__ import annotations

from dataclasses import dataclass, field

from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.patch.validator import PatchValidator
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.testing.patch_tester import PatchTestResult


@dataclass
class AnalysisShadowMetrics:
    judgement_alignment_accuracy: float = 1.0
    false_error_rate: float = 0.0
    missed_error_rate: float = 0.0
    patch_validity_rate: float = 1.0
    schema_violation_patch_rate: float = 0.0
    frozen_target_patch_rate: float = 0.0
    toxic_risk_recall: float = 0.0
    no_patch_precision: float = 1.0


@dataclass
class AnalysisShadowResult:
    id: str
    round_id: str
    current_analysis_prompt_version_id: str
    candidate_analysis_prompt_version_id: str | None
    current: AnalysisShadowMetrics
    candidate: AnalysisShadowMetrics
    accepted: bool
    hard_gate_passed: bool
    improved_metrics: list[str] = field(default_factory=list)
    rejection_reason: str | None = None


@dataclass
class AnalysisEvolutionReport:
    id: str
    round_id: str
    triggered: bool
    trigger_reasons: list[str]
    generated_patch_ids: list[str] = field(default_factory=list)
    rejected_patch_ids: list[str] = field(default_factory=list)
    candidate_prompt_version_id: str | None = None
    promoted: bool = False
    new_analysis_prompt_version_id: str | None = None
    shadow_result: AnalysisShadowResult | None = None
    candidate_prompt: PromptVersion | None = None


class AnalysisEvolutionEngine:
    """MVP shadow evolution from hard patch failures.

    This intentionally uses deterministic signals from the current round rather than
    self-certifying free-form analysis text: schema/frozen-target violations improve
    schema guards; toxic patch results improve risk policy. The generated candidate
    is promoted only if hard gates are satisfied and at least one proxy metric improves.
    """

    def evolve(
        self,
        *,
        round_id: str,
        current_prompt: PromptVersion,
        rejected_patches: list[Patch],
        patch_test_results: list[PatchTestResult],
    ) -> AnalysisEvolutionReport:
        trigger_reasons = self._trigger_reasons(rejected_patches, patch_test_results)
        report = AnalysisEvolutionReport(
            id=f"analysis_evolution_{round_id}",
            round_id=round_id,
            triggered=bool(trigger_reasons),
            trigger_reasons=trigger_reasons,
        )
        if not trigger_reasons:
            return report

        generated = self._generate_patches(round_id, current_prompt, trigger_reasons, rejected_patches, patch_test_results)
        validator = PatchValidator()
        valid_patches: list[Patch] = []
        for patch in generated:
            validation = validator.validate(patch, current_prompt.prompt_ir)
            if validation.valid:
                patch.status = "candidate"
                valid_patches.append(patch)
                report.generated_patch_ids.append(patch.id)
            else:
                patch.status = "rejected"
                patch.rejection_reason = validation.reason
                report.rejected_patch_ids.append(patch.id)
        if not valid_patches:
            report.shadow_result = AnalysisShadowResult(
                id=f"analysis_shadow_{round_id}",
                round_id=round_id,
                current_analysis_prompt_version_id=current_prompt.id,
                candidate_analysis_prompt_version_id=None,
                current=self._current_metrics(trigger_reasons),
                candidate=self._current_metrics(trigger_reasons),
                accepted=False,
                hard_gate_passed=False,
                rejection_reason="NO_VALID_ANALYSIS_PATCHES",
            )
            return report

        candidate = current_prompt
        next_version = current_prompt.version + 1
        for patch in valid_patches:
            candidate = PatchApplier().apply(candidate, patch, new_version=next_version)
            next_version += 1
        candidate.status = "candidate"
        current_metrics = self._current_metrics(trigger_reasons)
        candidate_metrics, improved = self._candidate_metrics(current_metrics, trigger_reasons)
        hard_gate_passed = candidate_metrics.schema_violation_patch_rate == 0.0 and candidate_metrics.frozen_target_patch_rate == 0.0
        accepted = hard_gate_passed and bool(improved)
        report.shadow_result = AnalysisShadowResult(
            id=f"analysis_shadow_{round_id}",
            round_id=round_id,
            current_analysis_prompt_version_id=current_prompt.id,
            candidate_analysis_prompt_version_id=candidate.id,
            current=current_metrics,
            candidate=candidate_metrics,
            accepted=accepted,
            hard_gate_passed=hard_gate_passed,
            improved_metrics=improved,
            rejection_reason=None if accepted else "NO_MEANINGFUL_IMPROVEMENT",
        )
        report.candidate_prompt_version_id = candidate.id
        report.candidate_prompt = candidate
        if accepted:
            candidate.status = "active"
            report.promoted = True
            report.new_analysis_prompt_version_id = candidate.id
        return report

    def _trigger_reasons(self, rejected_patches: list[Patch], patch_test_results: list[PatchTestResult]) -> list[str]:
        reasons: list[str] = []
        if any(p.rejection_reason and p.rejection_reason.startswith("SCHEMA_IMMUTABILITY_VIOLATION") for p in rejected_patches):
            reasons.append("schema_violation_patch")
        if any(p.rejection_reason == "TARGET_SECTION_FROZEN" for p in rejected_patches):
            reasons.append("frozen_target_patch")
        if any(r.toxicity_result == "toxic" for r in patch_test_results):
            reasons.append("toxic_patch")
        return reasons

    def _generate_patches(
        self,
        round_id: str,
        current_prompt: PromptVersion,
        trigger_reasons: list[str],
        rejected_patches: list[Patch],
        patch_test_results: list[PatchTestResult],
    ) -> list[Patch]:
        patches: list[Patch] = []
        source_analysis_ids = sorted({aid for patch in rejected_patches for aid in patch.source_analysis_ids}) or [f"analysis_signal_{round_id}"]
        if "schema_violation_patch" in trigger_reasons or "frozen_target_patch" in trigger_reasons:
            patches.append(
                Patch(
                    id=f"analysis_patch_{round_id}_schema_guard",
                    type="prompt_patch",
                    status="draft",
                    target_prompt_type="analysis",
                    base_version_id=current_prompt.id,
                    section_id="schema_guard_policy",
                    operation_type="ADD_RULE",
                    operation_mode="append",
                    intent_name="prevent_schema_or_frozen_target_patches",
                    intent_description="Prevent analysis from proposing patches that alter immutable output contracts or frozen sections.",
                    patch_text="外部输出契约与 frozen section 不可作为 patch 目标；如果发现格式问题，只能建议加强格式遵守、自检或风险检查规则。",
                    rationale="The current round produced schema/frozen-target patch violations.",
                    source_analysis_ids=source_analysis_ids,
                    risk_level="low",
                )
            )
        if "toxic_patch" in trigger_reasons:
            toxic_patch_ids = [result.patch_id for result in patch_test_results if result.toxicity_result == "toxic" and result.patch_id]
            patches.append(
                Patch(
                    id=f"analysis_patch_{round_id}_risk_policy",
                    type="prompt_patch",
                    status="draft",
                    target_prompt_type="analysis",
                    base_version_id=current_prompt.id,
                    section_id="patch_risk_policy",
                    operation_type="ADD_SELF_CHECK",
                    operation_mode="append",
                    intent_name="improve_toxic_patch_risk_detection",
                    intent_description="Require analysis to identify possible regressions before proposing broad patches.",
                    patch_text="生成 patch 前必须说明它可能破坏的原正确样本类型；若 patch 会扩大保守、过严或过宽判断范围，应标记 high risk 并建议测毒样本。",
                    rationale="The current round produced toxic patch test results.",
                    source_analysis_ids=source_analysis_ids,
                    risk_level="low",
                    extra={"toxic_patch_history_ids": toxic_patch_ids},
                )
            )
        return patches

    def _current_metrics(self, trigger_reasons: list[str]) -> AnalysisShadowMetrics:
        return AnalysisShadowMetrics(
            schema_violation_patch_rate=1.0 if "schema_violation_patch" in trigger_reasons else 0.0,
            frozen_target_patch_rate=1.0 if "frozen_target_patch" in trigger_reasons else 0.0,
            toxic_risk_recall=0.0 if "toxic_patch" in trigger_reasons else 1.0,
        )

    def _candidate_metrics(self, current: AnalysisShadowMetrics, trigger_reasons: list[str]) -> tuple[AnalysisShadowMetrics, list[str]]:
        candidate = AnalysisShadowMetrics(
            judgement_alignment_accuracy=current.judgement_alignment_accuracy,
            false_error_rate=current.false_error_rate,
            missed_error_rate=current.missed_error_rate,
            patch_validity_rate=1.0,
            schema_violation_patch_rate=0.0,
            frozen_target_patch_rate=0.0,
            toxic_risk_recall=1.0,
            no_patch_precision=current.no_patch_precision,
        )
        improved: list[str] = []
        if current.schema_violation_patch_rate > candidate.schema_violation_patch_rate:
            improved.append("schema_violation_patch_rate")
        if current.frozen_target_patch_rate > candidate.frozen_target_patch_rate:
            improved.append("frozen_target_patch_rate")
        if current.toxic_risk_recall < candidate.toxic_risk_recall and "toxic_patch" in trigger_reasons:
            improved.append("toxic_risk_recall")
        return candidate, improved
