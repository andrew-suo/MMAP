"""Prompt Optimization Phase。

根据设计文档，Prompt Optimization Phase 每次迭代包含三个 stage：
1. Sampling Stage
2. Extraction Prompt Optimization Stage
3. Analysis Prompt Optimization Stage
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..stages.analysis_prompt_optimization import AnalysisMetrics, AnalysisPromptOptimizationStage
from ..stages.batch_size_controller import BatchSizeController, BatchSizeControllerConfig
from ..stages.extraction_prompt_optimization import ExtractionMetrics, ExtractionPromptOptimizationStage
from ..data.sampler import SamplerConfig, create_sampler
from ..data.sample import SampleBatch, SampleSet, SampleTrace
from ..prompt.structured_prompt import StructuredPrompt


@dataclass
class MultiSeedConfig:
    """Multi-seed candidate sampling 配置。"""
    enabled: bool = False
    seed_count: int = 3
    candidate_batch_size: int | None = None
    merge_candidates_before_selection: bool = True


@dataclass
class PromptOptimizationConfig:
    """Prompt Optimization 配置。"""
    enabled: bool = True
    rounds: int = 3
    initial_batch_size: int = 16
    min_batch_size: int = 8
    max_batch_size: int = 99

    # Batch Size Controller
    batch_size_controller: BatchSizeControllerConfig = field(default_factory=BatchSizeControllerConfig)

    # Sampler
    sampler: SamplerConfig = field(default_factory=lambda: SamplerConfig(type="difficulty_frequency"))

    # Extraction Prompt
    extraction_prompt_line_limit: int = 300
    extraction_prompt_char_limit: int = 20000
    extraction_prompt_compression_enabled: bool = True

    # Analysis Prompt
    analysis_prompt_line_limit: int = 250
    analysis_prompt_char_limit: int = 16000
    analysis_prompt_compression_enabled: bool = True

    # Compression
    ema_alpha: float = 0.3

    # Patch
    patch_merge_strategy: str = "tree_merge"
    toxicity_test_enabled: bool = True
    toxicity_test_early_stop: bool = True
    toxicity_test_sort_by_source_difficulty: bool = True
    patch_generation_mode: str = "semantic_then_translate"
    candidate_selection_enabled: bool = False
    candidate_count: int = 3
    candidate_validation_split_ratio: float = 0.3
    candidate_min_gain: float = 0.0
    candidate_reject_on_any_broken: bool = True
    validation_pool_enabled: bool = True
    validation_batch_size: int | None = None
    validation_exclude_optimization_batch: bool = True

    # Multi-seed candidate sampling
    multi_seed: MultiSeedConfig = field(default_factory=MultiSeedConfig)


@dataclass
class PromptOptimizationIterationResult:
    """Prompt Optimization 单轮迭代结果。"""
    iteration: int
    batch: SampleBatch
    extraction_metrics: ExtractionMetrics
    analysis_metrics: AnalysisMetrics
    extraction_prompt: StructuredPrompt
    analysis_prompt: StructuredPrompt
    rollback: bool = False
    no_progress: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iteration": self.iteration,
            "batch_id": self.batch.id,
            "extraction_metrics": self.extraction_metrics.to_dict(),
            "analysis_metrics": self.analysis_metrics.to_dict(),
            "extraction_prompt_id": self.extraction_prompt.id,
            "analysis_prompt_id": self.analysis_prompt.id,
            "rollback": self.rollback,
            "no_progress": self.no_progress,
            "notes": list(self.notes),
        }


class PromptOptimizationPhase:
    """Prompt Optimization Phase。"""

    def __init__(
        self,
        config: PromptOptimizationConfig,
        extraction_prompt: StructuredPrompt,
        analysis_prompt: StructuredPrompt,
        sample_set: SampleSet,
        output_dir: Path,
        seed: int = 42,
        executors: dict[str, Any] | None = None,
        checkpoint_callback: Callable[[int, "PromptOptimizationPhase"], None] | None = None,
    ):
        self.config = config
        self.extraction_prompt = extraction_prompt
        self.analysis_prompt = analysis_prompt
        self.sample_set = sample_set
        self.output_dir = output_dir
        self.seed = seed
        # executor 字典，默认为空（stage 内部会回退到 mock）
        self.executors = executors or {}
        self.checkpoint_callback = checkpoint_callback

        # 创建 sampler
        self.sampler = create_sampler(config.sampler)

        # 创建 batch size controller
        self.batch_size_controller = BatchSizeController(config.batch_size_controller)

        # 结果存储
        self.iteration_results: list[PromptOptimizationIterationResult] = []
        self.prompt_versions: list[dict[str, Any]] = []
        self.patch_apply_reports: list[dict[str, Any]] = []
        # PR4: 暴露每轮 stage 实例，供 runner 读取 compression_report
        self.extraction_stages: list[ExtractionPromptOptimizationStage] = []
        self.analysis_stages: list[AnalysisPromptOptimizationStage] = []
        self.sampling_plans: dict[int, dict[str, Any]] = {}

    def run(self, start_iteration: int = 1) -> list[PromptOptimizationIterationResult]:
        """执行完整的 Prompt Optimization Phase。"""
        if not self.config.enabled:
            return []

        max_iterations = self.config.rounds
        prev_accuracy: float | None = None

        for iteration in range(start_iteration, max_iterations + 1):
            print(f"\n--- Phase 2: Prompt 优化 - 迭代 {iteration}/{max_iterations} ---")
            result = self._run_iteration(iteration)
            self.iteration_results.append(result)

            # 输出当前准确率
            current_accuracy = result.extraction_metrics.final_accuracy
            if current_accuracy is not None:
                print(f"迭代 {iteration} 完成，当前准确率: {current_accuracy:.2%}")
                # 准确率变化判断
                if prev_accuracy is not None:
                    if current_accuracy > prev_accuracy:
                        print(f"📈 准确率提升: {prev_accuracy:.2%} → {current_accuracy:.2%}")
                    elif current_accuracy < prev_accuracy:
                        print(f"⚠️ 准确率下降: {prev_accuracy:.2%} → {current_accuracy:.2%}")
                    else:
                        print(f"⚠️ 准确率未提升，保持: {current_accuracy:.2%}")
                prev_accuracy = current_accuracy
            else:
                print(f"迭代 {iteration} 完成")

            # 更新 batch size controller
            if result.extraction_metrics.base_accuracy is not None:
                self.batch_size_controller.update(
                    base_accuracy=result.extraction_metrics.base_accuracy,
                    final_accuracy=result.extraction_metrics.final_accuracy,
                    rollback=result.rollback,
                    no_progress=result.no_progress,
                )
            if self.checkpoint_callback is not None:
                self.checkpoint_callback(iteration, self)

        return self.iteration_results

    def _run_iteration(self, iteration: int) -> PromptOptimizationIterationResult:
        """执行单轮迭代。"""
        # PR4: 捕获 iteration 开始前的状态
        import copy
        batch_size_before = copy.deepcopy(self.batch_size_controller)
        sample_states_before = {
            sid: copy.deepcopy(state) for sid, state in self.sample_set.states.items()
        }

        # Stage 1: Sampling Stage
        batch = self._sampling_stage(iteration)
        validation_batch = self._validation_sampling_stage(batch, iteration)
        candidate_batches = self._candidate_sampling_stage(batch, iteration)
        self.sampling_plans[iteration] = {
            "optimization_batch_id": batch.id,
            "optimization_sample_ids": list(batch.sample_ids),
            "validation_batch_id": validation_batch.id if validation_batch else None,
            "validation_sample_ids": list(validation_batch.sample_ids) if validation_batch else [],
            "candidate_batches": [
                {
                    "batch_id": candidate_batch.id,
                    "sample_ids": list(candidate_batch.sample_ids),
                    "seed_index": candidate_batch.metadata.get("seed_index"),
                }
                for candidate_batch in candidate_batches
            ],
            "multi_seed_enabled": self.config.multi_seed.enabled,
            "validation_pool_enabled": self.config.validation_pool_enabled,
        }

        # Stage 2: Extraction Prompt Optimization Stage
        extraction_stage = ExtractionPromptOptimizationStage(
            extraction_prompt=self.extraction_prompt,
            analysis_prompt=self.analysis_prompt,
            sample_set=self.sample_set,
            batch=batch,
            iteration=iteration,
            extraction_executor=self.executors.get("extraction"),
            evaluation_executor=self.executors.get("evaluation"),
            analysis_executor=self.executors.get("analysis"),
            patch_generation_executor=self.executors.get("patch_generation"),
            patch_apply_executor=self.executors.get("patch_apply"),
            merge_executor=self.executors.get("merge"),
            toxicity_test_executor=self.executors.get("toxicity_test"),
            compression_executor=self.executors.get("compression"),
            line_limit=self.config.extraction_prompt_line_limit,
            char_limit=self.config.extraction_prompt_char_limit,
            compression_enabled=self.config.extraction_prompt_compression_enabled,
            ema_alpha=self.config.ema_alpha,
            candidate_selection_enabled=self.config.candidate_selection_enabled,
            candidate_count=self.config.candidate_count,
            candidate_min_gain=self.config.candidate_min_gain,
            candidate_reject_on_any_broken=self.config.candidate_reject_on_any_broken,
            validation_batch=validation_batch,
            candidate_batches=candidate_batches,
        )
        extraction_metrics = extraction_stage.run()
        self.extraction_stages.append(extraction_stage)

        # 更新 extraction prompt（使用 accepted_prompt 而非仅自增 version）
        if extraction_stage.accepted_prompt is not None:
            old_prompt_id = self.extraction_prompt.id
            old_version = self.extraction_prompt.version
            self.extraction_prompt = extraction_stage.accepted_prompt
            self._record_prompt_lineage(
                stage="extraction",
                iteration=iteration,
                base_prompt_id=old_prompt_id,
                new_prompt_id=self.extraction_prompt.id,
                version=self.extraction_prompt.version,
                apply_report=extraction_stage.patch_apply_report,
            )

        # Stage 3: Analysis Prompt Optimization Stage
        analysis_stage = AnalysisPromptOptimizationStage(
            analysis_prompt=self.analysis_prompt,
            extraction_results=extraction_stage.base_extraction_results,
            base_analysis_results=extraction_stage.analysis_results,
            sample_set=self.sample_set,
            batch=batch,
            iteration=iteration,
            analysis_executor=self.executors.get("analysis"),
            patch_generation_executor=self.executors.get("patch_generation"),
            patch_apply_executor=self.executors.get("patch_apply"),
            extraction_prompt=self.extraction_prompt,
            merge_executor=self.executors.get("merge"),
            toxicity_test_executor=self.executors.get("toxicity_test"),
            compression_executor=self.executors.get("compression"),
            line_limit=self.config.analysis_prompt_line_limit,
            char_limit=self.config.analysis_prompt_char_limit,
            compression_enabled=self.config.analysis_prompt_compression_enabled,
            ema_alpha=self.config.ema_alpha,
            candidate_selection_enabled=self.config.candidate_selection_enabled,
            candidate_count=self.config.candidate_count,
            candidate_min_gain=self.config.candidate_min_gain,
            candidate_reject_on_any_broken=self.config.candidate_reject_on_any_broken,
            validation_batch=validation_batch,
            candidate_batches=candidate_batches,
        )
        analysis_metrics = analysis_stage.run()
        self.analysis_stages.append(analysis_stage)

        # 更新 analysis prompt（使用 accepted_prompt 而非仅自增 version）
        if analysis_stage.accepted_prompt is not None:
            old_prompt_id = self.analysis_prompt.id
            old_version = self.analysis_prompt.version
            self.analysis_prompt = analysis_stage.accepted_prompt
            self._record_prompt_lineage(
                stage="analysis",
                iteration=iteration,
                base_prompt_id=old_prompt_id,
                new_prompt_id=self.analysis_prompt.id,
                version=self.analysis_prompt.version,
                apply_report=analysis_stage.patch_apply_report,
            )

        # 构造结果
        rollback = extraction_metrics.rollback or extraction_metrics.no_progress
        no_progress = extraction_metrics.no_progress and analysis_metrics.no_progress

        result = PromptOptimizationIterationResult(
            iteration=iteration,
            batch=batch,
            extraction_metrics=extraction_metrics,
            analysis_metrics=analysis_metrics,
            extraction_prompt=self.extraction_prompt,
            analysis_prompt=self.analysis_prompt,
            rollback=rollback,
            no_progress=no_progress,
        )

        # 保存 artifact
        self._save_iteration_artifacts(
            iteration,
            extraction_stage,
            analysis_stage,
            result,
            batch_size_before=batch_size_before,
            sample_states_before=sample_states_before,
        )

        return result

    def _sampling_stage(self, iteration: int) -> SampleBatch:
        """Sampling Stage。"""
        batch_size = self.batch_size_controller.get_current_batch_size()

        batch = self.sampler.sample(
            sample_set=self.sample_set,
            batch_size=batch_size,
            iteration=iteration,
            seed=self.seed,
        )

        # 设置 phase
        batch.phase = "prompt_optimization"

        # 清除该轮次的旧 traces
        self.sample_set.clear_traces_for_iteration("prompt_optimization", iteration)

        # 为每个被选中的样本创建 trace
        for sample_id in batch.sample_ids:
            trace = SampleTrace(
                sample_id=sample_id,
                phase="prompt_optimization",
                iteration=iteration,
                selected=True,
            )
            self.sample_set.add_trace(trace)

        # 为未被选中的样本创建 trace
        active_specs = self.sample_set.get_active_specs()
        for spec in active_specs:
            if spec.id not in batch.sample_ids:
                trace = SampleTrace(
                    sample_id=spec.id,
                    phase="prompt_optimization",
                    iteration=iteration,
                    selected=False,
                )
                self.sample_set.add_trace(trace)

        return batch

    def _validation_sampling_stage(
        self,
        optimization_batch: SampleBatch,
        iteration: int,
    ) -> SampleBatch | None:
        """抽取 candidate selection 使用的 validation batch。"""
        if not self.config.candidate_selection_enabled or not self.config.validation_pool_enabled:
            return None

        batch_size = self.config.validation_batch_size
        if batch_size is None:
            import math
            batch_size = max(
                3,
                math.ceil(len(optimization_batch.sample_ids) * self.config.candidate_validation_split_ratio),
            )

        excluded = set(optimization_batch.sample_ids) if self.config.validation_exclude_optimization_batch else set()
        validation_batch = self.sampler.sample_validation(
            sample_set=self.sample_set,
            batch_size=batch_size,
            iteration=iteration,
            seed=self.seed + 10_000,
            excluded_sample_ids=excluded,
        )
        fallback_used = False
        if not validation_batch.sample_ids and excluded:
            validation_batch = self.sampler.sample_validation(
                sample_set=self.sample_set,
                batch_size=batch_size,
                iteration=iteration,
                seed=self.seed + 10_000,
                excluded_sample_ids=set(),
            )
            fallback_used = True
            validation_batch.warnings.append("validation pool fallback used because excluded pool was empty")
        validation_batch.metadata["validation_pool_fallback_used"] = fallback_used
        validation_batch.metadata["excluded_optimization_batch"] = bool(excluded)
        return validation_batch

    def _candidate_sampling_stage(
        self,
        optimization_batch: SampleBatch,
        iteration: int,
    ) -> list[SampleBatch]:
        """为 multi-seed candidate generation 抽取额外 batch。"""
        if not self.config.multi_seed.enabled:
            return []
        seed_count = max(0, self.config.multi_seed.seed_count)
        batch_size = self.config.multi_seed.candidate_batch_size or len(optimization_batch.sample_ids)
        candidate_batches: list[SampleBatch] = []
        for seed_idx in range(seed_count):
            candidate_seed = self.seed + iteration * 100 + seed_idx
            candidate_batch = self.sampler.sample(
                sample_set=self.sample_set,
                batch_size=batch_size,
                iteration=iteration,
                seed=candidate_seed,
                update_state=False,
                batch_id_prefix=f"candidate_batch_{seed_idx + 1}",
            )
            candidate_batch.phase = "prompt_optimization_candidate"
            candidate_batch.metadata["seed_index"] = seed_idx + 1
            candidate_batch.metadata["seed"] = candidate_seed
            candidate_batches.append(candidate_batch)
        return candidate_batches

    def _record_prompt_lineage(
        self,
        stage: str,
        iteration: int,
        base_prompt_id: str,
        new_prompt_id: str,
        version: int,
        apply_report=None,
    ) -> None:
        """记录 prompt lineage。"""
        import json

        lineage = {
            "stage": stage,
            "iteration": iteration,
            "base_prompt_id": base_prompt_id,
            "new_prompt_id": new_prompt_id,
            "version": version,
            "applied_patch_ids": apply_report.applied_patch_ids if apply_report else [],
        }
        self.prompt_versions.append(lineage)

        if apply_report is not None:
            report_dict = apply_report.to_dict() if hasattr(apply_report, "to_dict") else dict(apply_report)
            report_dict["stage"] = stage
            report_dict["iteration"] = iteration
            self.patch_apply_reports.append(report_dict)

            # 保存到文件
            lineage_file = self.output_dir / "prompt_versions.jsonl"
            lineage_file.parent.mkdir(parents=True, exist_ok=True)
            with open(lineage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(lineage, ensure_ascii=False) + "\n")

            report_file = self.output_dir / "patch_apply_reports.jsonl"
            with open(report_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(report_dict, ensure_ascii=False) + "\n")
        else:
            # 即使无 apply_report 也需保存 prompt lineage
            lineage_file = self.output_dir / "prompt_versions.jsonl"
            lineage_file.parent.mkdir(parents=True, exist_ok=True)
            with open(lineage_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(lineage, ensure_ascii=False) + "\n")

    def _save_iteration_artifacts(
        self,
        iteration: int,
        extraction_stage: ExtractionPromptOptimizationStage,
        analysis_stage: AnalysisPromptOptimizationStage,
        result: PromptOptimizationIterationResult,
        batch_size_before=None,
        sample_states_before=None,
    ) -> None:
        """保存单轮迭代的 artifacts。"""
        import json

        def _write_jsonl(path: Path, items: list) -> None:
            """将列表写入 JSONL 文件。"""
            with open(path, "w", encoding="utf-8") as f:
                for item in items:
                    data = item.to_dict() if hasattr(item, "to_dict") else item
                    f.write(json.dumps(data, ensure_ascii=False) + "\n")

        def _write_json(path: Path, data: Any) -> None:
            """将数据写入 JSON 文件。"""
            d = data.to_dict() if hasattr(data, "to_dict") else data
            path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

        def _success_memory_items(results: list, prompt_type: str) -> list[dict[str, Any]]:
            """从正确样本的 section attribution 中提炼成功记忆 artifact。"""
            items: list[dict[str, Any]] = []
            for result in results:
                if not getattr(result, "analysis_correct", False):
                    continue
                judgement = getattr(result, "judgement", {})
                if not isinstance(judgement, dict):
                    continue
                attributions = judgement.get("prompt_section_attribution", [])
                if not isinstance(attributions, list):
                    continue
                for attribution in attributions:
                    if not isinstance(attribution, dict):
                        continue
                    section_id = attribution.get("section_id")
                    if not section_id:
                        continue
                    reason = attribution.get("reason", "")
                    section_name = attribution.get("section_name", "")
                    items.append({
                        "sample_id": getattr(result, "sample_id", ""),
                        "prompt_type": prompt_type,
                        "section_id": section_id,
                        "section_name": section_name,
                        "reason": reason,
                        "generalized_lesson": reason,
                    })
            return items

        def _annotate_merge_report(report: Any) -> None:
            """为 merge report 附加简要决策摘要。"""
            if report is None or not hasattr(report, "metadata"):
                return
            report.metadata["merge_decision_summary"] = {
                "input_patch_count": getattr(report, "input_patch_count", 0),
                "merged_patch_count": getattr(report, "merged_patch_count", 0),
                "dropped_patch_count": getattr(report, "dropped_patch_count", 0),
                "conflict_count": getattr(report, "conflict_count", 0),
                "fallback_used": getattr(report, "fallback_used", False),
            }

        def _patch_lifecycle(stage: Any, prompt_type: str) -> list[dict[str, Any]]:
            """生成 patch 生命周期 artifact，并补充 final decision metadata。"""
            ordered: dict[str, Any] = {}
            phases = [
                ("draft", getattr(stage, "draft_patches", [])),
                ("validated", getattr(stage, "validated_patches", [])),
                ("rejected", getattr(stage, "rejected_patches", [])),
                ("initial_merged", getattr(stage, "initial_merged_patches", [])),
                ("safe", getattr(stage, "safe_patches", [])),
                ("toxic", getattr(stage, "toxic_patches", [])),
                ("final_merged", getattr(stage, "final_merged_patches", [])),
            ]
            phase_by_id: dict[str, list[str]] = {}
            for phase, patches in phases:
                for patch in patches:
                    ordered.setdefault(patch.id, patch)
                    phase_by_id.setdefault(patch.id, []).append(phase)

            records: list[dict[str, Any]] = []
            for patch_id, patch in ordered.items():
                phases_seen = phase_by_id.get(patch_id, [])
                if "final_merged" in phases_seen or getattr(patch, "status", None) == "accepted":
                    final_decision = "accepted"
                elif "toxic" in phases_seen or getattr(patch, "rejection_reason", None) == "TOXIC":
                    final_decision = "toxic"
                elif getattr(patch, "rejection_reason", None) == "INEFFECTIVE":
                    final_decision = "ineffective"
                elif getattr(patch, "status", None) == "rejected" or "rejected" in phases_seen:
                    final_decision = "rejected"
                else:
                    final_decision = getattr(patch, "status", "unknown")

                decision_reason = getattr(patch, "rejection_reason", None) or final_decision
                metadata = getattr(patch, "metadata", {})
                metadata["final_decision"] = final_decision
                metadata["decision_reason"] = decision_reason
                if "source_phase" not in metadata:
                    metadata["source_phase"] = f"{prompt_type}_patch_generation"

                records.append({
                    "patch_id": patch.id,
                    "prompt_type": prompt_type,
                    "phases": phases_seen,
                    "status": getattr(patch, "status", None),
                    "final_decision": final_decision,
                    "decision_reason": decision_reason,
                    "source_sample_ids": list(getattr(patch, "source_sample_ids", [])),
                    "fixed_sample_ids": list(getattr(patch, "fixed_sample_ids", [])),
                    "broken_sample_ids": list(getattr(patch, "broken_sample_ids", [])),
                    "toxic_sample_ids": list(getattr(patch, "toxic_sample_ids", [])),
                    "rejection_reason": getattr(patch, "rejection_reason", None),
                    "metadata": dict(metadata),
                })
            return records

        iteration_dir = self.output_dir / "prompt_optimization" / f"iteration_{iteration}"
        iteration_dir.mkdir(parents=True, exist_ok=True)

        # 保存 batch
        (iteration_dir / "sample_batch.json").write_text(
            json.dumps(result.batch.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _write_json(iteration_dir / "sampling_plan.json", self.sampling_plans.get(iteration, {}))
        validation_batch = getattr(extraction_stage, "validation_batch", None)
        if validation_batch is not None:
            _write_json(iteration_dir / "validation_batch.json", validation_batch)
        candidate_batches = getattr(extraction_stage, "candidate_batches", [])
        _write_jsonl(iteration_dir / "candidate_batches.jsonl", candidate_batches)

        # PR4: 保存 sample traces
        traces = self.sample_set.get_traces_for_iteration("prompt_optimization", iteration)
        traces_data = []
        for trace in traces:
            trace_dict = {
                "sample_id": trace.sample_id,
                "phase": trace.phase,
                "iteration": trace.iteration,
                "selected": trace.selected,
            }
            for attr in ["base_extraction_result_id", "base_extraction_status", "reflection_result_id",
                         "reflection_success", "generated_patch_ids", "generated_analysis_patch_ids",
                         "transition"]:
                val = getattr(trace, attr, None)
                if val is not None:
                    trace_dict[attr] = list(val) if isinstance(val, list) else val
            traces_data.append(trace_dict)
        with open(iteration_dir / "sample_traces.jsonl", "w", encoding="utf-8") as f:
            for t in traces_data:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")

        # PR4: 保存 sample state before/after
        def _serialize_state(state):
            """序列化 SampleState。"""
            if hasattr(state, "to_dict"):
                return state.to_dict()
            return {k: v for k, v in vars(state).items()} if hasattr(state, "__dict__") else str(state)

        if sample_states_before is not None:
            before_data = {sid: _serialize_state(s) for sid, s in sample_states_before.items()}
            _write_json(iteration_dir / "sample_state_before.json", before_data)

        after_data = {sid: _serialize_state(s) for sid, s in self.sample_set.states.items()}
        _write_json(iteration_dir / "sample_state_after.json", after_data)

        # PR4: 保存 batch_size_controller before/after
        if batch_size_before is not None:
            _write_json(iteration_dir / "batch_size_controller_before.json", batch_size_before)
        _write_json(iteration_dir / "batch_size_controller_after.json", self.batch_size_controller)

        # 保存 extraction metrics
        _write_json(iteration_dir / "extraction_metrics.json", result.extraction_metrics)

        # 保存 analysis metrics
        _write_json(iteration_dir / "analysis_metrics.json", result.analysis_metrics)

        # 保存 batch size controller state
        _write_json(iteration_dir / "batch_size_controller.json", self.batch_size_controller)

        # --- Extraction artifacts ---
        extraction_dir = iteration_dir / "extraction"
        extraction_dir.mkdir(parents=True, exist_ok=True)

        _write_jsonl(extraction_dir / "base_results.jsonl", extraction_stage.base_extraction_results)
        _write_jsonl(extraction_dir / "base_eval.jsonl", extraction_stage.base_eval_records)
        _write_jsonl(extraction_dir / "analysis_results.jsonl", extraction_stage.analysis_results)
        _write_jsonl(extraction_dir / "semantic_patch_drafts.jsonl", getattr(extraction_stage, "semantic_patch_drafts", []))
        _write_jsonl(extraction_dir / "translated_patches.jsonl", getattr(extraction_stage, "translated_patches", []))
        _write_jsonl(extraction_dir / "model_output_repairs.jsonl", getattr(extraction_stage, "model_output_repairs", []))
        _write_jsonl(extraction_dir / "draft_patches.jsonl", extraction_stage.draft_patches)
        _write_jsonl(extraction_dir / "validated_patches.jsonl", getattr(extraction_stage, "validated_patches", []))
        _write_jsonl(extraction_dir / "rejected_patches.jsonl", getattr(extraction_stage, "rejected_patches", []))
        _annotate_merge_report(extraction_stage.initial_merge_report)
        _annotate_merge_report(extraction_stage.final_merge_report)

        if extraction_stage.initial_merge_report is not None:
            _write_json(extraction_dir / "initial_merge_report.json", extraction_stage.initial_merge_report)
        if getattr(extraction_stage, "patched_prompt", None) is not None:
            _write_json(extraction_dir / "patched_prompt.json", extraction_stage.patched_prompt)
        if getattr(extraction_stage, "patch_apply_report", None) is not None:
            _write_json(extraction_dir / "patch_apply_report.json", extraction_stage.patch_apply_report)
        _write_jsonl(extraction_dir / "patched_results.jsonl", extraction_stage.patched_extraction_results)
        _write_jsonl(extraction_dir / "patched_eval.jsonl", getattr(extraction_stage, "patched_eval_records", []))
        if getattr(extraction_stage, "accepted_prompt", None) is not None:
            _write_json(extraction_dir / "final_prompt.json", extraction_stage.accepted_prompt)
        _write_jsonl(extraction_dir / "final_results.jsonl", extraction_stage.final_extraction_results)
        _write_jsonl(extraction_dir / "final_eval.jsonl", getattr(extraction_stage, "final_eval_records", []))
        _write_json(extraction_dir / "metrics.json", extraction_stage.metrics)

        # PR3: Extraction 阶段新增 artifact
        if getattr(extraction_stage, "transition_report", None) is not None:
            _write_json(extraction_dir / "transition_report.json", extraction_stage.transition_report)
        extraction_candidate_validation_report = getattr(extraction_stage, "candidate_validation_report", None)
        if extraction_candidate_validation_report is not None:
            _write_json(extraction_dir / "candidate_validation_report.json", extraction_candidate_validation_report)
            _write_jsonl(
                extraction_dir / "candidate_patch_sets.jsonl",
                extraction_candidate_validation_report.candidates,
            )
        _write_jsonl(extraction_dir / "ineffective_patches.jsonl", getattr(extraction_stage, "ineffective_patches", []))
        if getattr(extraction_stage, "toxicity_report", None) is not None:
            _write_json(extraction_dir / "toxicity_report.json", extraction_stage.toxicity_report)
        _write_jsonl(extraction_dir / "safe_patches.jsonl", getattr(extraction_stage, "safe_patches", []))
        _write_jsonl(extraction_dir / "toxic_patches.jsonl", getattr(extraction_stage, "toxic_patches", []))
        if getattr(extraction_stage, "final_merge_report", None) is not None:
            _write_json(extraction_dir / "final_merge_report.json", extraction_stage.final_merge_report)
        _write_jsonl(extraction_dir / "final_merged_patches.jsonl", getattr(extraction_stage, "final_merged_patches", []))
        _write_jsonl(extraction_dir / "success_memory_items.jsonl", _success_memory_items(extraction_stage.analysis_results, "extraction"))
        _write_jsonl(extraction_dir / "patch_lifecycle.jsonl", _patch_lifecycle(extraction_stage, "extraction"))
        extraction_toxicity_report = getattr(extraction_stage, "toxicity_report", None)
        if extraction_toxicity_report is not None:
            _write_jsonl(
                extraction_dir / "patch_test_records.jsonl",
                extraction_toxicity_report.patch_test_records,
            )

        # PR4: Compression report
        if getattr(extraction_stage, "compression_report", None) is not None:
            _write_json(extraction_dir / "compression_report.json", extraction_stage.compression_report)

        # --- Analysis artifacts ---
        analysis_dir = iteration_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        _write_json(analysis_dir / "base_metrics.json", analysis_stage.metrics)
        _write_jsonl(analysis_dir / "reflection_results.jsonl", analysis_stage.reflection_results)
        _write_jsonl(analysis_dir / "semantic_patch_drafts.jsonl", getattr(analysis_stage, "semantic_patch_drafts", []))
        _write_jsonl(analysis_dir / "translated_patches.jsonl", getattr(analysis_stage, "translated_patches", []))
        _write_jsonl(analysis_dir / "model_output_repairs.jsonl", getattr(analysis_stage, "model_output_repairs", []))
        _write_jsonl(analysis_dir / "draft_patches.jsonl", analysis_stage.draft_patches)
        _write_jsonl(analysis_dir / "validated_patches.jsonl", getattr(analysis_stage, "validated_patches", []))
        _write_jsonl(analysis_dir / "rejected_patches.jsonl", getattr(analysis_stage, "rejected_patches", []))
        _annotate_merge_report(analysis_stage.initial_merge_report)
        _annotate_merge_report(analysis_stage.final_merge_report)

        if analysis_stage.initial_merge_report is not None:
            _write_json(analysis_dir / "initial_merge_report.json", analysis_stage.initial_merge_report)
        if getattr(analysis_stage, "patched_prompt", None) is not None:
            _write_json(analysis_dir / "patched_analysis_prompt.json", analysis_stage.patched_prompt)
        if getattr(analysis_stage, "patch_apply_report", None) is not None:
            _write_json(analysis_dir / "patch_apply_report.json", analysis_stage.patch_apply_report)
        _write_jsonl(analysis_dir / "patched_analysis_results.jsonl", analysis_stage.patched_analysis_results)
        if getattr(analysis_stage, "accepted_prompt", None) is not None:
            _write_json(analysis_dir / "final_analysis_prompt.json", analysis_stage.accepted_prompt)
        _write_jsonl(analysis_dir / "final_analysis_results.jsonl", analysis_stage.final_analysis_results)
        _write_json(analysis_dir / "metrics.json", analysis_stage.metrics)

        # PR3: Analysis 阶段新增 artifact
        if getattr(analysis_stage, "transition_report", None) is not None:
            _write_json(analysis_dir / "transition_report.json", analysis_stage.transition_report)
        analysis_candidate_validation_report = getattr(analysis_stage, "candidate_validation_report", None)
        if analysis_candidate_validation_report is not None:
            _write_json(analysis_dir / "candidate_validation_report.json", analysis_candidate_validation_report)
            _write_jsonl(
                analysis_dir / "candidate_patch_sets.jsonl",
                analysis_candidate_validation_report.candidates,
            )
        _write_jsonl(analysis_dir / "ineffective_patches.jsonl", getattr(analysis_stage, "ineffective_patches", []))
        if getattr(analysis_stage, "toxicity_report", None) is not None:
            _write_json(analysis_dir / "toxicity_report.json", analysis_stage.toxicity_report)
        _write_jsonl(analysis_dir / "safe_patches.jsonl", getattr(analysis_stage, "safe_patches", []))
        _write_jsonl(analysis_dir / "toxic_patches.jsonl", getattr(analysis_stage, "toxic_patches", []))
        if getattr(analysis_stage, "final_merge_report", None) is not None:
            _write_json(analysis_dir / "final_merge_report.json", analysis_stage.final_merge_report)
        _write_jsonl(analysis_dir / "final_merged_patches.jsonl", getattr(analysis_stage, "final_merged_patches", []))
        _write_jsonl(analysis_dir / "success_memory_items.jsonl", _success_memory_items(analysis_stage.base_analysis_results, "analysis"))
        _write_jsonl(analysis_dir / "patch_lifecycle.jsonl", _patch_lifecycle(analysis_stage, "analysis"))
        analysis_toxicity_report = getattr(analysis_stage, "toxicity_report", None)
        if analysis_toxicity_report is not None:
            _write_jsonl(
                analysis_dir / "patch_test_records.jsonl",
                analysis_toxicity_report.patch_test_records,
            )

        # PR4: Compression report
        if getattr(analysis_stage, "compression_report", None) is not None:
            _write_json(analysis_dir / "compression_report.json", analysis_stage.compression_report)
