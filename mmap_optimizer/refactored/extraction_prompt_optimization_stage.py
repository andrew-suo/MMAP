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

from .patch import ExtractionPatch, PatchMergeReport, ToxicityReport
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
    ):
        self.extraction_prompt = extraction_prompt
        self.analysis_prompt = analysis_prompt
        self.sample_set = sample_set
        self.batch = batch
        self.iteration = iteration

        # 结果存储
        self.base_extraction_results: list[ExtractionResult] = []
        self.analysis_results: list[AnalysisResult] = []
        self.draft_patches: list[ExtractionPatch] = []
        self.initial_merged_patches: list[ExtractionPatch] = []
        self.patched_extraction_results: list[ExtractionResult] = []
        self.final_merged_patches: list[ExtractionPatch] = []
        self.final_extraction_results: list[ExtractionResult] = []

        # 指标
        self.metrics = ExtractionMetrics()

        # 报告
        self.initial_merge_report: PatchMergeReport | None = None
        self.final_merge_report: PatchMergeReport | None = None
        self.toxicity_report: ToxicityReport | None = None

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
        # 这里需要调用模型执行抽取，第一版使用 mock 实现
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
        # 这里需要调用 analysis prompt 进行分析，第一版使用 mock 实现
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
        if not self.initial_merged_patches:
            self.metrics.no_progress = True
            return

        # Mock 应用 patch 并测试
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
        # 第一版暂不实现压缩
        self.metrics.compression_accepted = False

    def _step9_final_test_and_metrics(self) -> None:
        """Step 9: 最终测试与统计。"""
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