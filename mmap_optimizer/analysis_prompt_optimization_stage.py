"""Analysis Prompt Optimization Stage。

根据设计文档，该 stage 负责优化 analysis prompt，包含 8 个步骤：
1. 统计分析准确率
2. 对分析错误样本反思
3. 生成 analysis prompt patch
4. Tree Merge 生成 analysis patch
5. 应用 analysis patch 并回归测试
6. 回归分析、无效剔除与测毒
7. Analysis Prompt 压缩
8. 最终测试与统计
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .extraction_prompt_optimization_stage import AnalysisResult, ExtractionResult
from .patch_types import AnalysisPatch, CompressionReport, PatchMergeReport, ToxicityReport
from .sample import SampleBatch, SampleSet, SampleTrace
from .structured_prompt import StructuredPrompt


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
        analysis_executor=None,    # AnalysisExecutor 实例
        patch_generation_executor=None,  # PatchGenerationExecutor 实例
        patch_apply_executor=None,       # PatchApplyExecutor 实例
        extraction_prompt=None,          # StructuredPrompt 实例（用于 generate_analysis_patches 和 execute_batch）
        merge_executor=None,             # MergeExecutor 实例
        toxicity_test_executor=None,     # ToxicityTestExecutor 实例
        compression_executor=None,       # CompressionExecutor 实例
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

        # 结果存储
        self.reflection_results: list[ReflectionResult] = []
        self.draft_patches: list[AnalysisPatch] = []
        self.validated_patches: list[AnalysisPatch] = []
        self.rejected_patches: list[AnalysisPatch] = []
        self.initial_merged_patches: list[AnalysisPatch] = []
        self.patched_analysis_results: list[AnalysisResult] = []
        self.final_merged_patches: list[AnalysisPatch] = []
        self.final_analysis_results: list[AnalysisResult] = []

        # PR3 测毒结果存储
        self.ineffective_patches: list[AnalysisPatch] = []
        self.safe_patches: list[AnalysisPatch] = []
        self.toxic_patches: list[AnalysisPatch] = []
        self.final_prompt: StructuredPrompt | None = None

        # Patch 应用相关
        self.patched_prompt: StructuredPrompt | None = None
        self.patch_apply_report = None
        self.accepted_prompt: StructuredPrompt | None = None
        self.trial_prompt: StructuredPrompt | None = None

        # 指标
        self.metrics = AnalysisMetrics()

        # 报告
        self.initial_merge_report: PatchMergeReport | None = None
        self.final_merge_report: PatchMergeReport | None = None
        self.toxicity_report: ToxicityReport | None = None
        self.compression_report: CompressionReport | None = None
        self.transition_report: dict[str, Any] | None = None

    def run(self) -> AnalysisMetrics:
        """执行完整的 Analysis Prompt Optimization Stage。"""
        # Step 1: 统计分析准确率
        self._step1_compute_base_metrics()

        # Step 2: 对分析错误样本反思
        self._step2_reflect_on_errors()

        # Step 3: 生成 analysis prompt patch
        self._step3_generate_patches()

        # Step 4: Tree Merge 生成 analysis patch
        self._step4_initial_merge()

        # Step 5: 应用 analysis patch 并回归测试
        self._step5_apply_and_test()

        # Step 6: 回归分析、无效剔除与测毒
        self._step6_regression_and_toxicity_test()

        # Step 7: Analysis Prompt 压缩
        self._step7_compress_if_needed()

        # Step 8: 最终测试与统计
        self._step8_final_test_and_metrics()

        return self.metrics

    def _step1_compute_base_metrics(self) -> None:
        """Step 1: 统计分析准确率。"""
        correct_count = sum(1 for r in self.base_analysis_results if r.analysis_correct)
        wrong_count = sum(1 for r in self.base_analysis_results if not r.analysis_correct)
        total = len(self.base_analysis_results)

        self.metrics.base_correct_count = correct_count
        self.metrics.base_wrong_count = wrong_count
        self.metrics.base_accuracy = correct_count / total if total > 0 else 0.0

    def _step2_reflect_on_errors(self) -> None:
        """Step 2: 对分析错误样本反思。"""
        # 找出分析错误的样本
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
                # 使用真实 executor 反思
                reflection = self.analysis_executor.reflect(
                    self.analysis_prompt,
                    extraction_result,
                    base_analysis,
                    spec,
                )
            else:
                # Mock 反思结果
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

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == sample_id:
                    trace.reflection_result_id = reflection.sample_id
                    trace.reflection_success = reflection.reflection_success

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

            # 更新 SampleTrace 的 generated_analysis_patch_ids
            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for patch in self.draft_patches:
                for trace in traces:
                    if trace.sample_id in patch.source_sample_ids:
                        trace.generated_analysis_patch_ids.append(patch.id)
            return

        # Mock fallback
        for reflection in self.reflection_results:
            if not reflection.reflection_success or reflection.patch_suggestion is None:
                continue

            suggestion = reflection.patch_suggestion
            patch = AnalysisPatch(
                id=f"patch_analysis_{reflection.sample_id}",
                target_section_id=suggestion.get("target_section", "section_1"),
                operation_type=suggestion.get("operation", "replace"),
                content=suggestion.get("content", "Mock analysis patch content"),
                rationale=f"Based on reflection for sample {reflection.sample_id}",
                source_sample_ids=[reflection.sample_id],
                status="draft",
            )
            self.draft_patches.append(patch)

            # 更新 SampleTrace
            traces = self.sample_set.get_traces_for_iteration("prompt_optimization", self.iteration)
            for trace in traces:
                if trace.sample_id == reflection.sample_id:
                    trace.generated_analysis_patch_ids.append(patch.id)

    def _step4_initial_merge(self) -> None:
        """Step 4: Tree Merge 生成 analysis patch。"""
        if self.merge_executor is not None:
            # PR3: 使用真实 MergeExecutor
            merged_patches, merge_report = self.merge_executor.merge(
                patches=self.validated_patches,
                prompt=self.analysis_prompt,
                merge_strategy="tree_merge",
                sample_set=self.sample_set,
            )
            self.initial_merged_patches = merged_patches
            self.initial_merge_report = merge_report
            return

        if self.patch_generation_executor is not None:
            # Passthrough merge：直接使用 validated_patches，不修改 patch status
            self.initial_merged_patches = self.validated_patches.copy()

            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_analysis_initial_{self.iteration}",
                input_patch_count=len(self.draft_patches),
                merged_patch_count=len(self.initial_merged_patches),
                conflict_count=0,
                merged_patches=[p.to_dict() for p in self.initial_merged_patches],
                metadata={"merge_strategy": "passthrough"},
            )
            return

        # Mock fallback
        if not self.draft_patches:
            self.initial_merge_report = PatchMergeReport(
                id=f"merge_report_analysis_initial_{self.iteration}",
                input_patch_count=0,
                merged_patch_count=0,
                conflict_count=0,
            )
            return

        # Mock tree merge
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
                return

            # 复用本轮 extraction results 重新执行 AnalysisExecutor
            if self.analysis_executor is not None:
                self.patched_analysis_results = self.analysis_executor.execute_batch(
                    analysis_prompt=trial_prompt,
                    extraction_prompt=self.extraction_prompt,  # 可能为 None
                    extraction_results=self.extraction_results,
                    sample_set=self.sample_set,
                )
            return

        # Mock fallback
        if not self.initial_merged_patches:
            self.metrics.no_progress = True
            return

        # Mock 应用 patch 并重新分析
        for extraction_result in self.extraction_results:
            # Mock patched analysis result
            analysis_result = AnalysisResult(
                sample_id=extraction_result.sample_id,
                judgement={"mock": "patched_judgement"},
                analysis_correct=True,  # Mock 假设都正确
            )
            self.patched_analysis_results.append(analysis_result)

    def _step6_regression_and_toxicity_test(self) -> None:
        """Step 6: 回归分析、无效剔除与测毒。"""
        if self.patch_apply_executor is not None and self.toxicity_test_executor is not None:
            # PR3: 真实 merge + greedy 测毒

            # 1. Analysis transition 分类
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

            # 2. 构造 analysis_toxic_sample_ids
            toxic_sample_ids = broken_ids

            # 3. 调用 ToxicityTestExecutor (analysis mode)
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

            # Populate ineffective_patches from initial_merged_patches
            self.ineffective_patches = [
                p for p in self.initial_merged_patches
                if p.status == "rejected" and getattr(p, "rejection_reason", None) == "INEFFECTIVE"
            ]

            # Populate transition_report
            self.transition_report = {
                "fixed_sample_ids": list(fixed_ids),
                "broken_sample_ids": list(broken_ids),
                "unchanged_wrong_ids": list(unchanged_wrong_ids),
                "unchanged_correct_ids": list(unchanged_correct_ids),
                "toxic_sample_ids": list(toxic_sample_ids),
            }

            # 4. Safe patches 二次 merge
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

            # 5. 应用 final_merged_patches 到 base analysis prompt
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

            # 6. 更新指标
            self.metrics.accepted_patch_count = len(self.final_merged_patches)
            self.metrics.rejected_patch_count = (
                len(self.rejected_patches) + len(toxic_patches)
            )

            # 7. 更新 SampleTrace transition
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
            return

        if self.patch_apply_executor is not None:
            # 使用 base_analysis_results 和 patched_analysis_results 做 transition 分类
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

            # 计算 patched analysis accuracy
            patched_correct = sum(
                1 for r in self.patched_analysis_results if r.analysis_correct
            )
            patched_total = len(self.patched_analysis_results)
            patched_accuracy = (
                patched_correct / patched_total if patched_total > 0 else 0.0
            )
            base_accuracy = self.metrics.base_accuracy or 0.0

            # 接受/拒绝规则
            if broken_ids:
                # unsafe：有 broken → rollback
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "TOXIC"
                self.final_merged_patches = []
            elif not fixed_ids:
                # 无收益：fixed = 0 → no_progress
                self.metrics.no_progress = True
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "INEFFECTIVE"
                self.final_merged_patches = []
            elif patched_accuracy >= base_accuracy:
                # 接受规则：patched_accuracy >= base_accuracy 且无 broken
                self.accepted_prompt = self.trial_prompt
                self.final_merged_patches = self.initial_merged_patches.copy()
                for patch in self.final_merged_patches:
                    patch.status = "accepted"
            else:
                # 回归：patched_accuracy < base_accuracy 但无 broken
                self.accepted_prompt = None
                for patch in self.initial_merged_patches:
                    patch.status = "rejected"
                    patch.rejection_reason = "REGRESSION"
                self.final_merged_patches = []

            # 更新指标
            self.metrics.accepted_patch_count = len(self.final_merged_patches)
            self.metrics.rejected_patch_count = (
                len(self.initial_merged_patches) - len(self.final_merged_patches)
            )

            # 创建测毒报告
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

            # 更新 SampleTrace transition
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
            return

        # Mock fallback
        if not self.initial_merged_patches:
            return

        # 计算转换分类
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

        # 剔除无效 patch
        for patch in self.initial_merged_patches:
            if all(sid in unchanged_wrong_ids for sid in patch.source_sample_ids):
                patch.status = "rejected"
                patch.rejection_reason = "INEFFECTIVE"

        # 构造中毒样本集合
        toxic_sample_ids = broken_ids

        # 排序剩余 patch
        remaining_patches = [
            p for p in self.initial_merged_patches
            if p.status not in ["rejected"]
        ]

        # Greedy 测毒
        safe_patches: list[AnalysisPatch] = []
        toxic_patches: list[AnalysisPatch] = []

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

        # 创建测毒报告
        self.toxicity_report = ToxicityReport(
            id=f"toxicity_report_analysis_{self.iteration}",
            tested_patch_count=len(remaining_patches),
            toxic_patch_count=len(toxic_patches),
            safe_patch_count=len(safe_patches),
            toxic_patches=[p.id for p in toxic_patches],
            safe_patches=[p.id for p in safe_patches],
            toxic_sample_ids=toxic_sample_ids,
        )

    def _step7_compress_if_needed(self) -> None:
        """Step 7: Analysis Prompt 压缩。"""
        if self.compression_executor is None:
            self.metrics.compression_accepted = False
            return

        prompt_to_compress = self.final_prompt or self.accepted_prompt or self.analysis_prompt
        if prompt_to_compress is None:
            self.metrics.compression_accepted = False
            return

        line_limit = getattr(self, "line_limit", 250)
        char_limit = getattr(self, "char_limit", 16000)

        # Use final_analysis_results as pre-compression if available
        pre_analysis = self.final_analysis_results or self.patched_analysis_results or self.base_analysis_results

        compressed_prompt, report = self.compression_executor.compress_if_needed(
            prompt=prompt_to_compress,
            line_limit=line_limit,
            char_limit=char_limit,
            batch=self.batch,
            sample_set=self.sample_set,
            mode="analysis",
            analysis_executor=self.analysis_executor,
            extraction_prompt=self.extraction_prompt,
            extraction_results=self.extraction_results,
            pre_compression_analysis_results=pre_analysis,
        )

        self.compression_report = report

        if report.accepted:
            self.final_prompt = compressed_prompt
            self.accepted_prompt = compressed_prompt
            self.metrics.compression_accepted = True
            # Re-run final analysis test with compressed prompt
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
                # 使用 accepted_prompt 重新执行 AnalysisExecutor
                if self.analysis_executor is not None:
                    self.final_analysis_results = self.analysis_executor.execute_batch(
                        analysis_prompt=self.accepted_prompt,
                        extraction_prompt=self.extraction_prompt,  # 可能为 None
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
                    # 无 analysis_executor，复用 patched_analysis_results
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
            else:
                # accepted_prompt is None
                self.metrics.no_progress = True
                self.metrics.final_accuracy = self.metrics.base_accuracy
            return

        # Mock fallback
        if not self.final_merged_patches:
            self.metrics.no_progress = True
            self.metrics.final_accuracy = self.metrics.base_accuracy
            return

        # Mock 最终测试
        for extraction_result in self.extraction_results:
            analysis_result = AnalysisResult(
                sample_id=extraction_result.sample_id,
                judgement={"mock": "final_judgement"},
                analysis_correct=True,
            )
            self.final_analysis_results.append(analysis_result)

        # 计算最终指标
        correct_count = sum(1 for r in self.final_analysis_results if r.analysis_correct)
        total = len(self.final_analysis_results)
        self.metrics.final_correct_count = correct_count
        self.metrics.final_accuracy = correct_count / total if total > 0 else 0.0