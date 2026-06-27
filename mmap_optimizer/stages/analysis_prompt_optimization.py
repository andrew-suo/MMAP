"""Analysis Prompt Optimization Stage。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..core.logging import get_logger, log_stage
from ..core.progress import NullProgressReporter, ProgressReporter
from ..patch.types import (
    AnalysisPatch,
    CompressionReport,
    PatchMergeReport,
    SemanticPatchDraft,
    ToxicityReport,
)
from ..data.sample import (
    SampleBatch,
    SampleOutcomeHistoryItem,
    SamplePatchAttempt,
    SampleSet,
    SampleTrace,
)
from ..prompt.structured_prompt import StructuredPrompt
from ..prompt.section_contribution import SectionContributionTracker
from .extraction_prompt_optimization import AnalysisResult, ExtractionResult


@dataclass
class ReflectionResult:
    """反思结果。"""
    sample_id: str
    reflection_success: bool
    error_reason: str | None = None
    patch_suggestion: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "sample_id": self.sample_id,
            "reflection_success": self.reflection_success,
            "error_reason": self.error_reason,
            "patch_suggestion": self.patch_suggestion,
            "notes": list(self.notes),
        }


@dataclass
class AnalysisMetrics:
    """Analysis Prompt 指标。"""
    base_accuracy: float | None = None
    final_accuracy: float | None = None
    base_correct_count: int = 0
    base_wrong_count: int = 0
    final_correct_count: int = 0
    final_wrong_count: int = 0
    accepted_patch_count: int = 0
    rejected_patch_count: int = 0
    compression_accepted: bool = False
    no_progress: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "base_accuracy": self.base_accuracy,
            "final_accuracy": self.final_accuracy,
            "base_correct_count": self.base_correct_count,
            "base_wrong_count": self.base_wrong_count,
            "final_correct_count": self.final_correct_count,
            "final_wrong_count": self.final_wrong_count,
            "accepted_patch_count": self.accepted_patch_count,
            "rejected_patch_count": self.rejected_patch_count,
            "compression_accepted": self.compression_accepted,
            "no_progress": self.no_progress,
        }


class AnalysisPromptOptimizationStage:
    """Analysis Prompt Optimization Stage。"""

    def __init__(
        self,
        analysis_prompt: StructuredPrompt,
        extraction_results: list[ExtractionResult],
        base_analysis_results: list[AnalysisResult],
        sample_set: SampleSet,
        batch: SampleBatch,
        iteration: int,
        analysis_executor=None,
        patch_generation_executor=None,
        patch_apply_executor=None,
        extraction_prompt=None,
        merge_executor=None,
        toxicity_test_executor=None,
        compression_executor=None,
        line_limit: int = 250,
        char_limit: int = 16000,
        compression_enabled: bool = True,
        ema_alpha: float = 0.3,
        progress_reporter: ProgressReporter | None = None,
    ):
        self.analysis_prompt = analysis_prompt
        self.extraction_results = extraction_results
        self.base_analysis_results = base_analysis_results
        self.sample_set = sample_set
        self.batch = batch
        self.iteration = iteration
        self.analysis_executor = analysis_executor
        self.patch_generation_executor = patch_generation_executor
        self.patch_apply_executor = patch_apply_executor
        self.extraction_prompt = extraction_prompt
        self.merge_executor = merge_executor
        self.toxicity_test_executor = toxicity_test_executor
        self.compression_executor = compression_executor
        self.line_limit = line_limit
        self.char_limit = char_limit
        self.compression_enabled = compression_enabled
        self.ema_alpha = ema_alpha
        self.progress = progress_reporter or NullProgressReporter()
        self.logger = get_logger(__name__)

        self.reflection_results: list[ReflectionResult] = []
        self.draft_patches: list[AnalysisPatch] = []
        self.validated_patches: list[AnalysisPatch] = []
        self.rejected_patches: list[AnalysisPatch] = []
        self.initial_merged_patches: list[AnalysisPatch] = []
        self.patched_analysis_results: list[AnalysisResult] = []
        self.final_merged_patches: list[AnalysisPatch] = []
        self.final_analysis_results: list[AnalysisResult] = []

        self.ineffective_patches: list[AnalysisPatch] = []
        self.safe_patches: list[AnalysisPatch] = []
        self.toxic_patches: list[AnalysisPatch] = []
        self.final_prompt: StructuredPrompt | None = None

        self.patched_prompt: StructuredPrompt | None = None
        self.patch_apply_report = None
        self.accepted_prompt: StructuredPrompt | None = None
        self.trial_prompt: StructuredPrompt | None = None

        self.metrics = AnalysisMetrics()

        self.initial_merge_report: PatchMergeReport | None = None
        self.final_merge_report: PatchMergeReport | None = None
        self.toxicity_report: ToxicityReport | None = None
        self.compression_report: CompressionReport | None = None
        self.transition_report: dict[str, Any] | None = None
        self.semantic_patch_drafts: list[SemanticPatchDraft] = []
        self.translated_patches: list[AnalysisPatch] = []
        self.model_output_repairs: list[dict[str, Any]] = []

        # Section 贡献度追踪（EMA）
        self.contribution_tracker = SectionContributionTracker(alpha=0.3)

    def run(self) -> AnalysisMetrics:
        """执行完整的 Analysis Prompt Optimization Stage。"""
        log_stage(self.logger, "analysis_stage_start", iteration=self.iteration, samples=len(self.batch.sample_ids))
        self.progress.step("  [Analysis 1/8] 统计基础分析准确率...")
        self._step1_compute_base_metrics()
        if self.metrics.base_accuracy is not None:
            self.progress.step(f"  [Analysis 1/8] 基础评估完成，准确率: {self.metrics.base_accuracy:.2%}")

        # 更新 section 贡献度追踪
        self._update_contribution_tracker()

        self.progress.step("  [Analysis 2/8] 反思分析错误...")
        self._step2_reflect_on_errors()

        self._step3_generate_patches()
        self.progress.step(f"  [Analysis 3/8] 生成 patch（{len(self.draft_patches)} 个）...")

        self._step4_initial_merge()
        self.progress.step(f"  [Analysis 4/8] 合并 patch（{len(self.initial_merged_patches)} 个）...")

        self.progress.step("  [Analysis 5/8] 应用 patch 并回归测试...")
        self._step5_apply_and_test()

        self.progress.step("  [Analysis 6/8] 测毒验证...")
        self._step6_regression_and_toxicity_test()

        self.progress.step("  [Analysis 7/8] 压缩 prompt...")
        self._step7_compress_if_needed()

        self.progress.step("  [Analysis 8/8] 生成最终结果...")
        self._step8_final_test_and_metrics()
        log_stage(
            self.logger,
            "analysis_stage_done",
            iteration=self.iteration,
            base_accuracy=self.metrics.base_accuracy,
            final_accuracy=self.metrics.final_accuracy,
            accepted_patches=self.metrics.accepted_patch_count,
            rejected_patches=self.metrics.rejected_patch_count,
            no_progress=self.metrics.no_progress,
        )

        return self.metrics

    def _step1_compute_base_metrics(self) -> None:
        """Step 1: 统计分析准确率。"""
        correct_count = sum(1 for r in self.base_analysis_results if r.analysis_correct)
        wrong_count = sum(1 for r in self.base_analysis_results if not r.analysis_correct)
        total = len(self.base_analysis_results)

        self.metrics.base_correct_count = correct_count
        self.metrics.base_wrong_count = wrong_count
        self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

    def _update_contribution_tracker(self) -> None:
        """从分析结果更新 section 贡献度追踪器。"""
        batch_attribution: dict[str, list[dict]] = {}
        batch_results: dict[str, bool] = {}

        for result in self.base_analysis_results:
            judgement = result.judgement if isinstance(result.judgement, dict) else {}
            attribution = judgement.get("prompt_section_attribution", [])
            if isinstance(attribution, list):
                batch_attribution[result.sample_id] = attribution
            batch_results[result.sample_id] = result.analysis_correct

        if batch_results:
            self.contribution_tracker.update(batch_attribution, batch_results)

    def _step2_reflect_on_errors(self) -> None:
        """Step 2: 对分析错误样本反思。"""
        if self.analysis_executor is not None and hasattr(self.analysis_executor, "model_output_repairs"):
            self.analysis_executor.model_output_repairs = []

        wrong_analysis_ids = [
            r.sample_id for r in self.base_analysis_results
            if not r.analysis_correct
        ]

        for sample_id in wrong_analysis_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            extraction_result = next(
                (r for r in self.extraction_results if r.sample_id == sample_id),
                None
            )
            if extraction_result is None:
                continue

            base_analysis = next(
                (r for r in self.base_analysis_results if r.sample_id == sample_id),
                None
            )
            if base_analysis is None:
                continue

            if self.analysis_executor is not None:
                try:
                    reflection = self.analysis_executor.reflect(
                        self.analysis_prompt,
                        extraction_result,
                        base_analysis,
                        spec,
                        self.sample_set,
                    )
                except TypeError:
                    reflection = self.analysis_executor.reflect(
                        self.analysis_prompt,
                        extraction_result,
                        base_analysis,
                        spec,
                    )
            else:
                reflection = ReflectionResult(
                    sample_id=sample_id,
                    reflection_success=True,
                    error_reason="Mock reflection: analysis misjudged",
                    patch_suggestion={
                        "target_section": "section_1",
                        "operation": "replace",
                        "content": "Mock analysis patch content",
                    },
                )
            self.reflection_results.append(reflection)
            state = self.sample_set.states.get(sample_id)
            if state is not None:
                trajectory = state.get_or_create_trajectory("analysis", self.iteration)
                trajectory.base_status = "pass" if base_analysis.analysis_correct else "fail"
                trajectory.analysis_summary = {
                    "analysis_correct": base_analysis.analysis_correct,
                    "error_reason": base_analysis.error_reason,
                    "confirmed_facts": list(base_analysis.confirmed_facts),
                    "hypothesized_error_causes": list(base_analysis.hypothesized_error_causes),
                }
                trajectory.reflection_summary = {
                    "reflection_success": reflection.reflection_success,
                    "error_reason": reflection.error_reason,
                    "patch_suggestion": reflection.patch_suggestion,
                    "notes": list(reflection.notes),
                }

            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == sample_id:
                    trace.reflection_result_id = reflection.sample_id
                    trace.reflection_success = reflection.reflection_success
        if self.analysis_executor is not None:
            self.model_output_repairs.extend(getattr(
                self.analysis_executor, "model_output_repairs", []
            ))

    def _step3_generate_patches(self) -> None:
        """Step 3: 生成 analysis prompt patch。"""
        if self.patch_generation_executor is not None:
            draft_patches, validated_patches, rejected_patches = (
                self.patch_generation_executor.generate_analysis_patches(
                    reflection_results=self.reflection_results,
                    analysis_prompt=self.analysis_prompt,
                    sample_set=self.sample_set,
                )
            )
            self.draft_patches = draft_patches
            self.validated_patches = validated_patches
            self.rejected_patches = rejected_patches
            self.semantic_patch_drafts = list(getattr(
                self.patch_generation_executor, "semantic_patch_drafts", []
            ))
            self.translated_patches = list(getattr(
                self.patch_generation_executor, "translated_patches", []
            ))
            self.model_output_repairs.extend(getattr(
                self.patch_generation_executor, "model_output_repairs", []
            ))

            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for patch in self.draft_patches:
                for trace in traces:
                    if trace.sample_id in patch.source_sample_ids:
                        trace.generated_analysis_patch_ids.append(patch.id)
            self._record_generated_patch_attempts()
            return

        for reflection in self.reflection_results:
            if not reflection.reflection_success or reflection.patch_suggestion is None:
                continue

            suggestion = reflection.patch_suggestion
            patch = AnalysisPatch(
                id=f"patch_analysis_{reflection.sample_id}",
                target_section_id=suggestion.get("target_section", "section_1"),
                operation_type=suggestion.get("op", "append_to_section"),
                content=suggestion.get("content", "Mock analysis patch content"),
                rationale=f"Based on reflection for sample {reflection.sample_id}",
                source_sample_ids=[reflection.sample_id],
                status="draft",
            )
            self.draft_patches.append(patch)

            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == reflection.sample_id:
                    trace.generated_analysis_patch_ids.append(patch.id)
        self._record_generated_patch_attempts()

    def _record_generated_patch_attempts(self) -> None:
        """记录当前 sample 触发生成过的 analysis patch，包括校验失败。"""
        patch_by_id = {patch.id: patch for patch in self.draft_patches}
        validated_ids = {patch.id for patch in self.validated_patches}
        rejected_ids = {patch.id for patch in self.rejected_patches}
        for patch in self.draft_patches + self.rejected_patches:
            if patch.id in patch_by_id and patch is not patch_by_id[patch.id]:
                continue
            validation_status = "validated" if patch.id in validated_ids else "unknown"
            if patch.id in rejected_ids or getattr(patch, "status", None) == "rejected":
                validation_status = "rejected"
            for sample_id in getattr(patch, "source_sample_ids", []):
                state = self.sample_set.states.get(sample_id)
                if state is None:
                    continue
                trajectory = state.get_or_create_trajectory("analysis", self.iteration)
                trajectory.add_patch_attempt(
                    self._build_patch_attempt(
                        patch=patch,
                        generation_status="generated",
                        validation_status=validation_status,
                        merge_status="not_merged",
                        final_decision="rejected" if validation_status == "rejected" else "unknown",
                    )
                )

    def _build_patch_attempt(
        self,
        patch: AnalysisPatch,
        generation_status: str = "generated",
        validation_status: str = "unknown",
        merge_status: str = "unknown",
        regression_effect: str = "unknown",
        toxicity_status: str = "not_tested",
        final_decision: str = "unknown",
        evidence_scope: str = "sample",
    ) -> SamplePatchAttempt:
        metadata = dict(getattr(patch, "metadata", {}))
        return SamplePatchAttempt(
            patch_id=patch.id,
            prompt_type="analysis",
            iteration=self.iteration,
            target_section_id=patch.target_section_id,
            operation_type=patch.operation_type,
            direction=str(metadata.get("source_reason") or patch.rationale or "")[:500],
            content=patch.content[:800],
            rationale=patch.rationale[:800],
            generation_status=generation_status,
            validation_status=validation_status,
            merge_status=merge_status,
            regression_effect=regression_effect,
            toxicity_status=toxicity_status,
            final_decision=final_decision,
            rejection_reason=getattr(patch, "rejection_reason", None),
            evidence_scope=evidence_scope,
            metadata={
                "semantic_draft_id": metadata.get("semantic_draft_id"),
                "translation_status": metadata.get("translation_status"),
                "source_phase": metadata.get("source_phase"),
            },
        )

    def _step4_initial_merge(self) -> None:
        """Step 4: Tree Merge 生成 analysis patch。"""
        if self.merge_executor is not None:
            merged_patches, merge_report = self.merge_executor.merge(
                patches=self.validated_patches,
                prompt=self.analysis_prompt,
                merge_strategy="tree_merge",
                sample_set=self.sample_set,
            )
            self.initial_merged_patches = merged_patches
            self.initial_merge_report = merge_report
            self._record_initial_merge_outcomes()
            return

        if self.patch_generation_executor is not None:
            self.initial_merged_patches = self.validated_patches.copy()

            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_analysis_initial_{self.iteration}",
                input_patch_count=len(self.draft_patches),
                merged_patch_count=len(self.initial_merged_patches),
                conflict_count=0,
                merged_patches=[p.to_dict() for p in self.initial_merged_patches],
                metadata={"merge_strategy": "passthrough"},
            )
            self._record_initial_merge_outcomes()
            return

        if not self.draft_patches:
            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_analysis_initial_{self.iteration}",
                input_patch_count=0,
                merged_patch_count=0,
                conflict_count=0,
            )
            return

        self.initial_merged_patches = self.draft_patches.copy()
        for patch in self.initial_merged_patches:
            patch.status = "merged"

        self.initial_merge_report = PatchMergeReport(
            id=f"merge_report_analysis_initial_{self.iteration}",
            input_patch_count=len(self.draft_patches),
            merged_patch_count=len(self.initial_merged_patches),
            conflict_count=0,
            merged_patches=[p.to_dict() for p in self.initial_merged_patches],
        )
        self._record_initial_merge_outcomes()

    def _step5_apply_and_test(self) -> None:
        """Step 5: 应用 analysis patch 并回归测试。"""
        if self.patch_apply_executor is not None and self.initial_merged_patches:
            trial_prompt, apply_report = self.patch_apply_executor.apply(
                self.analysis_prompt, self.initial_merged_patches
            )
            self.trial_prompt = trial_prompt
            self.patched_prompt = trial_prompt
            self.patch_apply_report = apply_report

            if not apply_report.changed:
                self.metrics.no_progress = True
                self._mark_apply_no_change()
                return

            if self.analysis_executor is not None:
                self.patched_analysis_results = self.analysis_executor.execute_batch(
                    analysis_prompt=trial_prompt,
                    extraction_prompt=self.extraction_prompt,
                    extraction_results=self.extraction_results,
                    sample_set=self.sample_set,
                )
            return

        if not self.initial_merged_patches:
            self.metrics.no_progress = True
            return

        for extraction_result in self.extraction_results:
            analysis_result = AnalysisResult(
                sample_id=extraction_result.sample_id,
                judgement={"mock": "patched_judgement"},
                analysis_correct=True,
            )
            self.patched_analysis_results.append(analysis_result)

    def _step6_regression_and_toxicity_test(self) -> None:
        """Step 6: 回归分析、无效剔除与测毒。"""
        if (
            self.patch_apply_report is not None
            and getattr(self.patch_apply_report, "changed", True) is False
        ):
            return
        if self.patch_apply_executor is not None and self.toxicity_test_executor is not None:
            base_analysis_map = {r.sample_id: r for r in self.base_analysis_results}
            patched_analysis_map = {r.sample_id: r for r in self.patched_analysis_results}

            fixed_ids: list[str] = []
            broken_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base = base_analysis_map.get(sample_id)
                patched = patched_analysis_map.get(sample_id)
                if base is None or patched is None:
                    continue
                if not base.analysis_correct and patched.analysis_correct:
                    fixed_ids.append(sample_id)
                elif base.analysis_correct and not patched.analysis_correct:
                    broken_ids.append(sample_id)
                elif not base.analysis_correct and not patched.analysis_correct:
                    unchanged_wrong_ids.append(sample_id)
                else:
                    unchanged_correct_ids.append(sample_id)

            toxic_sample_ids = broken_ids

            safe_patches, toxic_patches, toxicity_report = self.toxicity_test_executor.test(
                base_prompt=self.analysis_prompt,
                candidate_patches=self.initial_merged_patches,
                toxic_sample_ids=toxic_sample_ids,
                sample_set=self.sample_set,
                mode="analysis",
                early_stop=True,
                analysis_executor=self.analysis_executor,
                extraction_prompt=self.extraction_prompt,
                extraction_results=self.extraction_results,
                unchanged_wrong_sample_ids=unchanged_wrong_ids,
                sample_states=self.sample_set.states,
            )

            self.safe_patches = safe_patches
            self.toxic_patches = toxic_patches
            self.toxicity_report = toxicity_report

            self.ineffective_patches = [
                p for p in self.initial_merged_patches
                if p.status == "rejected" and getattr(p, "rejection_reason", None) == "INEFFECTIVE"
            ]

            self.transition_report = {
                "fixed_sample_ids": list(fixed_ids),
                "broken_sample_ids": list(broken_ids),
                "unchanged_wrong_ids": list(unchanged_wrong_ids),
                "unchanged_correct_ids": list(unchanged_correct_ids),
                "toxic_sample_ids": list(toxic_sample_ids),
            }

            if safe_patches and self.merge_executor is not None:
                final_merged_patches, final_merge_report = self.merge_executor.merge(
                    patches=safe_patches,
                    prompt=self.analysis_prompt,
                    merge_strategy="tree_merge",
                    sample_set=self.sample_set,
                )
                self.final_merged_patches = final_merged_patches
                self.final_merge_report = final_merge_report
            elif safe_patches:
                self.final_merged_patches = safe_patches.copy()
                self.final_merge_report = PatchMergeReport(
                    id=f"merge_report_analysis_final_{self.iteration}",
                    input_patch_count=len(safe_patches),
                    merged_patch_count=len(safe_patches),
                    conflict_count=0,
                    strategy="passthrough",
                    fallback_used=True,
                )
            else:
                self.final_merged_patches = []

            if self.final_merged_patches:
                final_prompt, final_apply_report = self.patch_apply_executor.apply(
                    self.analysis_prompt, self.final_merged_patches
                )
                self.final_prompt = final_prompt
                self.accepted_prompt = final_prompt
                for patch in self.final_merged_patches:
                    patch.status = "accepted"
            else:
                self.final_prompt = None
                self.accepted_prompt = None
                self.metrics.no_progress = True

            self.metrics.accepted_patch_count = len(self.final_merged_patches)
            self.metrics.rejected_patch_count = (
                len(self.rejected_patches) + len(toxic_patches)
            )

            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for trace in traces:
                if trace.sample_id in fixed_ids:
                    trace.transition = "fixed"
                elif trace.sample_id in broken_ids:
                    trace.transition = "broken"
                elif trace.sample_id in unchanged_wrong_ids:
                    trace.transition = "unchanged_wrong"
                else:
                    trace.transition = "unchanged_correct"
            self._record_sample_patch_attempts(
                patches=self.initial_merged_patches,
                fixed_sample_ids=fixed_ids,
                broken_sample_ids=broken_ids,
                unchanged_wrong_ids=unchanged_wrong_ids,
                unchanged_correct_ids=unchanged_correct_ids,
            )
            return

        if self.patch_apply_executor is not None:
            base_analysis_map = {r.sample_id: r for r in self.base_analysis_results}
            patched_analysis_map = {r.sample_id: r for r in self.patched_analysis_results}

            fixed_ids: list[str] = []
            broken_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base = base_analysis_map.get(sample_id)
                patched = patched_analysis_map.get(sample_id)

                if base is None or patched is None:
                    continue

                if not base.analysis_correct and patched.analysis_correct:
                    fixed_ids.append(sample_id)
                elif base.analysis_correct and not patched.analysis_correct:
                    broken_ids.append(sample_id)
                elif not base.analysis_correct and not patched.analysis_correct:
                    unchanged_wrong_ids.append(sample_id)
                else:
                    unchanged_correct_ids.append(sample_id)

            patched_correct = sum(
                1 for r in self.patched_analysis_results if r.analysis_correct
            )
            patched_total = len(self.patched_analysis_results)
            patched_accuracy = (
                patched_correct / patched_total if patched_total > 0 else 0.0
            )
            base_accuracy = self.metrics.base_accuracy or 0.0

            if broken_ids:
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "TOXIC"
                self.final_merged_patches = []
            elif not fixed_ids:
                self.metrics.no_progress = True
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "INEFFECTIVE"
                self.final_merged_patches = []
            elif patched_accuracy >= base_accuracy:
                self.accepted_prompt = self.trial_prompt
                self.final_merged_patches = self.initial_merged_patches.copy()
                for patch in self.final_merged_patches:
                    patch.status = "accepted"
            else:
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "REGRESSION"
                self.final_merged_patches = []

            self.metrics.accepted_patch_count = len(self.final_merged_patches)
            self.metrics.rejected_patch_count = (
                len(self.initial_merged_patches) - len(self.final_merged_patches)
            )

            toxic_patch_ids = (
                [p.id for p in self.initial_merged_patches] if broken_ids else []
            )
            safe_patch_ids = (
                [p.id for p in self.final_merged_patches]
                if self.accepted_prompt is not None
                else []
            )
            self.toxicity_report = ToxicityReport(
                id=f"toxicity_report_analysis_{self.iteration}",
                tested_patch_count=len(self.initial_merged_patches),
                toxic_patch_count=len(toxic_patch_ids),
                safe_patch_count=len(safe_patch_ids),
                toxic_patches=toxic_patch_ids,
                safe_patches=safe_patch_ids,
                toxic_sample_ids=broken_ids,
            )

            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for trace in traces:
                if trace.sample_id in fixed_ids:
                    trace.transition = "fixed"
                elif trace.sample_id in broken_ids:
                    trace.transition = "broken"
                elif trace.sample_id in unchanged_wrong_ids:
                    trace.transition = "unchanged_wrong"
                else:
                    trace.transition = "unchanged_correct"
            self._record_sample_patch_attempts(
                patches=self.initial_merged_patches,
                fixed_sample_ids=fixed_ids,
                broken_sample_ids=broken_ids,
                unchanged_wrong_ids=unchanged_wrong_ids,
                unchanged_correct_ids=unchanged_correct_ids,
            )
            return

        if not self.initial_merged_patches:
            return

        base_analysis_map = {r.sample_id: r for r in self.base_analysis_results}
        patched_analysis_map = {r.sample_id: r for r in self.patched_analysis_results}

        fixed_ids: list[str] = []
        broken_ids: list[str] = []
        unchanged_wrong_ids: list[str] = []
        unchanged_correct_ids: list[str] = []

        for sample_id in self.batch.sample_ids:
            base = base_analysis_map.get(sample_id)
            patched = patched_analysis_map.get(sample_id)

            if base is None or patched is None:
                continue

            if not base.analysis_correct and patched.analysis_correct:
                fixed_ids.append(sample_id)
            elif base.analysis_correct and not patched.analysis_correct:
                broken_ids.append(sample_id)
            elif not base.analysis_correct and not patched.analysis_correct:
                unchanged_wrong_ids.append(sample_id)
            else:
                unchanged_correct_ids.append(sample_id)

        for patch in self.initial_merged_patches:
            if all(sid in unchanged_wrong_ids for sid in patch.source_sample_ids):
                patch.status = "rejected"
                patch.rejection_reason = "INEFFECTIVE"

        toxic_sample_ids = broken_ids

        remaining_patches = [
            p for p in self.initial_merged_patches
            if p.status not in ["rejected"]
        ]

        safe_patches: list[AnalysisPatch] = []
        toxic_patches: list[AnalysisPatch] = []

        for patch in remaining_patches:
            patch.status = "candidate_safe"
            safe_patches.append(patch)

        self.final_merged_patches = safe_patches.copy()
        for patch in self.final_merged_patches:
            patch.status = "accepted"

        self.metrics.accepted_patch_count = len(self.final_merged_patches)
        self.metrics.rejected_patch_count = len([
            p for p in self.initial_merged_patches if p.status == "rejected"
        ])

        self.toxicity_report = ToxicityReport(
            id=f"toxicity_report_analysis_{self.iteration}",
            tested_patch_count=len(remaining_patches),
            toxic_patch_count=len(toxic_patches),
            safe_patch_count=len(safe_patches),
            toxic_patches=[p.id for p in toxic_patches],
            safe_patches=[p.id for p in safe_patches],
            toxic_sample_ids=toxic_sample_ids,
        )

        self._record_sample_patch_attempts(
            patches=self.initial_merged_patches,
            fixed_sample_ids=fixed_ids,
            broken_sample_ids=broken_ids,
            unchanged_wrong_ids=unchanged_wrong_ids,
            unchanged_correct_ids=unchanged_correct_ids,
        )

    def _record_sample_patch_attempts(
        self,
        patches: list[AnalysisPatch],
        fixed_sample_ids: list[str],
        broken_sample_ids: list[str],
        unchanged_wrong_ids: list[str],
        unchanged_correct_ids: list[str],
    ) -> None:
        """把本轮 analysis patch 的最终结果写入 source sample 轨迹。"""
        transition_by_sample = self._transition_map(
            fixed_sample_ids=fixed_sample_ids,
            broken_sample_ids=broken_sample_ids,
            unchanged_wrong_ids=unchanged_wrong_ids,
            unchanged_correct_ids=unchanged_correct_ids,
        )
        final_patch_ids = {patch.id for patch in self.final_merged_patches}
        safe_patch_ids = {patch.id for patch in self.safe_patches}
        toxic_patch_ids = {patch.id for patch in self.toxic_patches}
        rejected_patch_ids = {patch.id for patch in self.rejected_patches}
        test_record_by_patch = self._toxicity_test_record_map()
        for patch in patches:
            for sample_id in patch.source_sample_ids:
                state = self.sample_set.states.get(sample_id)
                if state is None:
                    continue
                final_decision = self._patch_final_decision(patch)
                if patch.id not in final_patch_ids and final_decision == "accepted":
                    final_decision = "dropped"
                toxicity = self._patch_toxicity(patch, final_decision)
                if toxicity == "safe":
                    toxicity = "tested_safe"
                if patch.id in safe_patch_ids and toxicity == "not_tested":
                    toxicity = "tested_safe"
                if patch.id in toxic_patch_ids:
                    toxicity = "toxic"
                record = test_record_by_patch.get(patch.id, {})
                if record.get("status") == "skipped":
                    toxicity = "skipped_no_toxic_samples"
                trajectory = state.get_or_create_trajectory("analysis", self.iteration)
                attempt = self._build_patch_attempt(
                    patch=patch,
                    validation_status="validated" if patch.id not in rejected_patch_ids else "rejected",
                    merge_status="final_merged" if patch.id in final_patch_ids else (
                        "initial_merged" if patch in self.initial_merged_patches else "not_merged"
                    ),
                    regression_effect=transition_by_sample.get(sample_id, "unknown"),
                    toxicity_status=toxicity,
                    final_decision=final_decision,
                    evidence_scope="batch",
                )
                attempt.tested_sample_ids = [str(sid) for sid in record.get("tested_sample_ids", [])]
                attempt.broken_sample_ids = [str(sid) for sid in record.get("broken_sample_ids", [])]
                attempt.fixed_sample_ids = [str(sid) for sid in record.get("fixed_sample_ids", [])]
                attempt.stop_reason = record.get("stop_reason")
                trajectory.add_patch_attempt(attempt)
                state.generated_analysis_patch_count += 1

    def _record_initial_merge_outcomes(self) -> None:
        """把 validated patch 在 initial merge 阶段的消费结果写回轨迹。"""
        merged_ids = {patch.id for patch in self.initial_merged_patches}
        dropped_ids = set(getattr(self.initial_merge_report, "dropped_patch_ids", []) or [])
        for patch in self.validated_patches:
            if patch.id in merged_ids:
                merge_status = "initial_merged"
                final_decision = "unknown"
            else:
                merge_status = "not_merged"
                final_decision = "dropped"
                if patch.id in dropped_ids and patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED":
                    final_decision = "rejected"
            if patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED":
                merge_status = "not_merged"
                final_decision = "rejected"
            for sample_id in patch.source_sample_ids:
                state = self.sample_set.states.get(sample_id)
                if state is None:
                    continue
                trajectory = state.get_or_create_trajectory("analysis", self.iteration)
                trajectory.add_patch_attempt(
                    self._build_patch_attempt(
                        patch=patch,
                        validation_status="validated",
                        merge_status=merge_status,
                        final_decision=final_decision,
                        evidence_scope="batch",
                    )
                )

    def _mark_apply_no_change(self) -> None:
        """Apply 没有修改 prompt 时，终止当前 patch 消费并写回轨迹。"""
        self.accepted_prompt = None
        self.final_prompt = None
        self.final_merged_patches = []
        self.safe_patches = []
        self.toxic_patches = []
        for patch in self.initial_merged_patches:
            patch.status = "rejected"
            patch.rejection_reason = "APPLY_NO_CHANGE"
        self.metrics.accepted_patch_count = 0
        self.metrics.rejected_patch_count = (
            len(self.rejected_patches) + len(self.initial_merged_patches)
        )
        self._record_sample_patch_attempts(
            patches=self.initial_merged_patches,
            fixed_sample_ids=[],
            broken_sample_ids=[],
            unchanged_wrong_ids=[],
            unchanged_correct_ids=[],
        )

    def _toxicity_test_record_map(self) -> dict[str, dict[str, Any]]:
        if self.toxicity_report is None:
            return {}
        records = getattr(self.toxicity_report, "patch_test_records", []) or []
        record_map: dict[str, dict[str, Any]] = {}
        for record in records:
            if isinstance(record, dict):
                patch_id = str(record.get("patch_id", ""))
                if patch_id:
                    record_map[patch_id] = record
        return record_map

    def _transition_map(
        self,
        fixed_sample_ids: list[str],
        broken_sample_ids: list[str],
        unchanged_wrong_ids: list[str],
        unchanged_correct_ids: list[str],
    ) -> dict[str, str]:
        transition_by_sample = {sid: "fixed" for sid in fixed_sample_ids}
        transition_by_sample.update({sid: "broken" for sid in broken_sample_ids})
        transition_by_sample.update({sid: "unchanged_wrong" for sid in unchanged_wrong_ids})
        transition_by_sample.update({sid: "unchanged_correct" for sid in unchanged_correct_ids})
        return transition_by_sample

    def _patch_final_decision(self, patch: AnalysisPatch) -> str:
        if patch.rejection_reason == "TOXIC":
            return "toxic"
        if patch.rejection_reason == "INEFFECTIVE":
            return "ineffective"
        if patch.rejection_reason == "APPLY_NO_CHANGE":
            return "ineffective"
        if patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED":
            return "rejected"
        if patch.rejection_reason == "REGRESSION":
            return "rejected"
        if patch.status == "accepted":
            return "accepted"
        if patch.status == "candidate_safe":
            return "accepted"
        if patch.status == "rejected":
            return "rejected"
        return patch.status or "unknown"

    def _patch_toxicity(self, patch: AnalysisPatch, final_decision: str) -> str:
        if final_decision == "toxic" or patch.rejection_reason == "TOXIC":
            return "toxic"
        if final_decision == "accepted":
            return "safe"
        return "not_tested"

    def _step7_compress_if_needed(self) -> None:
        """Step 7: Analysis Prompt 压缩。"""
        if self.compression_executor is None or not self.compression_enabled:
            self.metrics.compression_accepted = False
            return

        prompt_to_compress = self.final_prompt or self.accepted_prompt or self.analysis_prompt
        if prompt_to_compress is None:
            self.metrics.compression_accepted = False
            return

        line_limit = self.line_limit
        char_limit = self.char_limit

        compressed_prompt, report = self.compression_executor.compress_if_needed(
            prompt=prompt_to_compress,
            line_limit=line_limit,
            char_limit=char_limit,
            batch=self.batch,
            sample_set=self.sample_set,
            mode="analysis",
            contribution_tracker=self.contribution_tracker,
        )

        self.compression_report = report

        if report.accepted:
            self.final_prompt = compressed_prompt
            self.accepted_prompt = compressed_prompt
            self.metrics.compression_accepted = True
            if self.analysis_executor is not None:
                self.final_analysis_results = self.analysis_executor.execute_batch(
                    analysis_prompt=compressed_prompt,
                    extraction_prompt=self.extraction_prompt,
                    extraction_results=self.extraction_results,
                    sample_set=self.sample_set,
                )
                correct = sum(1 for r in self.final_analysis_results if r.analysis_correct)
                total = len(self.final_analysis_results)
                self.metrics.final_accuracy = correct / total if total > 0 else 0.0
                self.metrics.final_correct_count = correct
                self.metrics.final_wrong_count = total - correct
        else:
            self.metrics.compression_accepted = False

    def _step8_final_test_and_metrics(self) -> None:
        """Step 8: 最终测试与统计。"""
        if self.patch_apply_executor is not None:
            if self.accepted_prompt is not None:
                if self.analysis_executor is not None:
                    self.final_analysis_results = self.analysis_executor.execute_batch(
                        analysis_prompt=self.accepted_prompt,
                        extraction_prompt=self.extraction_prompt,
                        extraction_results=self.extraction_results,
                        sample_set=self.sample_set,
                    )
                    correct_count = sum(
                        1 for r in self.final_analysis_results if r.analysis_correct
                    )
                    total = len(self.final_analysis_results)
                    self.metrics.final_correct_count = correct_count
                    self.metrics.final_accuracy = (
                        correct_count / total if total > 0 else 0.0
                    )
                else:
                    if self.patched_analysis_results:
                        self.final_analysis_results = self.patched_analysis_results
                        correct_count = sum(
                            1 for r in self.final_analysis_results if r.analysis_correct
                        )
                        total = len(self.final_analysis_results)
                        self.metrics.final_correct_count = correct_count
                        self.metrics.final_accuracy = (
                            correct_count / total if total > 0 else 0.0
                        )
                    else:
                        self.metrics.no_progress = True
                        self.metrics.final_accuracy = self.metrics.base_accuracy
                self._record_analysis_outcome_history()
            else:
                self.metrics.no_progress = True
                self.metrics.final_accuracy = self.metrics.base_accuracy
                self._record_analysis_outcome_history()
            return

        if not self.final_merged_patches:
            self.metrics.no_progress = True
            self.metrics.final_accuracy = self.metrics.base_accuracy
            self._record_analysis_outcome_history()
            return

        for extraction_result in self.extraction_results:
            analysis_result = AnalysisResult(
                sample_id=extraction_result.sample_id,
                judgement={"mock": "final_judgement"},
                analysis_correct=True,
            )
            self.final_analysis_results.append(analysis_result)

        correct_count = sum(1 for r in self.final_analysis_results if r.analysis_correct)
        total = len(self.final_analysis_results)
        self.metrics.final_correct_count = correct_count
        self.metrics.final_accuracy = correct_count / total if total > 0 else 0.0
        self._record_analysis_outcome_history()

    def _record_analysis_outcome_history(self) -> None:
        """记录本轮 analysis prompt 最终效果，供 APEX 风格采样使用。"""
        final_status_by_sample = {
            result.sample_id: result.analysis_correct for result in self.final_analysis_results
        }
        base_status_by_sample = {
            result.sample_id: result.analysis_correct for result in self.base_analysis_results
        }
        trace_by_sample = {
            trace.sample_id: trace
            for trace in self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
        }
        patch_decision = "accepted" if self.accepted_prompt is not None else "no_progress"

        for sample_id in self.batch.sample_ids:
            raw_status = final_status_by_sample.get(sample_id)
            if raw_status is None:
                raw_status = base_status_by_sample.get(sample_id)
            if raw_status is None:
                outcome_status = "unknown"
            else:
                outcome_status = "pass" if raw_status else "fail"
            state = self.sample_set.states.get(sample_id)
            if state is None:
                continue
            if raw_status is not None:
                state.last_analysis_status = "correct" if raw_status else "wrong"
            trajectory = state.get_or_create_trajectory("analysis", self.iteration)
            if sample_id in base_status_by_sample:
                trajectory.base_status = "pass" if base_status_by_sample[sample_id] else "fail"
            trajectory.final_status = outcome_status
            trajectory.sample_transition = (
                getattr(trace_by_sample.get(sample_id), "transition", None) or "unknown"
            )
            state.add_outcome_history(
                SampleOutcomeHistoryItem(
                    sample_id=sample_id,
                    prompt_type="analysis",
                    iteration=self.iteration,
                    status=outcome_status,
                    transition=getattr(trace_by_sample.get(sample_id), "transition", None) or "unknown",
                    selected=True,
                    patch_decision=patch_decision,
                    metadata={"analysis_correct": raw_status},
                )
            )
