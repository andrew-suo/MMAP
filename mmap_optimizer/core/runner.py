"""Run Plan 和主运行器。

根据设计文档，运行时根据配置生成明确的 RunPlan：
RunPlan
├── prompt_structuring
├── prompt_iter_001
├── prompt_iter_002
├── prompt_iter_003
├── fewshot_iter_001
└── fewshot_iter_002
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..stages.analysis_prompt_optimization import AnalysisMetrics
from ..core.config import RefactoredConfig
from ..data.dataset_loader import DatasetLoader
from ..executors import create_executors
from ..stages.extraction_prompt_optimization import ExtractionMetrics
from ..phases.fewshot_optimization import FewshotMetrics, FewshotOptimizationPhase
from ..phases.prompt_optimization import PromptOptimizationPhase
from ..phases.prompt_structuring import PromptStructuringPhase
from ..data.sample import SampleSet
from ..prompt.structured_prompt import StructuredPrompt

# YAML 导入检查（在顶部导入，避免 _save_initial_artifacts 使用时未定义）
try:
    import yaml
except Exception:
    yaml = None


@dataclass
class RunPlanStep:
    """Run Plan 的单个步骤。"""
    id: str
    phase: str  # "prompt_structuring", "prompt_optimization", "fewshot_optimization"
    iteration: int | None = None
    status: str = "pending"  # "pending", "running", "completed", "failed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "phase": self.phase,
            "iteration": self.iteration,
            "status": self.status,
            "notes": list(self.notes),
        }


@dataclass
class RunPlan:
    """运行计划。"""
    id: str
    steps: list[RunPlanStep] = field(default_factory=list)
    current_step_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_index": self.current_step_index,
        }

    def get_current_step(self) -> RunPlanStep | None:
        """获取当前步骤。"""
        if self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def advance(self) -> None:
        """推进到下一个步骤。"""
        self.current_step_index += 1


@dataclass
class PromptOptimizationSummary:
    """Prompt Optimization Phase 汇总。"""
    iterations: int = 0
    base_accuracy_first: float | None = None
    final_accuracy_last: float | None = None
    best_accuracy: float | None = None
    total_accepted_patches: int = 0
    total_rejected_patches: int = 0
    total_toxic_patches: int = 0
    total_ineffective_patches: int = 0
    rollback_count: int = 0
    no_progress_count: int = 0
    compression_triggered_count: int = 0
    compression_accepted_count: int = 0
    batch_size_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iterations": self.iterations,
            "base_accuracy_first": self.base_accuracy_first,
            "final_accuracy_last": self.final_accuracy_last,
            "best_accuracy": self.best_accuracy,
            "total_accepted_patches": self.total_accepted_patches,
            "total_rejected_patches": self.total_rejected_patches,
            "total_toxic_patches": self.total_toxic_patches,
            "total_ineffective_patches": self.total_ineffective_patches,
            "rollback_count": self.rollback_count,
            "no_progress_count": self.no_progress_count,
            "compression_triggered_count": self.compression_triggered_count,
            "compression_accepted_count": self.compression_accepted_count,
            "batch_size_history": list(self.batch_size_history),
        }


@dataclass
class AnalysisPromptSummary:
    """Analysis Prompt Optimization 汇总。"""
    base_accuracy_first: float | None = None
    final_accuracy_last: float | None = None
    total_accepted_patches: int = 0
    rollback_count: int = 0
    no_progress_count: int = 0
    compression_triggered_count: int = 0
    compression_accepted_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "base_accuracy_first": self.base_accuracy_first,
            "final_accuracy_last": self.final_accuracy_last,
            "total_accepted_patches": self.total_accepted_patches,
            "rollback_count": self.rollback_count,
            "no_progress_count": self.no_progress_count,
            "compression_triggered_count": self.compression_triggered_count,
            "compression_accepted_count": self.compression_accepted_count,
        }


@dataclass
class FewshotOptimizationSummary:
    """Few-shot Optimization Phase 汇总。"""
    iterations: int = 0
    base_accuracy_first: float | None = None
    final_accuracy_last: float | None = None
    selected_example_ids: list[str] = field(default_factory=list)
    accepted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "iterations": self.iterations,
            "base_accuracy_first": self.base_accuracy_first,
            "final_accuracy_last": self.final_accuracy_last,
            "selected_example_ids": list(self.selected_example_ids),
            "accepted": self.accepted,
        }


@dataclass
class RunSummary:
    """运行总结。

    PR4 扩展：包含时间信息、prompt_structuring_status、以及嵌套的
    prompt_optimization / analysis_prompt / fewshot_optimization 子对象。
    旧的扁平字段保留作为向后兼容（CLI 显示用），新代码应优先使用嵌套对象。
    """
    id: str
    status: str = "running"
    start_time: str | None = None
    end_time: str | None = None
    duration_seconds: float | None = None
    prompt_structuring_status: str = "pending"

    # 嵌套汇总对象（PR4）
    prompt_optimization: PromptOptimizationSummary = field(
        default_factory=PromptOptimizationSummary
    )
    analysis_prompt: AnalysisPromptSummary = field(
        default_factory=AnalysisPromptSummary
    )
    fewshot_optimization: FewshotOptimizationSummary = field(
        default_factory=FewshotOptimizationSummary
    )

    # 最终 prompt / few-shot 顶层信息
    final_extraction_prompt_id: str | None = None
    final_analysis_prompt_id: str | None = None
    final_fewshot_example_count: int = 0
    notes: list[str] = field(default_factory=list)

    # ---- 向后兼容的扁平字段（从嵌套对象派生）----
    @property
    def prompt_structuring_completed(self) -> bool:
        return self.prompt_structuring_status == "completed"

    @property
    def prompt_optimization_rounds(self) -> int:
        return self.prompt_optimization.iterations

    @property
    def fewshot_optimization_rounds(self) -> int:
        return self.fewshot_optimization.iterations

    @property
    def total_extraction_accepted_patches(self) -> int:
        return self.prompt_optimization.total_accepted_patches

    @property
    def total_analysis_accepted_patches(self) -> int:
        return self.analysis_prompt.total_accepted_patches

    @property
    def extraction_accuracy_delta(self) -> float | None:
        po = self.prompt_optimization
        if po.base_accuracy_first is not None and po.final_accuracy_last is not None:
            return po.final_accuracy_last - po.base_accuracy_first
        return None

    @property
    def analysis_accuracy_delta(self) -> float | None:
        ap = self.analysis_prompt
        if ap.base_accuracy_first is not None and ap.final_accuracy_last is not None:
            return ap.final_accuracy_last - ap.base_accuracy_first
        return None

    @property
    def fewshot_accuracy_delta(self) -> float | None:
        fo = self.fewshot_optimization
        if fo.base_accuracy_first is not None and fo.final_accuracy_last is not None:
            return fo.final_accuracy_last - fo.base_accuracy_first
        return None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（v1.4 结构）。"""
        return {
            "id": self.id,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "prompt_structuring_status": self.prompt_structuring_status,
            "prompt_optimization": self.prompt_optimization.to_dict(),
            "analysis_prompt": self.analysis_prompt.to_dict(),
            "fewshot_optimization": self.fewshot_optimization.to_dict(),
            "final_extraction_prompt_id": self.final_extraction_prompt_id,
            "final_analysis_prompt_id": self.final_analysis_prompt_id,
            "final_fewshot_example_count": self.final_fewshot_example_count,
            "notes": list(self.notes),
        }


class MMAPRunner:
    """重构后的 MMAP 主运行器。"""

    def __init__(
        self,
        config: RefactoredConfig,
        extraction_prompt_path: str | Path | None = None,
        analysis_prompt_path: str | Path | None = None,
        use_mock: bool | None = None,
    ):
        self.config = config
        self.extraction_prompt_path = Path(
            extraction_prompt_path or config.prompts.extraction
        )
        self.analysis_prompt_path = Path(
            analysis_prompt_path or config.prompts.analysis
        )

        # 输出目录
        self.output_dir = Path(config.run.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 创建 Run Plan
        self.run_plan = self._create_run_plan()

        # 创建 Run Summary
        self.run_summary = RunSummary(id="run_summary")

        # 状态
        self.sample_set: SampleSet | None = None
        self.structured_extraction_prompt: StructuredPrompt | None = None
        self.structured_analysis_prompt: StructuredPrompt | None = None

        # PR4: Mock 边界收敛
        # use_mock 优先取显式参数，其次取 config.run.use_mock，默认 None 表示自动判断
        self.use_mock = use_mock if use_mock is not None else config.run.use_mock

        # 构建 executor 字典（根据 config.models 决定使用真实实现或 mock）
        self.executors = self._build_executors()

        # PR4: 真实运行模式下校验 model_client 可用
        # 仅当 use_mock 显式为 False 时才强制要求 model_client；
        # use_mock=None（自动）允许在无 model_client 时回退到 mock。
        if self.use_mock is False:
            model_client = self.executors.get("model_client")
            if model_client is None:
                raise RuntimeError(
                    "use_mock=false 但 model_client 不可用。"
                    "请配置有效的 models.* 配置，或显式设置 use_mock=true 以使用 mock 模式。"
                )

    def _build_executors(self) -> dict[str, Any]:
        """根据配置构建 executor 字典。"""
        return create_executors(self.config.to_dict(), use_mock=self.use_mock)

    def _create_run_plan(self) -> RunPlan:
        """创建 Run Plan。"""
        steps: list[RunPlanStep] = []

        # Prompt Structuring Phase
        steps.append(RunPlanStep(
            id="prompt_structuring",
            phase="prompt_structuring",
        ))

        # Prompt Optimization Iterations
        for i in range(1, self.config.prompt_optimization.rounds + 1):
            steps.append(RunPlanStep(
                id=f"prompt_iter_{i:03d}",
                phase="prompt_optimization",
                iteration=i,
            ))

        # Few-shot Optimization Iterations
        for i in range(1, self.config.fewshot_optimization.rounds + 1):
            steps.append(RunPlanStep(
                id=f"fewshot_iter_{i:03d}",
                phase="fewshot_optimization",
                iteration=i,
            ))

        return RunPlan(id="run_plan", steps=steps)

    def run(self) -> RunSummary:
        """执行完整的 MMAP 运行。"""
        import time
        from datetime import datetime, timezone

        # PR4: 记录开始时间
        start_ts = time.time()
        self.run_summary.start_time = datetime.now(timezone.utc).isoformat()

        # 保存初始配置和 Run Plan
        self._save_initial_artifacts()

        # Phase 1: Prompt Structuring
        self._run_prompt_structuring()

        # Phase 2: Prompt Optimization
        if self.config.prompt_optimization.enabled:
            self._run_prompt_optimization()

        # Phase 3: Few-shot Optimization
        if self.config.fewshot_optimization.enabled:
            self._run_fewshot_optimization()

        # 完成
        end_ts = time.time()
        self.run_summary.end_time = datetime.now(timezone.utc).isoformat()
        self.run_summary.duration_seconds = round(end_ts - start_ts, 3)
        self.run_summary.status = "completed"
        self._save_final_artifacts()

        return self.run_summary

    def _save_initial_artifacts(self) -> None:
        """保存初始 artifacts。"""
        import json

        # 保存配置
        config_json = json.dumps(self.config.to_dict(), indent=2, ensure_ascii=False)
        if yaml is not None:
            (self.output_dir / "run_config.yaml").write_text(
                yaml.dump(self.config.to_dict(), allow_unicode=True),
                encoding="utf-8",
            )
        (self.output_dir / "run_config.json").write_text(config_json, encoding="utf-8")

        # 保存 Run Plan
        (self.output_dir / "run_plan.json").write_text(
            json.dumps(self.run_plan.to_dict(), indent=2),
            encoding="utf-8",
        )

        # PR4: 确保 Run 级 JSONL 文件存在（即使为空），保证 artifact 结构完整
        for name in ("prompt_versions.jsonl", "patch_apply_reports.jsonl"):
            f = self.output_dir / name
            if not f.exists():
                f.write_text("", encoding="utf-8")

    def _run_prompt_structuring(self) -> None:
        """执行 Prompt Structuring Phase。"""
        step = self.run_plan.get_current_step()
        if step is None:
            return

        step.status = "running"
        self._save_run_plan()

        # 创建 Prompt Structuring Phase
        phase = PromptStructuringPhase(self.config.prompt_structuring)

        # 执行
        self.structured_extraction_prompt, self.structured_analysis_prompt = phase.run(
            self.extraction_prompt_path,
            self.analysis_prompt_path,
        )

        # 验证
        extraction_issues = phase.validate(self.structured_extraction_prompt)
        analysis_issues = phase.validate(self.structured_analysis_prompt)

        if extraction_issues:
            step.notes.extend([f"Extraction: {issue}" for issue in extraction_issues])
        if analysis_issues:
            step.notes.extend([f"Analysis: {issue}" for issue in analysis_issues])

        # 保存结构化 prompt
        import json
        (self.output_dir / "structured_extraction_prompt.json").write_text(
            json.dumps(self.structured_extraction_prompt.to_dict(), indent=2),
            encoding="utf-8",
        )
        (self.output_dir / "structured_analysis_prompt.json").write_text(
            json.dumps(self.structured_analysis_prompt.to_dict(), indent=2),
            encoding="utf-8",
        )

        # 加载样本
        loader = DatasetLoader(
            dataset_path=self.config.dataset.path,
            format=self.config.dataset.format,
            image_root=self.config.dataset.image_root,
        )
        self.sample_set = loader.load_with_ground_truth(self.config.dataset.ground_truth_path)

        # 保存样本状态
        self._save_sample_states()

        # 完成
        step.status = "completed"
        self.run_summary.prompt_structuring_status = "completed"
        self.run_plan.advance()
        self._save_run_plan()

    def _run_prompt_optimization(self) -> None:
        """执行 Prompt Optimization Phase。"""
        if self.structured_extraction_prompt is None or self.structured_analysis_prompt is None:
            return
        if self.sample_set is None:
            return

        # 创建 Prompt Optimization Phase
        phase = PromptOptimizationPhase(
            config=self.config.prompt_optimization,
            extraction_prompt=self.structured_extraction_prompt,
            analysis_prompt=self.structured_analysis_prompt,
            sample_set=self.sample_set,
            output_dir=self.output_dir,
            seed=self.config.run.seed,
            executors=self.executors,
        )

        # 执行
        results = phase.run()

        # 更新状态
        self.structured_extraction_prompt = phase.extraction_prompt
        self.structured_analysis_prompt = phase.analysis_prompt

        # PR4: 更新 Run Summary 嵌套对象
        po_summary = self.run_summary.prompt_optimization
        ap_summary = self.run_summary.analysis_prompt

        po_summary.iterations = len(results)
        self.run_summary.final_extraction_prompt_id = self.structured_extraction_prompt.id
        self.run_summary.final_analysis_prompt_id = self.structured_analysis_prompt.id

        # 统计 patches / rollback / no_progress / compression / best_accuracy
        best_extraction_acc: float | None = None
        for result in results:
            em = result.extraction_metrics
            am = result.analysis_metrics

            po_summary.total_accepted_patches += em.accepted_patch_count
            po_summary.total_rejected_patches += em.rejected_patch_count
            po_summary.total_toxic_patches += em.toxic_patch_count
            ap_summary.total_accepted_patches += am.accepted_patch_count

            if result.rollback:
                po_summary.rollback_count += 1
            if result.no_progress:
                po_summary.no_progress_count += 1
            if am.no_progress:
                ap_summary.no_progress_count += 1

            # compression 统计（从 stage.compression_report 读取）
            # ExtractionStage 和 AnalysisStage 在 phase.iteration_results 中无直接引用，
            # 通过 metrics.compression_accepted 推断 accepted；triggered 需从 stage 取。
            # 这里通过 phase 暴露的 stage 列表获取（若可用）。
            if em.compression_accepted:
                po_summary.compression_accepted_count += 1
            if am.compression_accepted:
                ap_summary.compression_accepted_count += 1

            if em.final_accuracy is not None:
                if best_extraction_acc is None or em.final_accuracy > best_extraction_acc:
                    best_extraction_acc = em.final_accuracy

        po_summary.best_accuracy = best_extraction_acc

        # 从 phase 获取 compression_triggered_count 和 batch_size_history
        # phase.extraction_stages / phase.analysis_stages 在 _run_iteration 中创建，
        # 这里通过 phase 暴露的属性获取（若无则跳过）
        for stage in getattr(phase, "extraction_stages", []):
            cr = getattr(stage, "compression_report", None)
            if cr is not None and getattr(cr, "triggered", False):
                po_summary.compression_triggered_count += 1
        for stage in getattr(phase, "analysis_stages", []):
            cr = getattr(stage, "compression_report", None)
            if cr is not None and getattr(cr, "triggered", False):
                ap_summary.compression_triggered_count += 1

        po_summary.batch_size_history = list(phase.batch_size_controller.get_history())

        # 计算首末准确率
        if results:
            first_result = results[0]
            last_result = results[-1]

            if first_result.extraction_metrics.base_accuracy is not None:
                po_summary.base_accuracy_first = first_result.extraction_metrics.base_accuracy
            if last_result.extraction_metrics.final_accuracy is not None:
                po_summary.final_accuracy_last = last_result.extraction_metrics.final_accuracy

            if first_result.analysis_metrics.base_accuracy is not None:
                ap_summary.base_accuracy_first = first_result.analysis_metrics.base_accuracy
            if last_result.analysis_metrics.final_accuracy is not None:
                ap_summary.final_accuracy_last = last_result.analysis_metrics.final_accuracy

        # 更新 Run Plan
        for i, result in enumerate(results):
            step_index = i + 1  # prompt_structuring 是第 0 步
            if step_index < len(self.run_plan.steps):
                step = self.run_plan.steps[step_index]
                step.status = "completed"
                if result.rollback:
                    step.notes.append("rollback")
                if result.no_progress:
                    step.notes.append("no_progress")

        self.run_plan.current_step_index = len(results) + 1
        self._save_run_plan()

        # 保存样本状态
        self._save_sample_states()

    def _run_fewshot_optimization(self) -> None:
        """执行 Few-shot Optimization Phase。"""
        if self.structured_extraction_prompt is None:
            return
        if self.sample_set is None:
            return

        # 创建 Few-shot Optimization Phase
        phase = FewshotOptimizationPhase(
            config=self.config.fewshot_optimization,
            extraction_prompt=self.structured_extraction_prompt,
            sample_set=self.sample_set,
            output_dir=self.output_dir,
            seed=self.config.run.seed,
            fewshot_executor=self.executors.get("fewshot"),
        )

        # 执行
        results = phase.run()

        # PR4: 更新 Run Summary 嵌套对象
        fo_summary = self.run_summary.fewshot_optimization
        fo_summary.iterations = len(results)
        self.run_summary.final_fewshot_example_count = len(phase.fewshot_examples)
        fo_summary.selected_example_ids = [e.id for e in phase.fewshot_examples]

        # 计算首末准确率与 accepted
        if results:
            first_result = results[0]
            last_result = results[-1]

            if first_result.metrics.base_accuracy is not None:
                fo_summary.base_accuracy_first = first_result.metrics.base_accuracy
            if last_result.metrics.final_accuracy is not None:
                fo_summary.final_accuracy_last = last_result.metrics.final_accuracy

            # accepted: 任一轮接受即标记为 True
            fo_summary.accepted = any(r.metrics.accepted for r in results)

        # 更新 Run Plan
        prompt_opt_steps = self.config.prompt_optimization.rounds
        for i, result in enumerate(results):
            step_index = 1 + prompt_opt_steps + i  # prompt_structuring(1) + prompt_optimization(N)
            if step_index < len(self.run_plan.steps):
                step = self.run_plan.steps[step_index]
                step.status = "completed"
                if result.metrics.accepted:
                    step.notes.append("accepted")
                else:
                    step.notes.append("rejected")

        self.run_plan.current_step_index = len(self.run_plan.steps)
        self._save_run_plan()

        # 保存样本状态
        self._save_sample_states()

        # PR4: 保存 final_fewshot_examples.jsonl
        import json
        fewshot_file = self.output_dir / "final_fewshot_examples.jsonl"
        with open(fewshot_file, "w", encoding="utf-8") as f:
            for example in phase.fewshot_examples:
                f.write(json.dumps(example.to_dict(), ensure_ascii=False) + "\n")

    def _save_run_plan(self) -> None:
        """保存 Run Plan。"""
        import json
        (self.output_dir / "run_plan.json").write_text(
            json.dumps(self.run_plan.to_dict(), indent=2),
            encoding="utf-8",
        )

    def _save_sample_states(self) -> None:
        """保存样本状态。"""
        if self.sample_set is None:
            return

        import json

        states_dict = {
            sample_id: {
                "sample_id": state.sample_id,
                "selected_count": state.selected_count,
                "selection_ema": state.selection_ema,
                "frequency_score": state.frequency_score,
                "error_count": state.error_count,
                "error_ema": state.error_ema,
                "difficulty_score": state.difficulty_score,
                "last_extraction_status": state.last_extraction_status,
                "last_analysis_status": state.last_analysis_status,
                "historical_fixed_count": state.historical_fixed_count,
                "historical_broken_count": state.historical_broken_count,
            }
            for sample_id, state in self.sample_set.states.items()
        }

        (self.output_dir / "sample_states.json").write_text(
            json.dumps(states_dict, indent=2),
            encoding="utf-8",
        )

    def _save_final_artifacts(self) -> None:
        """保存最终 artifacts。"""
        import json

        # 保存 Run Summary
        (self.output_dir / "run_summary.json").write_text(
            json.dumps(self.run_summary.to_dict(), indent=2),
            encoding="utf-8",
        )

        # 保存最终的 prompt
        if self.structured_extraction_prompt:
            (self.output_dir / "final_extraction_prompt.json").write_text(
                json.dumps(self.structured_extraction_prompt.to_dict(), indent=2),
                encoding="utf-8",
            )

        if self.structured_analysis_prompt:
            (self.output_dir / "final_analysis_prompt.json").write_text(
                json.dumps(self.structured_analysis_prompt.to_dict(), indent=2),
                encoding="utf-8",
            )
