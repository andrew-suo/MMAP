"""Extraction Prompt Optimization Stage。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..core.logging import get_logger, log_stage
from ..core.progress import NullProgressReporter, ProgressReporter
from ..patch.types import (
    CompressionReport,
    ExtractionPatch,
    PatchMergeReport,
    SemanticPatchDraft,
    ToxicityReport,
)
from ..data.sample import (
    SampleBatch,
    SampleOutcomeHistoryItem,
    SamplePatchAttempt,
    SampleSet,
    SampleState,
    SampleTrace,
)
from ..prompt.structured_prompt import StructuredPrompt
from ..prompt.section_contribution import SectionContributionTracker


@dataclass
class ExtractionResult:
    """抽取结果。"""
    sample_id: str
    raw_output: str
    parsed_output: dict | None
    status: Literal["correct", "wrong", "invalid"]
    error_details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "sample_id": self.sample_id,
            "raw_output": self.raw_output,
            "parsed_output": self.parsed_output,
            "status": self.status,
            "error_details": list(self.error_details),
        }


@dataclass
class AnalysisResult:
    """分析结果（盲评模式）。"""
    sample_id: str
    judgement: dict[str, Any]
    analysis_correct: bool
    error_reason: str | None = None
    patch_suggestion: dict[str, Any] | None = None
    confirmed_facts: list[str] = field(default_factory=list)
    hypothesized_error_causes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "sample_id": self.sample_id,
            "judgement": self.judgement,
            "analysis_correct": self.analysis_correct,
            "error_reason": self.error_reason,
            "patch_suggestion": self.patch_suggestion,
            "confirmed_facts": list(self.confirmed_facts),
            "hypothesized_error_causes": list(self.hypothesized_error_causes),
        }


@dataclass
class EvalRecord:
    """评估记录。"""
    sample_id: str
    extraction_result_id: str
    status: str
    correct: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "sample_id": self.sample_id,
            "extraction_result_id": self.extraction_result_id,
            "status": self.status,
            "correct": self.correct,
            "details": dict(self.details),
        }


@dataclass
class ExtractionMetrics:
    """Extraction Prompt 指标。"""
    base_accuracy: float | None = None
    final_accuracy: float | None = None
    base_correct_count: int = 0
    base_wrong_count: int = 0
    base_invalid_count: int = 0
    final_correct_count: int = 0
    final_wrong_count: int = 0
    final_invalid_count: int = 0
    accepted_patch_count: int = 0
    rejected_patch_count: int = 0
    toxic_patch_count: int = 0
    compression_accepted: bool = False
    rollback: bool = False
    no_progress: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "base_accuracy": self.base_accuracy,
            "final_accuracy": self.final_accuracy,
            "base_correct_count": self.base_correct_count,
            "base_wrong_count": self.base_wrong_count,
            "base_invalid_count": self.base_invalid_count,
            "final_correct_count": self.final_correct_count,
            "final_wrong_count": self.final_wrong_count,
            "final_invalid_count": self.final_invalid_count,
            "accepted_patch_count": self.accepted_patch_count,
            "rejected_patch_count": self.rejected_patch_count,
            "toxic_patch_count": self.toxic_patch_count,
            "compression_accepted": self.compression_accepted,
            "rollback": self.rollback,
            "no_progress": self.no_progress,
        }


class ExtractionPromptOptimizationStage:
    """Extraction Prompt Optimization Stage。"""

    def __init__(
        self,
        extraction_prompt: StructuredPrompt,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
        batch: SampleBatch,
        iteration: int,
        extraction_executor=None,
        evaluation_executor=None,
        analysis_executor=None,
        patch_generation_executor=None,
        patch_apply_executor=None,
        merge_executor=None,
        toxicity_test_executor=None,
        compression_executor=None,
        line_limit: int = 300,
        char_limit: int = 20000,
        compression_enabled: bool = True,
        ema_alpha: float = 0.3,
        progress_reporter: ProgressReporter | None = None,
    ):
        self.extraction_prompt = extraction_prompt
        self.analysis_prompt = analysis_prompt
        self.sample_set = sample_set
        self.batch = batch
        self.iteration = iteration

        self.extraction_executor = extraction_executor
        self.evaluation_executor = evaluation_executor
        self.analysis_executor = analysis_executor
        self.patch_generation_executor = patch_generation_executor
        self.patch_apply_executor = patch_apply_executor
        self.merge_executor = merge_executor
        self.toxicity_test_executor = toxicity_test_executor
        self.compression_executor = compression_executor
        self.line_limit = line_limit
        self.char_limit = char_limit
        self.compression_enabled = compression_enabled
        self.ema_alpha = ema_alpha
        self.progress = progress_reporter or NullProgressReporter()
        self.logger = get_logger(__name__)

        self.base_extraction_results: list[ExtractionResult] = []
        self.base_eval_records: list[EvalRecord] = []
        self.analysis_results: list[AnalysisResult] = []
        self.draft_patches: list[ExtractionPatch] = []
        self.validated_patches: list[ExtractionPatch] = []
        self.rejected_patches: list[ExtractionPatch] = []
        self.initial_merged_patches: list[ExtractionPatch] = []
        self.patched_extraction_results: list[ExtractionResult] = []
        self.patched_eval_records: list[EvalRecord] = []
        self.final_merged_patches: list[ExtractionPatch] = []
        self.final_extraction_results: list[ExtractionResult] = []
        self.final_eval_records: list[EvalRecord] = []

        self.ineffective_patches: list[ExtractionPatch] = []
        self.safe_patches: list[ExtractionPatch] = []
        self.toxic_patches: list[ExtractionPatch] = []

        self.trial_prompt: StructuredPrompt | None = None
        self.patched_prompt: StructuredPrompt | None = None
        self.accepted_prompt: StructuredPrompt | None = None
        self.final_prompt: StructuredPrompt | None = None

        self.metrics = ExtractionMetrics()

        self.initial_merge_report: PatchMergeReport | None = None
        self.final_merge_report: PatchMergeReport | None = None
        self.toxicity_report: ToxicityReport | None = None
        self.compression_report: CompressionReport | None = None
        self.transition_report: dict[str, Any] | None = None
        self.patch_apply_report = None
        self.semantic_patch_drafts: list[SemanticPatchDraft] = []
        self.translated_patches: list[ExtractionPatch] = []
        self.model_output_repairs: list[dict[str, Any]] = []

        # Section 贡献度追踪（EMA）
        self.contribution_tracker = SectionContributionTracker(alpha=0.3)

    def run(self) -> ExtractionMetrics:
        """执行完整的 Extraction Prompt Optimization Stage。"""
        log_stage(self.logger, "extraction_stage_start", iteration=self.iteration, samples=len(self.batch.sample_ids))
        self.progress.step("  [Extraction 1/9] 抽取样本...")
        self._step1_execute_extraction()

        self._step2_compute_base_metrics()
        if self.metrics.base_accuracy is not None:
            self.progress.step(f"  [Extraction 2/9] 基础评估完成，准确率: {self.metrics.base_accuracy:.2%}")
        else:
            self.progress.step("  [Extraction 2/9] 基础评估完成")

        # 更新 section 贡献度追踪
        self._update_contribution_tracker()

        self.progress.step("  [Extraction 3/9] 分析抽取结果...")
        self._step3_analyze_results()

        self._step4_generate_patches()
        self.progress.step(f"  [Extraction 4/9] 生成 patch（{len(self.draft_patches)} 个）...")

        self._step5_initial_merge()
        self.progress.step(f"  [Extraction 5/9] 合并 patch（{len(self.initial_merged_patches)} 个）...")

        self.progress.step("  [Extraction 6/9] 应用 patch 并重新评估...")
        self._step6_apply_and_test()

        self.progress.step("  [Extraction 7/9] 测毒验证...")
        self._step7_regression_and_toxicity_test()

        self.progress.step("  [Extraction 8/9] 压缩 prompt...")
        self._step8_compress_if_needed()

        self.progress.step("  [Extraction 9/9] 生成结果...")
        self._step9_final_test_and_metrics()
        log_stage(
            self.logger,
            "extraction_stage_done",
            iteration=self.iteration,
            base_accuracy=self.metrics.base_accuracy,
            final_accuracy=self.metrics.final_accuracy,
            accepted_patches=self.metrics.accepted_patch_count,
            rejected_patches=self.metrics.rejected_patch_count,
            toxic_patches=self.metrics.toxic_patch_count,
            no_progress=self.metrics.no_progress,
        )

        return self.metrics

    def _step1_execute_extraction(self) -> None:
        """Step 1: 执行抽取。"""
        if self.extraction_executor is not None:
            if hasattr(self.extraction_executor, "model_output_repairs"):
                self.extraction_executor.model_output_repairs = []
            self.base_extraction_results = self.extraction_executor.execute(
                prompt=self.extraction_prompt,
                batch=self.batch,
                sample_set=self.sample_set,
            )
            self.model_output_repairs.extend(getattr(
                self.extraction_executor, "model_output_repairs", []
            ))
            for result in self.base_extraction_results:
                trace = SampleTrace(
                    sample_id=result.sample_id,
                    phase="prompt_optimization",
                    iteration=self.iteration,
                    selected=True,
                    base_extraction_result_id=result.sample_id,
                    base_extraction_status=result.status,
                )
                self.sample_set.add_trace(trace)
            return

        for sample_id in self.batch.sample_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock output",
                parsed_output={"mock": "data"},
                status="correct",
            )
            self.base_extraction_results.append(result)

            trace = SampleTrace(
                sample_id=sample_id,
                phase="prompt_optimization",
                iteration=self.iteration,
                selected=True,
                base_extraction_result_id=result.sample_id,
                base_extraction_status=result.status,
            )
            self.sample_set.add_trace(trace)

    def _step2_compute_base_metrics(self) -> None:
        """Step 2: 统计原始 prompt 指标。"""
        if self.evaluation_executor is not None:
            self.base_eval_records = self.evaluation_executor.evaluate_batch(
                self.base_extraction_results, self.sample_set
            )
            correct_count = sum(1 for r in self.base_eval_records if r.status == "correct")
            wrong_count = sum(1 for r in self.base_eval_records if r.status == "wrong")
            invalid_count = sum(1 for r in self.base_eval_records if r.status == "invalid")
            total = len(self.base_eval_records)

            self.metrics.base_correct_count = correct_count
            self.metrics.base_wrong_count = wrong_count
            self.metrics.base_invalid_count = invalid_count
            self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

            for eval_record in self.base_eval_records:
                state = self.sample_set.states.get(eval_record.sample_id)
                if state:
                    has_error = eval_record.status in ["wrong", "invalid"]
                    state.update_error(has_error)
                    state.last_extraction_status = eval_record.status
                    trajectory = state.get_or_create_trajectory("extraction", self.iteration)
                    trajectory.base_status = eval_record.status
                    trajectory.selected = True
            return

        correct_count = sum(1 for r in self.base_extraction_results if r.status == "correct")
        wrong_count = sum(1 for r in self.base_extraction_results if r.status == "wrong")
        invalid_count = sum(1 for r in self.base_extraction_results if r.status == "invalid")
        total = len(self.base_extraction_results)

        self.metrics.base_correct_count = correct_count
        self.metrics.base_wrong_count = wrong_count
        self.metrics.base_invalid_count = invalid_count
        self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

        for result in self.base_extraction_results:
            state = self.sample_set.states.get(result.sample_id)
            if state:
                has_error = result.status in ["wrong", "invalid"]
                state.update_error(has_error)
                state.last_extraction_status = result.status
                trajectory = state.get_or_create_trajectory("extraction", self.iteration)
                trajectory.base_status = result.status
                trajectory.selected = True

    def _update_contribution_tracker(self) -> None:
        """从抽取结果和评估记录更新 section 贡献度追踪器。"""
        # 构建 sample_id → attribution 映射
        batch_attribution: dict[str, list[dict]] = {}
        for result in self.base_extraction_results:
            parsed = result.parsed_output if isinstance(result.parsed_output, dict) else {}
            used_sections = parsed.get("used_prompt_sections", [])
            if isinstance(used_sections, list):
                batch_attribution[result.sample_id] = used_sections

        # 构建 sample_id → is_correct 映射
        batch_results: dict[str, bool] = {}
        if self.base_eval_records:
            for record in self.base_eval_records:
                batch_results[record.sample_id] = record.correct
        else:
            # 无评估记录时，用 extraction status 近似
            for result in self.base_extraction_results:
                batch_results[result.sample_id] = result.status == "correct"

        if batch_results:
            self.contribution_tracker.update(batch_attribution, batch_results)

    def _step3_analyze_results(self) -> None:
        """Step 3: 分析所有抽取结果。"""
        if self.analysis_executor is not None:
            if hasattr(self.analysis_executor, "model_output_repairs"):
                self.analysis_executor.model_output_repairs = []
            self.analysis_results = self.analysis_executor.execute_batch(
                analysis_prompt=self.analysis_prompt,
                extraction_prompt=self.extraction_prompt,
                extraction_results=self.base_extraction_results,
                sample_set=self.sample_set,
            )
            self.model_output_repairs.extend(getattr(
                self.analysis_executor, "model_output_repairs", []
            ))
            for analysis_result in self.analysis_results:
                traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
                for trace in traces:
                    if trace.sample_id == analysis_result.sample_id:
                        trace.analysis_result_id = analysis_result.sample_id
                        trace.analysis_correct = analysis_result.analysis_correct
                state = self.sample_set.states.get(analysis_result.sample_id)
                if state:
                    state.last_analysis_status = "correct" if analysis_result.analysis_correct else "wrong"
                    trajectory = state.get_or_create_trajectory("extraction", self.iteration)
                    trajectory.analysis_summary = {
                        "analysis_correct": analysis_result.analysis_correct,
                        "error_reason": analysis_result.error_reason,
                        "confirmed_facts": list(analysis_result.confirmed_facts),
                        "hypothesized_error_causes": list(analysis_result.hypothesized_error_causes),
                    }
            return

        for result in self.base_extraction_results:
            spec = self.sample_set.specs.get(result.sample_id)
            if spec is None:
                continue

            analysis_result = AnalysisResult(
                sample_id=result.sample_id,
                judgement={"mock": "judgement"},
                analysis_correct=True,
            )
            self.analysis_results.append(analysis_result)

            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == result.sample_id:
                    trace.analysis_result_id = analysis_result.sample_id
                    trace.analysis_correct = analysis_result.analysis_correct

            state = self.sample_set.states.get(result.sample_id)
            if state:
                state.last_analysis_status = "correct" if analysis_result.analysis_correct else "wrong"
                trajectory = state.get_or_create_trajectory("extraction", self.iteration)
                trajectory.analysis_summary = {
                    "analysis_correct": analysis_result.analysis_correct,
                    "error_reason": analysis_result.error_reason,
                    "confirmed_facts": list(analysis_result.confirmed_facts),
                    "hypothesized_error_causes": list(analysis_result.hypothesized_error_causes),
                }

    def _step4_generate_patches(self) -> None:
        """Step 4: 基于有效分析生成 extraction patch。"""
        if self.patch_generation_executor is not None:
            draft_patches, validated_patches, rejected_patches = (
                self.patch_generation_executor.generate_extraction_patches(
                    analysis_results=self.analysis_results,
                    extraction_results=self.base_extraction_results,
                    extraction_prompt=self.extraction_prompt,
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

            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for patch in self.draft_patches:
                for trace in traces:
                    if trace.sample_id in patch.source_sample_ids:
                        trace.generated_extraction_patch_ids.append(patch.id)
            self._record_generated_patch_attempts()
            return

        for analysis_result in self.analysis_results:
            if not analysis_result.analysis_correct:
                continue

            patch = ExtractionPatch(
                id=f"patch_extraction_{analysis_result.sample_id}",
                target_section_id="section_1",
                operation_type="replace_section",
                content="Mock patch content",
                rationale="Mock rationale",
                source_sample_ids=[analysis_result.sample_id],
                status="draft",
            )
            self.draft_patches.append(patch)

            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == analysis_result.sample_id:
                    trace.generated_extraction_patch_ids.append(patch.id)
        self._record_generated_patch_attempts()

    def _record_generated_patch_attempts(self) -> None:
        """记录当前 sample 触发生成过的 extraction patch，包括校验失败。"""
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
                state.generated_extraction_patch_count += 1
                self._append_patch_attempt_event(
                    state=state,
                    sample_id=sample_id,
                    patch=patch,
                    stage="validation",
                    stage_status=validation_status,
                    generation_status="generated",
                    validation_status=validation_status,
                    merge_status="not_merged",
                    final_decision="rejected" if validation_status == "rejected" else "unknown",
                )
        for record in getattr(self.patch_generation_executor, "translation_failed_attempts", []):
            for sample_id in record.get("source_sample_ids", []):
                state = self.sample_set.states.get(sample_id)
                if state is None:
                    continue
                state.generated_extraction_patch_count += 1
                self._append_external_attempt_event(
                    state=state,
                    sample_id=str(sample_id),
                    attempt_id=str(record.get("attempt_id", "")),
                    patch_id=str(record.get("patch_id", "")),
                    stage="translated",
                    stage_status="failed",
                    generation_status=str(record.get("generation_status", "generated")),
                    validation_status=str(record.get("validation_status", "translation_failed")),
                    merge_status=str(record.get("merge_status", "not_merged")),
                    final_decision=str(record.get("final_decision", "rejected")),
                    rejection_reason=record.get("rejection_reason"),
                    target_section_id=str(record.get("target_section_id", "")),
                    operation_type=str(record.get("operation_type", "")),
                    direction=str(record.get("direction", "")),
                    content=str(record.get("content", "")),
                    rationale=str(record.get("rationale", "")),
                    metadata=dict(record.get("metadata", {})),
                )

    def _build_patch_attempt(
        self,
        patch: ExtractionPatch,
        sample_id: str,
        stage: str = "finalized",
        stage_status: str = "unknown",
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
            attempt_id=self._patch_attempt_id(patch, sample_id),
            patch_id=patch.id,
            prompt_type="extraction",
            iteration=self.iteration,
            stage=stage,
            stage_status=stage_status,
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

    def _step5_initial_merge(self) -> None:
        """Step 5: Tree Merge 生成初始 merged patch。"""
        if self.merge_executor is not None:
            merged_patches, merge_report = self.merge_executor.merge(
                patches=self.validated_patches,
                prompt=self.extraction_prompt,
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
                id=f"merge_report_initial_{self.iteration}",
                input_patch_count=len(self.validated_patches),
                merged_patch_count=len(self.initial_merged_patches),
                conflict_count=0,
                merged_patches=[p.to_dict() for p in self.initial_merged_patches],
                metadata={"merge_strategy": "passthrough"},
            )
            self._record_initial_merge_outcomes()
            return

        if not self.draft_patches:
            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_initial_{self.iteration}",
                input_patch_count=0,
                merged_patch_count=0,
                conflict_count=0,
            )
            return

        self.initial_merged_patches = self.draft_patches.copy()
        for patch in self.initial_merged_patches:
            patch.status = "merged"

        self.initial_merge_report = PatchMergeReport(
            id=f"merge_report_initial_{self.iteration}",
            input_patch_count=len(self.draft_patches),
            merged_patch_count=len(self.initial_merged_patches),
            conflict_count=0,
            merged_patches=[p.to_dict() for p in self.initial_merged_patches],
        )
        self._record_initial_merge_outcomes()

    def _step6_apply_and_test(self) -> None:
        """Step 6: 应用初始 merged patch 并回归测试。"""
        if self.patch_apply_executor is not None and self.initial_merged_patches:
            trial_prompt, apply_report = self.patch_apply_executor.apply(
                self.extraction_prompt, self.initial_merged_patches
            )
            self.trial_prompt = trial_prompt
            self.patched_prompt = trial_prompt
            self.patch_apply_report = apply_report

            if not apply_report.changed:
                self.metrics.no_progress = True
                self._mark_apply_no_change()
                return

            if self.extraction_executor is not None:
                self.patched_extraction_results = self.extraction_executor.execute(
                    prompt=trial_prompt,
                    batch=self.batch,
                    sample_set=self.sample_set,
                )
            if self.evaluation_executor is not None:
                self.patched_eval_records = self.evaluation_executor.evaluate_batch(
                    self.patched_extraction_results, self.sample_set,
                )
            return

        if not self.initial_merged_patches:
            self.metrics.no_progress = True
            return

        for sample_id in self.batch.sample_ids:
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock patched output",
                parsed_output={"mock": "patched_data"},
                status="correct",
            )
            self.patched_extraction_results.append(result)

    def _step7_regression_and_toxicity_test(self) -> None:
        """Step 7: 回归分析、无效剔除与测毒。"""
        if (
            self.patch_apply_report is not None
            and getattr(self.patch_apply_report, "changed", True) is False
        ):
            return
        if self.patch_apply_executor is not None and self.toxicity_test_executor is not None:
            base_eval_map = {r.sample_id: r for r in self.base_eval_records}
            patched_eval_map = {r.sample_id: r for r in self.patched_eval_records}

            fixed_sample_ids: list[str] = []
            broken_sample_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base_record = base_eval_map.get(sample_id)
                patched_record = patched_eval_map.get(sample_id)

                if base_record is None or patched_record is None:
                    continue

                base_correct = base_record.status == "correct"
                patched_correct = patched_record.status == "correct"

                if not base_correct and patched_correct:
                    fixed_sample_ids.append(sample_id)
                elif base_correct and not patched_correct:
                    broken_sample_ids.append(sample_id)
                elif not base_correct and not patched_correct:
                    unchanged_wrong_ids.append(sample_id)
                else:
                    unchanged_correct_ids.append(sample_id)

            toxic_sample_ids = broken_sample_ids

            safe_patches, toxic_patches, toxicity_report = self.toxicity_test_executor.test(
                base_prompt=self.extraction_prompt,
                candidate_patches=self.initial_merged_patches,
                toxic_sample_ids=toxic_sample_ids,
                sample_set=self.sample_set,
                mode="extraction",
                early_stop=True,
                extraction_executor=self.extraction_executor,
                evaluation_executor=self.evaluation_executor,
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
                "fixed_sample_ids": list(fixed_sample_ids),
                "broken_sample_ids": list(broken_sample_ids),
                "unchanged_wrong_ids": list(unchanged_wrong_ids),
                "unchanged_correct_ids": list(unchanged_correct_ids),
                "toxic_sample_ids": list(toxic_sample_ids),
            }

            if safe_patches and self.merge_executor is not None:
                final_merged_patches, final_merge_report = self.merge_executor.merge(
                    patches=safe_patches,
                    prompt=self.extraction_prompt,
                    merge_strategy="tree_merge",
                    sample_set=self.sample_set,
                )
                self.final_merged_patches = final_merged_patches
                self.final_merge_report = final_merge_report
            elif safe_patches:
                self.final_merged_patches = safe_patches.copy()
                self.final_merge_report = PatchMergeReport(
                    id=f"merge_report_final_{self.iteration}",
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
                    self.extraction_prompt, self.final_merged_patches
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
            self.metrics.toxic_patch_count = len(toxic_patches)

            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for trace in traces:
                if trace.sample_id in fixed_sample_ids:
                    trace.transition = "fixed"
                elif trace.sample_id in broken_sample_ids:
                    trace.transition = "broken"
                elif trace.sample_id in unchanged_wrong_ids:
                    trace.transition = "unchanged_wrong"
                else:
                    trace.transition = "unchanged_correct"

                state = self.sample_set.states.get(trace.sample_id)
                if state:
                    if trace.transition == "fixed":
                        state.historical_fixed_count += 1
                    elif trace.transition == "broken":
                        state.historical_broken_count += 1
            self._record_sample_patch_attempts(
                patches=self.initial_merged_patches,
                fixed_sample_ids=fixed_sample_ids,
                broken_sample_ids=broken_sample_ids,
                unchanged_wrong_ids=unchanged_wrong_ids,
                unchanged_correct_ids=unchanged_correct_ids,
            )
            return

        if self.patch_apply_executor is not None:
            base_eval_map = {r.sample_id: r for r in self.base_eval_records}
            patched_eval_map = {r.sample_id: r for r in self.patched_eval_records}

            fixed_sample_ids: list[str] = []
            broken_sample_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base_record = base_eval_map.get(sample_id)
                patched_record = patched_eval_map.get(sample_id)

                if base_record is None or patched_record is None:
                    continue

                base_correct = base_record.status == "correct"
                patched_correct = patched_record.status == "correct"

                if not base_correct and patched_correct:
                    fixed_sample_ids.append(sample_id)
                elif base_correct and not patched_correct:
                    broken_sample_ids.append(sample_id)
                elif not base_correct and not patched_correct:
                    unchanged_wrong_ids.append(sample_id)
                else:
                    unchanged_correct_ids.append(sample_id)

            fixed_count = len(fixed_sample_ids)
            broken_count = len(broken_sample_ids)

            if broken_count > 0:
                self.metrics.rollback = True
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "TOXIC"
                self.final_merged_patches = []
            elif fixed_count > 0:
                self.accepted_prompt = self.trial_prompt
                for patch in self.initial_merged_patches:
                    patch.status = "accepted"
                self.final_merged_patches = self.initial_merged_patches.copy()
            else:
                self.metrics.no_progress = True
                self.accepted_prompt = None
                self.final_merged_patches = []

            if self.accepted_prompt is not None:
                self.metrics.accepted_patch_count = len(self.initial_merged_patches)
                self.metrics.rejected_patch_count = len(self.rejected_patches)
            else:
                self.metrics.accepted_patch_count = 0
                self.metrics.rejected_patch_count = (
                    len(self.rejected_patches) + len(self.initial_merged_patches)
                )

            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for trace in traces:
                if trace.sample_id in fixed_sample_ids:
                    trace.transition = "fixed"
                elif trace.sample_id in broken_sample_ids:
                    trace.transition = "broken"
                elif trace.sample_id in unchanged_wrong_ids:
                    trace.transition = "unchanged_wrong"
                else:
                    trace.transition = "unchanged_correct"

                state = self.sample_set.states.get(trace.sample_id)
                if state:
                    if trace.transition == "fixed":
                        state.historical_fixed_count += 1
                    elif trace.transition == "broken":
                        state.historical_broken_count += 1
            self._record_sample_patch_attempts(
                patches=self.initial_merged_patches,
                fixed_sample_ids=fixed_sample_ids,
                broken_sample_ids=broken_sample_ids,
                unchanged_wrong_ids=unchanged_wrong_ids,
                unchanged_correct_ids=unchanged_correct_ids,
            )
            return

        if not self.initial_merged_patches:
            return

        base_results_map = {r.sample_id: r for r in self.base_extraction_results}
        patched_results_map = {r.sample_id: r for r in self.patched_extraction_results}

        fixed_sample_ids: list[str] = []
        broken_sample_ids: list[str] = []
        unchanged_wrong_ids: list[str] = []
        unchanged_correct_ids: list[str] = []

        for sample_id in self.batch.sample_ids:
            base_result = base_results_map.get(sample_id)
            patched_result = patched_results_map.get(sample_id)

            if base_result is None or patched_result is None:
                continue

            base_correct = base_result.status == "correct"
            patched_correct = patched_result.status == "correct"

            if not base_correct and patched_correct:
                fixed_sample_ids.append(sample_id)
            elif base_correct and not patched_correct:
                broken_sample_ids.append(sample_id)
            elif not base_correct and not patched_correct:
                unchanged_wrong_ids.append(sample_id)
            else:
                unchanged_correct_ids.append(sample_id)

        for patch in self.initial_merged_patches:
            if all(sid in unchanged_wrong_ids for sid in patch.source_sample_ids):
                patch.status = "rejected"
                patch.rejection_reason = "INEFFECTIVE"

        toxic_sample_ids = broken_sample_ids

        remaining_patches = [
            p for p in self.initial_merged_patches
            if p.status not in ["rejected"]
        ]

        remaining_patches.sort(
            key=lambda p: max(
                self.sample_set.states.get(sid, SampleState(sample_id=sid)).difficulty_score
                for sid in p.source_sample_ids
            ),
            reverse=True,
        )

        safe_patches: list[ExtractionPatch] = []
        toxic_patches: list[ExtractionPatch] = []

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
        self.metrics.toxic_patch_count = len(toxic_patches)

        self.toxicity_report = ToxicityReport(
            id=f"toxicity_report_{self.iteration}",
            tested_patch_count=len(remaining_patches),
            toxic_patch_count=len(toxic_patches),
            safe_patch_count=len(safe_patches),
            toxic_patches=[p.id for p in toxic_patches],
            safe_patches=[p.id for p in safe_patches],
            toxic_sample_ids=toxic_sample_ids,
        )

        traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
        for trace in traces:
            if trace.sample_id in fixed_sample_ids:
                trace.transition = "fixed"
            elif trace.sample_id in broken_sample_ids:
                trace.transition = "broken"
            elif trace.sample_id in unchanged_wrong_ids:
                trace.transition = "unchanged_wrong"
            else:
                trace.transition = "unchanged_correct"

            state = self.sample_set.states.get(trace.sample_id)
            if state:
                if trace.transition == "fixed":
                    state.historical_fixed_count += 1
                elif trace.transition == "broken":
                    state.historical_broken_count += 1

        self._record_sample_patch_attempts(
            patches=self.initial_merged_patches,
            fixed_sample_ids=fixed_sample_ids,
            broken_sample_ids=broken_sample_ids,
            unchanged_wrong_ids=unchanged_wrong_ids,
            unchanged_correct_ids=unchanged_correct_ids,
        )

    def _record_sample_patch_attempts(
        self,
        patches: list[ExtractionPatch],
        fixed_sample_ids: list[str],
        broken_sample_ids: list[str],
        unchanged_wrong_ids: list[str],
        unchanged_correct_ids: list[str],
    ) -> None:
        """把本轮 extraction patch 的最终结果写入 source sample 轨迹。"""
        transition_by_sample = self._transition_map(
            fixed_sample_ids=fixed_sample_ids,
            broken_sample_ids=broken_sample_ids,
            unchanged_wrong_ids=unchanged_wrong_ids,
            unchanged_correct_ids=unchanged_correct_ids,
        )
        final_patch_ids = {patch.id for patch in self.final_merged_patches}
        safe_patch_ids = {patch.id for patch in self.safe_patches}
        toxic_patch_ids = {patch.id for patch in self.toxic_patches}
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
                trajectory = state.get_or_create_trajectory("extraction", self.iteration)
                attempt = self._build_patch_attempt(
                    patch=patch,
                    sample_id=sample_id,
                    stage="finalized",
                    stage_status=final_decision,
                    validation_status="validated" if patch.id not in {p.id for p in self.rejected_patches} else "rejected",
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

    def _record_initial_merge_outcomes(self) -> None:
        """把 validated patch 在 initial merge 阶段的消费结果写回轨迹。"""
        merged_ids = {
            source_patch_id
            for patch in self.initial_merged_patches
            for source_patch_id in self._source_patch_ids(patch)
        }
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
                if getattr(patch, "rejection_reason", None) == "MERGE_PROVENANCE_INVALID":
                    final_decision = "rejected"
            if patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED":
                merge_status = "not_merged"
                final_decision = "rejected"
            if patch.rejection_reason == "MERGE_PROVENANCE_INVALID":
                merge_status = "not_merged"
                final_decision = "rejected"
            for sample_id in patch.source_sample_ids:
                state = self.sample_set.states.get(sample_id)
                if state is None:
                    continue
                self._append_patch_attempt_event(
                    state=state,
                    sample_id=sample_id,
                    patch=patch,
                    stage="initial_merge",
                    stage_status=merge_status,
                    validation_status="validated",
                    merge_status=merge_status,
                    final_decision=final_decision,
                    evidence_scope="batch",
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

    def _append_patch_attempt_event(
        self,
        state: SampleState,
        sample_id: str,
        patch: ExtractionPatch,
        stage: str,
        stage_status: str,
        generation_status: str = "generated",
        validation_status: str = "unknown",
        merge_status: str = "unknown",
        regression_effect: str = "unknown",
        toxicity_status: str = "not_tested",
        final_decision: str = "unknown",
        evidence_scope: str = "sample",
    ) -> None:
        trajectory = state.get_or_create_trajectory("extraction", self.iteration)
        trajectory.add_patch_attempt(
            self._build_patch_attempt(
                patch=patch,
                sample_id=sample_id,
                stage=stage,
                stage_status=stage_status,
                generation_status=generation_status,
                validation_status=validation_status,
                merge_status=merge_status,
                regression_effect=regression_effect,
                toxicity_status=toxicity_status,
                final_decision=final_decision,
                evidence_scope=evidence_scope,
            )
        )

    def _append_external_attempt_event(
        self,
        state: SampleState,
        sample_id: str,
        attempt_id: str,
        patch_id: str,
        stage: str,
        stage_status: str,
        generation_status: str,
        validation_status: str,
        merge_status: str,
        final_decision: str,
        rejection_reason: str | None,
        target_section_id: str,
        operation_type: str,
        direction: str,
        content: str,
        rationale: str,
        metadata: dict[str, Any],
    ) -> None:
        trajectory = state.get_or_create_trajectory("extraction", self.iteration)
        trajectory.add_patch_attempt(
            SamplePatchAttempt(
                attempt_id=attempt_id,
                patch_id=patch_id,
                prompt_type="extraction",
                iteration=self.iteration,
                stage=stage,
                stage_status=stage_status,
                target_section_id=target_section_id,
                operation_type=operation_type,
                direction=direction,
                content=content,
                rationale=rationale,
                generation_status=generation_status,
                validation_status=validation_status,
                merge_status=merge_status,
                final_decision=final_decision,
                rejection_reason=rejection_reason,
                evidence_scope="sample",
                metadata=metadata,
            )
        )

    def _patch_attempt_id(self, patch: ExtractionPatch, sample_id: str) -> str:
        return f"{sample_id}::{patch.id}"

    def _source_patch_ids(self, patch: ExtractionPatch) -> list[str]:
        metadata = getattr(patch, "metadata", {}) or {}
        source_patch_ids = metadata.get("source_patch_ids", [])
        if isinstance(source_patch_ids, list) and source_patch_ids:
            return [str(item) for item in source_patch_ids if str(item)]
        return [patch.id]

    def _patch_final_decision(self, patch: ExtractionPatch) -> str:
        if patch.rejection_reason == "TOXIC":
            return "toxic"
        if patch.rejection_reason == "INEFFECTIVE":
            return "ineffective"
        if patch.rejection_reason == "APPLY_NO_CHANGE":
            return "ineffective"
        if patch.rejection_reason == "MERGED_PATCH_VALIDATION_FAILED":
            return "rejected"
        if patch.rejection_reason == "MERGE_PROVENANCE_INVALID":
            return "rejected"
        if patch.status == "accepted":
            return "accepted"
        if patch.status == "candidate_safe":
            return "accepted"
        if patch.status == "rejected":
            return "rejected"
        return patch.status or "unknown"

    def _patch_toxicity(self, patch: ExtractionPatch, final_decision: str) -> str:
        if final_decision == "toxic" or patch.rejection_reason == "TOXIC":
            return "toxic"
        if final_decision in {"accepted", "candidate_safe"}:
            return "safe"
        return "not_tested"

    def _step8_compress_if_needed(self) -> None:
        """Step 8: Prompt 压缩（如果需要）。"""
        if self.compression_executor is None or not self.compression_enabled:
            self.metrics.compression_accepted = False
            return

        prompt_to_compress = self.final_prompt or self.accepted_prompt or self.extraction_prompt
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
            mode="extraction",
            contribution_tracker=self.contribution_tracker,
        )

        self.compression_report = report

        if report.accepted:
            self.final_prompt = compressed_prompt
            self.accepted_prompt = compressed_prompt
            self.metrics.compression_accepted = True
            if self.extraction_executor is not None and self.evaluation_executor is not None:
                self.final_extraction_results = self.extraction_executor.execute(
                    prompt=compressed_prompt, batch=self.batch, sample_set=self.sample_set
                )
                self.final_eval_records = self.evaluation_executor.evaluate_batch(
                    self.final_extraction_results, self.sample_set
                )
                correct = sum(1 for r in self.final_eval_records if r.status == "correct")
                total = len(self.final_eval_records)
                self.metrics.final_accuracy = correct / total if total > 0 else 0.0
                self.metrics.final_correct_count = correct
                self.metrics.final_wrong_count = sum(1 for r in self.final_eval_records if r.status == "wrong")
                self.metrics.final_invalid_count = sum(1 for r in self.final_eval_records if r.status == "invalid")
        else:
            self.metrics.compression_accepted = False

    def _step9_final_test_and_metrics(self) -> None:
        """Step 9: 最终测试与统计。"""
        if self.patch_apply_executor is not None:
            if self.accepted_prompt is not None:
                if self.extraction_executor is not None:
                    self.final_extraction_results = self.extraction_executor.execute(
                        prompt=self.accepted_prompt,
                        batch=self.batch,
                        sample_set=self.sample_set,
                    )
                if self.evaluation_executor is not None:
                    self.final_eval_records = self.evaluation_executor.evaluate_batch(
                        self.final_extraction_results, self.sample_set,
                    )

                if self.final_eval_records:
                    correct_count = sum(
                        1 for r in self.final_eval_records if r.status == "correct"
                    )
                    total = len(self.final_eval_records)
                    self.metrics.final_correct_count = correct_count
                    self.metrics.final_accuracy = (
                        correct_count / total if total > 0 else 0.0
                    )
                elif self.final_extraction_results:
                    correct_count = sum(
                        1 for r in self.final_extraction_results if r.status == "correct"
                    )
                    total = len(self.final_extraction_results)
                    self.metrics.final_correct_count = correct_count
                    self.metrics.final_accuracy = (
                        correct_count / total if total > 0 else 0.0
                    )
                else:
                    self.metrics.final_accuracy = self.metrics.base_accuracy

                traces = self.sample_set.get_traces_for_iteration(
                    "prompt_optimization", self.iteration
                )
                final_status_map = {
                    r.sample_id: r.status for r in self.final_extraction_results
                }
                for trace in traces:
                    trace.final_extraction_status = final_status_map.get(
                        trace.sample_id, "correct"
                    )
                    trace.final_extraction_result_id = trace.sample_id
                self._record_extraction_outcome_history()
            else:
                self.metrics.final_accuracy = self.metrics.base_accuracy
                self.metrics.no_progress = True
                self._record_extraction_outcome_history()
            return

        if not self.final_merged_patches:
            self.metrics.no_progress = True
            self.metrics.final_accuracy = self.metrics.base_accuracy
            self._record_extraction_outcome_history()
            return

        for sample_id in self.batch.sample_ids:
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock final output",
                parsed_output={"mock": "final_data"},
                status="correct",
            )
            self.final_extraction_results.append(result)

        correct_count = sum(1 for r in self.final_extraction_results if r.status == "correct")
        total = len(self.final_extraction_results)
        self.metrics.final_correct_count = correct_count
        self.metrics.final_accuracy = correct_count / total if total > 0 else 0.0
        self._record_extraction_outcome_history()

    def _record_extraction_outcome_history(self) -> None:
        """记录本轮 extraction prompt 最终效果，供 APEX 风格采样使用。"""
        final_status_by_sample = {
            result.sample_id: result.status for result in self.final_extraction_results
        }
        base_status_by_sample = {
            result.sample_id: result.status for result in self.base_extraction_results
        }
        trace_by_sample = {
            trace.sample_id: trace
            for trace in self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
        }
        patch_decision = "accepted" if self.accepted_prompt is not None else "no_progress"

        for sample_id in self.batch.sample_ids:
            raw_status = final_status_by_sample.get(sample_id) or base_status_by_sample.get(sample_id)
            if raw_status is None:
                outcome_status = "unknown"
            else:
                outcome_status = "pass" if raw_status == "correct" else "fail"
            state = self.sample_set.states.get(sample_id)
            if state is None:
                continue
            state.last_extraction_status = raw_status or state.last_extraction_status
            trajectory = state.get_or_create_trajectory("extraction", self.iteration)
            if base_status_by_sample.get(sample_id):
                trajectory.base_status = base_status_by_sample[sample_id]
            trajectory.final_status = raw_status or trajectory.final_status
            trajectory.sample_transition = (
                getattr(trace_by_sample.get(sample_id), "transition", None) or "unknown"
            )
            state.add_outcome_history(
                SampleOutcomeHistoryItem(
                    sample_id=sample_id,
                    prompt_type="extraction",
                    iteration=self.iteration,
                    status=outcome_status,
                    transition=getattr(trace_by_sample.get(sample_id), "transition", None) or "unknown",
                    selected=True,
                    patch_decision=patch_decision,
                    metadata={"raw_status": raw_status},
                )
            )
