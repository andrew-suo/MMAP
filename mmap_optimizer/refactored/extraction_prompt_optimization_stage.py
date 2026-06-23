"""Extraction Prompt Optimization Stage。

根据设计文档，该 stage 负责优化 extraction prompt，包含 9 个步骤：
1. 执行抽取
2. 统计原始 prompt 指标
3. 分析所有抽取结果
4. 基于有效分析生成 extraction patch
5. Tree Merge 生成初始 merged patch
6. 应用初始 merged patch 并回归测试
7. 回归分析、无效剔除与测毒
8. Prompt 压缩
9. 最终测试与统计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .patch import CompressionReport, ExtractionPatch, PatchMergeReport, ToxicityReport
from .sample import SampleBatch, SampleSet, SampleState, SampleTrace
from .structured_prompt import StructuredPrompt


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
    """分析结果。"""
    sample_id: str
    judgement: dict[str, Any]
    analysis_correct: bool
    error_reason: str | None = None
    patch_suggestion: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "sample_id": self.sample_id,
            "judgement": self.judgement,
            "analysis_correct": self.analysis_correct,
            "error_reason": self.error_reason,
            "patch_suggestion": self.patch_suggestion,
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
        extraction_executor=None,  # ExtractionExecutor 实例
        evaluation_executor=None,  # EvaluationExecutor 实例
        analysis_executor=None,    # AnalysisExecutor 实例
        patch_generation_executor=None,  # PatchGenerationExecutor 实例
        patch_apply_executor=None,       # PatchApplyExecutor 实例
        merge_executor=None,             # MergeExecutor 实例
        toxicity_test_executor=None,     # ToxicityTestExecutor 实例
        compression_executor=None,       # CompressionExecutor 实例
    ):
        self.extraction_prompt = extraction_prompt
        self.analysis_prompt = analysis_prompt
        self.sample_set = sample_set
        self.batch = batch
        self.iteration = iteration

        # Executor
        self.extraction_executor = extraction_executor
        self.evaluation_executor = evaluation_executor
        self.analysis_executor = analysis_executor
        self.patch_generation_executor = patch_generation_executor
        self.patch_apply_executor = patch_apply_executor
        self.merge_executor = merge_executor
        self.toxicity_test_executor = toxicity_test_executor
        self.compression_executor = compression_executor

        # 结果存储
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

        # PR3 测毒相关结果
        self.ineffective_patches: list[ExtractionPatch] = []
        self.safe_patches: list[ExtractionPatch] = []
        self.toxic_patches: list[ExtractionPatch] = []

        # Prompt 版本
        self.trial_prompt: StructuredPrompt | None = None
        self.patched_prompt: StructuredPrompt | None = None
        self.accepted_prompt: StructuredPrompt | None = None
        self.final_prompt: StructuredPrompt | None = None

        # 指标
        self.metrics = ExtractionMetrics()

        # 报告
        self.initial_merge_report: PatchMergeReport | None = None
        self.final_merge_report: PatchMergeReport | None = None
        self.toxicity_report: ToxicityReport | None = None
        self.compression_report: CompressionReport | None = None
        self.transition_report: dict[str, Any] | None = None
        self.patch_apply_report = None  # PatchApplyReport

    def run(self) -> ExtractionMetrics:
        """执行完整的 Extraction Prompt Optimization Stage。"""
        # Step 1: 执行抽取
        self._step1_execute_extraction()

        # Step 2: 统计原始 prompt 指标
        self._step2_compute_base_metrics()

        # Step 3: 分析所有抽取结果
        self._step3_analyze_results()

        # Step 4: 基于有效分析生成 extraction patch
        self._step4_generate_patches()

        # Step 5: Tree Merge 生成初始 merged patch
        self._step5_initial_merge()

        # Step 6: 应用初始 merged patch 并回归测试
        self._step6_apply_and_test()

        # Step 7: 回归分析、无效剔除与测毒
        self._step7_regression_and_toxicity_test()

        # Step 8: Prompt 压缩（如果需要）
        self._step8_compress_if_needed()

        # Step 9: 最终测试与统计
        self._step9_final_test_and_metrics()

        return self.metrics

    def _step1_execute_extraction(self) -> None:
        """Step 1: 执行抽取。"""
        if self.extraction_executor is not None:
            # 使用真实 executor
            self.base_extraction_results = self.extraction_executor.execute(
                prompt=self.extraction_prompt,
                batch=self.batch,
                sample_set=self.sample_set,
            )
            # 更新 SampleTrace
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

        # Fallback: mock 实现
        for sample_id in self.batch.sample_ids:
            spec = self.sample_set.specs.get(sample_id)
            if spec is None:
                continue

            # Mock 抽取结果
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock output",
                parsed_output={"mock": "data"},
                status="correct",  # Mock 假设所有都正确
            )
            self.base_extraction_results.append(result)

            # 更新 SampleTrace
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
            # 使用真实 executor 评估
            self.base_eval_records = self.evaluation_executor.evaluate_batch(
                self.base_extraction_results, self.sample_set
            )
            # 基于 eval_records 的 status 统计真实对错
            correct_count = sum(1 for r in self.base_eval_records if r.status == "correct")
            wrong_count = sum(1 for r in self.base_eval_records if r.status == "wrong")
            invalid_count = sum(1 for r in self.base_eval_records if r.status == "invalid")
            total = len(self.base_eval_records)

            self.metrics.base_correct_count = correct_count
            self.metrics.base_wrong_count = wrong_count
            self.metrics.base_invalid_count = invalid_count
            self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

            # 更新样本状态（last_extraction_status 已由 EvaluationExecutor 更新）
            for eval_record in self.base_eval_records:
                state = self.sample_set.states.get(eval_record.sample_id)
                if state:
                    has_error = eval_record.status in ["wrong", "invalid"]
                    state.update_error(has_error)
                    state.last_extraction_status = eval_record.status
            return

        # Fallback: 基于 extraction status 统计
        correct_count = sum(1 for r in self.base_extraction_results if r.status == "correct")
        wrong_count = sum(1 for r in self.base_extraction_results if r.status == "wrong")
        invalid_count = sum(1 for r in self.base_extraction_results if r.status == "invalid")
        total = len(self.base_extraction_results)

        self.metrics.base_correct_count = correct_count
        self.metrics.base_wrong_count = wrong_count
        self.metrics.base_invalid_count = invalid_count
        self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

        # 更新样本状态
        for result in self.base_extraction_results:
            state = self.sample_set.states.get(result.sample_id)
            if state:
                has_error = result.status in ["wrong", "invalid"]
                state.update_error(has_error)
                state.last_extraction_status = result.status

    def _step3_analyze_results(self) -> None:
        """Step 3: 分析所有抽取结果。"""
        if self.analysis_executor is not None:
            # 使用真实 executor
            self.analysis_results = self.analysis_executor.execute_batch(
                analysis_prompt=self.analysis_prompt,
                extraction_prompt=self.extraction_prompt,
                extraction_results=self.base_extraction_results,
                sample_set=self.sample_set,
            )
            # 更新 SampleTrace
            for analysis_result in self.analysis_results:
                traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
                for trace in traces:
                    if trace.sample_id == analysis_result.sample_id:
                        trace.analysis_result_id = analysis_result.sample_id
                        trace.analysis_correct = analysis_result.analysis_correct
                # 更新样本状态
                state = self.sample_set.states.get(analysis_result.sample_id)
                if state:
                    state.last_analysis_status = "correct" if analysis_result.analysis_correct else "wrong"
            return

        # Fallback: mock 实现
        for result in self.base_extraction_results:
            spec = self.sample_set.specs.get(result.sample_id)
            if spec is None:
                continue

            # Mock 分析结果
            analysis_result = AnalysisResult(
                sample_id=result.sample_id,
                judgement={"mock": "judgement"},
                analysis_correct=True,  # Mock 假设分析都正确
            )
            self.analysis_results.append(analysis_result)

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == result.sample_id:
                    trace.analysis_result_id = analysis_result.sample_id
                    trace.analysis_correct = analysis_result.analysis_correct

            # 更新样本状态
            state = self.sample_set.states.get(result.sample_id)
            if state:
                state.last_analysis_status = "correct" if analysis_result.analysis_correct else "wrong"

    def _step4_generate_patches(self) -> None:
        """Step 4: 基于有效分析生成 extraction patch。"""
        if self.patch_generation_executor is not None:
            # 使用真实 executor
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

            # 更新 SampleTrace 的 generated_extraction_patch_ids
            traces = self.sample_set.get_traces_for_iteration(
                "prompt_optimization", self.iteration
            )
            for patch in self.draft_patches:
                for trace in traces:
                    if trace.sample_id in patch.source_sample_ids:
                        trace.generated_extraction_patch_ids.append(patch.id)
            return

        # Fallback: mock 实现
        # 只对 analysis_correct = true 的样本生成 patch
        for analysis_result in self.analysis_results:
            if not analysis_result.analysis_correct:
                continue

            # Mock patch 生成
            patch = ExtractionPatch(
                id=f"patch_extraction_{analysis_result.sample_id}",
                target_section_id="section_1",
                operation_type="replace",
                content="Mock patch content",
                rationale="Mock rationale",
                source_sample_ids=[analysis_result.sample_id],
                status="draft",
            )
            self.draft_patches.append(patch)

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == analysis_result.sample_id:
                    trace.generated_extraction_patch_ids.append(patch.id)

    def _step5_initial_merge(self) -> None:
        """Step 5: Tree Merge 生成初始 merged patch。"""
        if self.merge_executor is not None:
            # PR3: 使用真实 MergeExecutor
            merged_patches, merge_report = self.merge_executor.merge(
                patches=self.validated_patches,
                prompt=self.extraction_prompt,
                merge_strategy="tree_merge",
                sample_set=self.sample_set,
            )
            self.initial_merged_patches = merged_patches
            self.initial_merge_report = merge_report
            return

        if self.patch_generation_executor is not None:
            # 使用 passthrough merge：直接透传 validated_patches
            self.initial_merged_patches = self.validated_patches.copy()
            # 不修改 patch status（保持 "candidate"）

            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_initial_{self.iteration}",
                input_patch_count=len(self.validated_patches),
                merged_patch_count=len(self.initial_merged_patches),
                conflict_count=0,
                merged_patches=[p.to_dict() for p in self.initial_merged_patches],
                metadata={"merge_strategy": "passthrough"},
            )
            return

        # Fallback: mock tree merge
        if not self.draft_patches:
            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_initial_{self.iteration}",
                input_patch_count=0,
                merged_patch_count=0,
                conflict_count=0,
            )
            return

        # Mock tree merge - 简单合并
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

    def _step6_apply_and_test(self) -> None:
        """Step 6: 应用初始 merged patch 并回归测试。"""
        if self.patch_apply_executor is not None and self.initial_merged_patches:
            # 使用真实 executor 应用 patch
            trial_prompt, apply_report = self.patch_apply_executor.apply(
                self.extraction_prompt, self.initial_merged_patches
            )
            self.trial_prompt = trial_prompt
            self.patched_prompt = trial_prompt
            self.patch_apply_report = apply_report

            if not apply_report.changed:
                self.metrics.no_progress = True
                return

            # 使用真实 executor 重新抽取和评估
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

        # Fallback: mock 应用 patch 并测试
        if not self.initial_merged_patches:
            self.metrics.no_progress = True
            return

        for sample_id in self.batch.sample_ids:
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock patched output",
                parsed_output={"mock": "patched_data"},
                status="correct",  # Mock 假设所有都正确
            )
            self.patched_extraction_results.append(result)

    def _step7_regression_and_toxicity_test(self) -> None:
        """Step 7: 回归分析、无效剔除与测毒。"""
        if self.patch_apply_executor is not None and self.toxicity_test_executor is not None:
            # PR3: 真实 merge + greedy 测毒

            # 1. Transition 分类
            base_eval_map = {r.sample_id: r for r in self.base_eval_records}
            patched_eval_map = {r.sample_id: r for r in self.patched_eval_records}

            fixed_sample_ids: list[str] = []
            broken_sample_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base_record = base_eval_map.get(sample_id)
                patched_record = patched_eval_map.get(sample_id)

                # 缺少 base 或 patched 评估记录时跳过
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

            # 2. 构造 toxic_sample_ids
            toxic_sample_ids = broken_sample_ids

            # 3. 调用 ToxicityTestExecutor
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

            # Populate ineffective_patches from initial_merged_patches
            # (ToxicityTestExecutor marks them with status="rejected", rejection_reason="INEFFECTIVE")
            self.ineffective_patches = [
                p for p in self.initial_merged_patches
                if p.status == "rejected" and getattr(p, "rejection_reason", None) == "INEFFECTIVE"
            ]

            # Populate transition_report
            self.transition_report = {
                "fixed_sample_ids": list(fixed_sample_ids),
                "broken_sample_ids": list(broken_sample_ids),
                "unchanged_wrong_ids": list(unchanged_wrong_ids),
                "unchanged_correct_ids": list(unchanged_correct_ids),
                "toxic_sample_ids": list(toxic_sample_ids),
            }

            # 4. Safe patches 二次 merge
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

            # 5. 应用 final_merged_patches 到 base_prompt
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

            # 6. 更新指标
            self.metrics.accepted_patch_count = len(self.final_merged_patches)
            self.metrics.rejected_patch_count = (
                len(self.rejected_patches) + len(toxic_patches)
            )
            self.metrics.toxic_patch_count = len(toxic_patches)

            # 7. 更新 SampleTrace transition
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

                # 更新状态统计
                state = self.sample_set.states.get(trace.sample_id)
                if state:
                    if trace.transition == "fixed":
                        state.historical_fixed_count += 1
                    elif trace.transition == "broken":
                        state.historical_broken_count += 1
            return

        if self.patch_apply_executor is not None:
            # 使用真实 executor：基于 base_eval_records 和 patched_eval_records
            # 做 transition 分类，只做 patch set 级判断
            base_eval_map = {r.sample_id: r for r in self.base_eval_records}
            patched_eval_map = {r.sample_id: r for r in self.patched_eval_records}

            fixed_sample_ids: list[str] = []
            broken_sample_ids: list[str] = []
            unchanged_wrong_ids: list[str] = []
            unchanged_correct_ids: list[str] = []

            for sample_id in self.batch.sample_ids:
                base_record = base_eval_map.get(sample_id)
                patched_record = patched_eval_map.get(sample_id)

                # 缺少 base 或 patched 评估记录时跳过
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

            # Patch set 级判断
            if broken_count > 0:
                # unsafe：回滚
                self.metrics.rollback = True
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "TOXIC"
                self.final_merged_patches = []
            elif fixed_count > 0:
                # 接受 patch set
                self.accepted_prompt = self.trial_prompt
                for patch in self.initial_merged_patches:
                    patch.status = "accepted"
                self.final_merged_patches = self.initial_merged_patches.copy()
            else:
                # 无收益
                self.metrics.no_progress = True
                self.accepted_prompt = None
                self.final_merged_patches = []

            # 更新指标
            if self.accepted_prompt is not None:
                self.metrics.accepted_patch_count = len(self.initial_merged_patches)
                self.metrics.rejected_patch_count = len(self.rejected_patches)
            else:
                self.metrics.accepted_patch_count = 0
                self.metrics.rejected_patch_count = (
                    len(self.rejected_patches) + len(self.initial_merged_patches)
                )

            # 更新 SampleTrace transition
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

                # 更新状态统计
                state = self.sample_set.states.get(trace.sample_id)
                if state:
                    if trace.transition == "fixed":
                        state.historical_fixed_count += 1
                    elif trace.transition == "broken":
                        state.historical_broken_count += 1
            return

        # Fallback: mock 回归分析与测毒
        if not self.initial_merged_patches:
            return

        # 计算转换分类
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

        # 剔除无效 patch
        for patch in self.initial_merged_patches:
            # 如果所有 source_sample_ids 都属于 unchanged_wrong，则无效
            if all(sid in unchanged_wrong_ids for sid in patch.source_sample_ids):
                patch.status = "rejected"
                patch.rejection_reason = "INEFFECTIVE"

        # 构造中毒样本集合
        toxic_sample_ids = broken_sample_ids

        # 排序剩余 patch
        remaining_patches = [
            p for p in self.initial_merged_patches
            if p.status not in ["rejected"]
        ]

        # 按来源样本难度排序
        remaining_patches.sort(
            key=lambda p: max(
                self.sample_set.states.get(sid, SampleState(sample_id=sid)).difficulty_score
                for sid in p.source_sample_ids
            ),
            reverse=True,
        )

        # Greedy 测毒
        safe_patches: list[ExtractionPatch] = []
        toxic_patches: list[ExtractionPatch] = []

        for patch in remaining_patches:
            # Mock 测毒 - 假设都安全
            patch.status = "candidate_safe"
            safe_patches.append(patch)

        # 重新 Tree Merge
        self.final_merged_patches = safe_patches.copy()
        for patch in self.final_merged_patches:
            patch.status = "accepted"

        # 更新指标
        self.metrics.accepted_patch_count = len(self.final_merged_patches)
        self.metrics.rejected_patch_count = len([
            p for p in self.initial_merged_patches if p.status == "rejected"
        ])
        self.metrics.toxic_patch_count = len(toxic_patches)

        # 创建测毒报告
        self.toxicity_report = ToxicityReport(
            id=f"toxicity_report_{self.iteration}",
            tested_patch_count=len(remaining_patches),
            toxic_patch_count=len(toxic_patches),
            safe_patch_count=len(safe_patches),
            toxic_patches=[p.id for p in toxic_patches],
            safe_patches=[p.id for p in safe_patches],
            toxic_sample_ids=toxic_sample_ids,
        )

        # 更新 SampleTrace
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

            # 更新状态统计
            state = self.sample_set.states.get(trace.sample_id)
            if state:
                if trace.transition == "fixed":
                    state.historical_fixed_count += 1
                elif trace.transition == "broken":
                    state.historical_broken_count += 1

    def _step8_compress_if_needed(self) -> None:
        """Step 8: Prompt 压缩（如果需要）。"""
        if self.compression_executor is None:
            self.metrics.compression_accepted = False
            return

        # Determine the prompt to compress (final_prompt if set, otherwise accepted_prompt)
        prompt_to_compress = self.final_prompt or self.accepted_prompt or self.extraction_prompt
        if prompt_to_compress is None:
            self.metrics.compression_accepted = False
            return

        # Get line/char limits from config or use defaults
        line_limit = getattr(self, "line_limit", 300)
        char_limit = getattr(self, "char_limit", 20000)

        # Use final_eval_records as pre-compression eval if available, else base_eval_records
        pre_eval = self.final_eval_records or self.patched_eval_records or self.base_eval_records

        compressed_prompt, report = self.compression_executor.compress_if_needed(
            prompt=prompt_to_compress,
            line_limit=line_limit,
            char_limit=char_limit,
            batch=self.batch,
            sample_set=self.sample_set,
            mode="extraction",
            extraction_executor=self.extraction_executor,
            evaluation_executor=self.evaluation_executor,
            pre_compression_eval_records=pre_eval,
        )

        self.compression_report = report

        if report.accepted:
            self.final_prompt = compressed_prompt
            self.accepted_prompt = compressed_prompt
            self.metrics.compression_accepted = True
            # Re-run final test with compressed prompt if we have executors
            if self.extraction_executor is not None and self.evaluation_executor is not None:
                self.final_extraction_results = self.extraction_executor.execute(
                    prompt=compressed_prompt, batch=self.batch, sample_set=self.sample_set
                )
                self.final_eval_records = self.evaluation_executor.evaluate(
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
            # 使用真实 executor：基于 accepted_prompt 决定最终 prompt
            if self.accepted_prompt is not None:
                # 使用 accepted_prompt 重新执行抽取和评估
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

                # 计算 final_accuracy
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

                # 更新 SampleTrace
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
            else:
                # 回滚或 no_progress：final_prompt = base_prompt
                self.metrics.final_accuracy = self.metrics.base_accuracy
                self.metrics.no_progress = True
            return

        # Fallback: mock 最终测试
        if not self.final_merged_patches:
            self.metrics.no_progress = True
            self.metrics.final_accuracy = self.metrics.base_accuracy
            return

        # Mock 最终测试
        for sample_id in self.batch.sample_ids:
            result = ExtractionResult(
                sample_id=sample_id,
                raw_output="mock final output",
                parsed_output={"mock": "final_data"},
                status="correct",
            )
            self.final_extraction_results.append(result)

        # 计算最终指标
        correct_count = sum(1 for r in self.final_extraction_results if r.status == "correct")
        total = len(self.final_extraction_results)
        self.metrics.final_correct_count = correct_count
        self.metrics.final_accuracy = correct_count / total if total > 0 else 0.0

        # 更新 SampleTrace
        traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
        for trace in traces:
            trace.final_extraction_status = "correct"
            trace.final_extraction_result_id = trace.sample_id