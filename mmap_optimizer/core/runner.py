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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.artifacts import write_json_artifact, write_jsonl_artifact
from ..stages.analysis_prompt_optimization import AnalysisMetrics
from ..stages.batch_size_controller import BatchSizeController
from ..core.checkpoint import CheckpointStore, RunCheckpoint
from ..core.config import RefactoredConfig
from ..core.logging import configure_run_logging, get_logger, log_stage
from ..core.progress import ProgressReporter
from ..data.dataset_loader import DatasetLoader
from ..executors import create_executors
from ..stages.extraction_prompt_optimization import ExtractionMetrics
from ..phases.fewshot_optimization import FewshotExample, FewshotMetrics, FewshotOptimizationPhase
from ..phases.prompt_optimization import PromptOptimizationPhase
from ..phases.prompt_structuring import PromptStructuringPhase
from ..data.sample import SampleSet, SampleState, SampleTrace
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunPlanStep":
        return cls(
            id=data.get("id", ""),
            phase=data.get("phase", ""),
            iteration=data.get("iteration"),
            status=data.get("status", "pending"),
            notes=list(data.get("notes", [])),
        )


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunPlan":
        return cls(
            id=data.get("id", "run_plan"),
            steps=[RunPlanStep.from_dict(step) for step in data.get("steps", [])],
            current_step_index=int(data.get("current_step_index", 0)),
        )

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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunSummary":
        summary = cls(id=data.get("id", "run_summary"))
        summary.status = data.get("status", summary.status)
        summary.start_time = data.get("start_time")
        summary.end_time = data.get("end_time")
        summary.duration_seconds = data.get("duration_seconds")
        summary.prompt_structuring_status = data.get("prompt_structuring_status", "pending")
        for target, source in (
            (summary.prompt_optimization, data.get("prompt_optimization", {})),
            (summary.analysis_prompt, data.get("analysis_prompt", {})),
            (summary.fewshot_optimization, data.get("fewshot_optimization", {})),
        ):
            for key, value in source.items():
                if hasattr(target, key):
                    setattr(target, key, value)
        summary.final_extraction_prompt_id = data.get("final_extraction_prompt_id")
        summary.final_analysis_prompt_id = data.get("final_analysis_prompt_id")
        summary.final_fewshot_example_count = data.get("final_fewshot_example_count", 0)
        summary.notes = list(data.get("notes", []))
        return summary


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
        self.log_path = configure_run_logging(
            self.output_dir,
            level=config.run.log_level,
        )
        self.logger = get_logger(__name__)
        self.progress = ProgressReporter(enabled=config.run.progress_enabled)

        # 创建 Run Plan
        self.run_plan = self._create_run_plan()

        # 创建 Run Summary
        self.run_summary = RunSummary(id="run_summary")
        self.checkpoint_store = CheckpointStore(self.output_dir)
        self.checkpoint = RunCheckpoint()

        # 状态
        self.sample_set: SampleSet | None = None
        self.structured_extraction_prompt: StructuredPrompt | None = None
        self.structured_analysis_prompt: StructuredPrompt | None = None

        # PR4: Mock 边界收敛
        # use_mock 优先取显式参数，其次取 config.run.use_mock，默认 None 表示自动判断
        self.use_mock = use_mock if use_mock is not None else config.run.use_mock

        # 构建 executor 字典（根据 config.models 决定使用真实实现或 mock）
        self.executors = self._build_executors()
        self._attach_progress_reporter()

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

    def _attach_progress_reporter(self) -> None:
        for executor in self.executors.values():
            if hasattr(executor, "__dict__"):
                setattr(executor, "progress_reporter", self.progress)

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

    def run(self, resume: bool = False) -> RunSummary:
        """执行完整的 MMAP 运行。"""
        import time
        from datetime import datetime, timezone

        # PR4: 记录开始时间
        start_ts = time.time()
        self.run_summary.start_time = datetime.now(timezone.utc).isoformat()
        log_stage(
            self.logger,
            "run_start",
            "运行开始",
            output_dir=self.output_dir,
            resume=resume,
            log_path=self.log_path,
        )

        if resume and self.checkpoint_store.exists():
            self._restore_from_checkpoint()
            if self.checkpoint.run_status == "completed":
                self.run_summary.status = "completed"
                return self.run_summary
        else:
            # 保存初始配置和 Run Plan
            self._save_initial_artifacts()
            self._save_checkpoint(
                current_phase="prompt_structuring",
                current_step_id="prompt_structuring",
                event="run_started",
            )

        # Phase 1: Prompt Structuring
        if self.run_plan.current_step_index == 0:
            self.progress.phase_start("Phase 1: Prompt Structuring")
            self._run_prompt_structuring()
            self.progress.phase_done("Phase 1: Prompt Structuring")
        elif self.sample_set is None:
            self._load_sample_set()

        # Phase 2: Prompt Optimization
        prompt_start = self._next_iteration_for_phase("prompt_optimization")
        if self.config.prompt_optimization.enabled and prompt_start <= self.config.prompt_optimization.rounds:
            self.progress.phase_start("Phase 2: Prompt Optimization")
            self._run_prompt_optimization(start_iteration=prompt_start)
            po_summary = self.run_summary.prompt_optimization
            metrics: list[str] = []
            if po_summary.final_accuracy_last is not None:
                metrics.append(f"Extraction 准确率: {po_summary.final_accuracy_last:.2%}")
            if self.run_summary.analysis_prompt.final_accuracy_last is not None:
                metrics.append(f"Analysis 准确率: {self.run_summary.analysis_prompt.final_accuracy_last:.2%}")
            self.progress.phase_done(
                "Phase 2: Prompt Optimization",
                ", ".join(metrics) if metrics else None,
            )

        # Phase 3: Few-shot Optimization
        fewshot_start = self._next_iteration_for_phase("fewshot_optimization")
        if self.config.fewshot_optimization.enabled and fewshot_start <= self.config.fewshot_optimization.rounds:
            self.progress.phase_start("Phase 3: Few-shot Optimization")
            self._run_fewshot_optimization(start_iteration=fewshot_start)
            fo_summary = self.run_summary.fewshot_optimization
            fewshot_metrics: str | None = None
            if fo_summary.final_accuracy_last is not None:
                fewshot_metrics = f"Few-shot 准确率: {fo_summary.final_accuracy_last:.2%}"
            self.progress.phase_done("Phase 3: Few-shot Optimization", fewshot_metrics)

        # 完成
        end_ts = time.time()
        self.run_summary.end_time = datetime.now(timezone.utc).isoformat()
        self.run_summary.duration_seconds = round(end_ts - start_ts, 3)
        self.run_summary.status = "completed"
        self._save_final_artifacts()
        self._save_checkpoint(run_status="completed", event="run_completed")
        log_stage(
            self.logger,
            "run_completed",
            "运行完成",
            duration_seconds=self.run_summary.duration_seconds,
            status=self.run_summary.status,
        )

        return self.run_summary

    def _save_initial_artifacts(self) -> None:
        """保存初始 artifacts。"""
        import json

        # 保存配置
        config_data = self.config.to_dict()
        config_json = json.dumps(config_data, indent=2, ensure_ascii=False)
        if yaml is not None:
            (self.output_dir / "run_config.yaml").write_text(
                yaml.dump(self.config.to_dict(), allow_unicode=True),
                encoding="utf-8",
            )
        else:
            (self.output_dir / "run_config.yaml").write_text(
                config_json,
                encoding="utf-8",
            )
        write_json_artifact(self.output_dir / "run_config.json", config_data)

        # 保存 Run Plan
        write_json_artifact(self.output_dir / "run_plan.json", self.run_plan)

        # PR4: 确保 Run 级 JSONL 文件存在（即使为空），保证 artifact 结构完整
        for name in ("prompt_versions.jsonl", "patch_apply_reports.jsonl", "model_call_failures.jsonl"):
            f = self.output_dir / name
            if not f.exists():
                f.write_text("", encoding="utf-8")

    def _run_prompt_structuring(self) -> None:
        """执行 Prompt Structuring Phase。"""
        step = self.run_plan.get_current_step()
        if step is None:
            return
        log_stage(self.logger, "prompt_structuring_start", step_id=step.id)

        step.status = "running"
        self._save_run_plan()
        self._save_checkpoint(
            current_phase="prompt_structuring",
            current_step_id=step.id,
            current_stage="running",
            event="prompt_structuring_started",
        )

        # 获取 optimizer_model_client（用于结构质量较差时进行标准化）
        # 标准化属于优化任务，应使用 optimizer 模型而非 extraction 模型
        model_client = self.executors.get("optimizer_model_client") or self.executors.get("model_client")

        # 创建 Prompt Structuring Phase
        phase = PromptStructuringPhase(
            self.config.prompt_structuring,
            model_client=model_client,
            model_config=self.executors.get("optimizer_model_config") or self.executors.get("extraction_model_config"),
        )

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
        write_json_artifact(self.output_dir / "structured_extraction_prompt.json", self.structured_extraction_prompt)
        write_json_artifact(self.output_dir / "structured_analysis_prompt.json", self.structured_analysis_prompt)

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
        self._save_current_prompts()
        self._save_sample_traces()
        current_step = self.run_plan.get_current_step()
        self._save_checkpoint(
            current_phase="prompt_optimization",
            current_step_id=current_step.id if current_step else None,
            current_stage="completed",
            event="prompt_structuring_completed",
        )
        log_stage(
            self.logger,
            "prompt_structuring_done",
            extraction_sections=len(self.structured_extraction_prompt.sections),
            analysis_sections=len(self.structured_analysis_prompt.sections),
            issues=len(extraction_issues) + len(analysis_issues),
        )

    def _run_prompt_optimization(self, start_iteration: int = 1) -> None:
        """执行 Prompt Optimization Phase。"""
        if self.structured_extraction_prompt is None or self.structured_analysis_prompt is None:
            return
        if self.sample_set is None:
            return
        log_stage(
            self.logger,
            "prompt_optimization_start",
            start_iteration=start_iteration,
            rounds=self.config.prompt_optimization.rounds,
            samples=len(self.sample_set.specs),
        )

        # 创建 Prompt Optimization Phase
        phase = PromptOptimizationPhase(
            config=self.config.prompt_optimization,
            extraction_prompt=self.structured_extraction_prompt,
            analysis_prompt=self.structured_analysis_prompt,
            sample_set=self.sample_set,
            output_dir=self.output_dir,
            seed=self.config.run.seed,
            executors=self.executors,
            checkpoint_callback=self._on_prompt_iteration_completed,
            progress_reporter=self.progress,
        )
        self._restore_batch_size_controller(phase, start_iteration)

        # 执行
        results = phase.run(start_iteration=start_iteration)

        # 更新状态
        self.structured_extraction_prompt = phase.extraction_prompt
        self.structured_analysis_prompt = phase.analysis_prompt

        # PR4: 更新 Run Summary 嵌套对象
        po_summary = self.run_summary.prompt_optimization
        ap_summary = self.run_summary.analysis_prompt

        self.run_summary.final_extraction_prompt_id = self.structured_extraction_prompt.id
        self.run_summary.final_analysis_prompt_id = self.structured_analysis_prompt.id

        for result in results:
            extraction_stage = next(
                (
                    stage for stage in getattr(phase, "extraction_stages", [])
                    if getattr(stage, "iteration", None) == result.iteration
                ),
                None,
            )
            analysis_stage = next(
                (
                    stage for stage in getattr(phase, "analysis_stages", [])
                    if getattr(stage, "iteration", None) == result.iteration
                ),
                None,
            )
            self._accumulate_prompt_iteration_summary(
                po_summary,
                ap_summary,
                result,
                extraction_stage,
                analysis_stage,
            )

        po_summary.batch_size_history = list(phase.batch_size_controller.get_history())

        # 更新 Run Plan
        for result in results:
            step_index = result.iteration  # prompt_structuring 是第 0 步
            if step_index < len(self.run_plan.steps):
                step = self.run_plan.steps[step_index]
                step.status = "completed"
                if result.rollback:
                    step.notes.append("rollback")
                if result.no_progress:
                    step.notes.append("no_progress")

        self.run_plan.current_step_index = max(
            self.run_plan.current_step_index,
            1 + self.config.prompt_optimization.rounds,
        )
        self._save_run_plan()

        # 保存样本状态
        self._save_sample_states()
        self._save_sample_traces()
        self._save_current_prompts()
        log_stage(
            self.logger,
            "prompt_optimization_done",
            iterations=len(results),
            extraction_accuracy=po_summary.final_accuracy_last,
            analysis_accuracy=ap_summary.final_accuracy_last,
        )

    def _run_fewshot_optimization(self, start_iteration: int = 1) -> None:
        """执行 Few-shot Optimization Phase。"""
        if self.structured_extraction_prompt is None:
            return
        if self.sample_set is None:
            return
        log_stage(
            self.logger,
            "fewshot_optimization_start",
            start_iteration=start_iteration,
            rounds=self.config.fewshot_optimization.rounds,
            samples=len(self.sample_set.specs),
        )

        # 创建 Few-shot Optimization Phase
        phase = FewshotOptimizationPhase(
            config=self.config.fewshot_optimization,
            extraction_prompt=self.structured_extraction_prompt,
            sample_set=self.sample_set,
            output_dir=self.output_dir,
            seed=self.config.run.seed,
            initial_fewshot_examples=self._load_fewshot_examples(),
            fewshot_executor=self.executors.get("fewshot"),
            checkpoint_callback=self._on_fewshot_iteration_completed,
            progress_reporter=self.progress,
        )

        # 执行
        results = phase.run(start_iteration=start_iteration)

        # PR4: 更新 Run Summary 嵌套对象
        fo_summary = self.run_summary.fewshot_optimization
        self.run_summary.final_fewshot_example_count = len(phase.fewshot_examples)
        fo_summary.selected_example_ids = [e.id for e in phase.fewshot_examples]

        if results:
            for result in results:
                self._accumulate_fewshot_iteration_summary(fo_summary, result)

        # 更新 Run Plan
        prompt_opt_steps = self.config.prompt_optimization.rounds
        for result in results:
            step_index = prompt_opt_steps + result.iteration
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
        fewshot_file = self.output_dir / "final_fewshot_examples.jsonl"
        write_jsonl_artifact(fewshot_file, phase.fewshot_examples)
        log_stage(
            self.logger,
            "fewshot_optimization_done",
            iterations=len(results),
            final_accuracy=fo_summary.final_accuracy_last,
            selected_examples=len(phase.fewshot_examples),
        )

    def _accumulate_prompt_iteration_summary(
        self,
        po_summary: PromptOptimizationSummary,
        ap_summary: AnalysisPromptSummary,
        result: Any,
        extraction_stage: Any | None = None,
        analysis_stage: Any | None = None,
    ) -> None:
        em = result.extraction_metrics
        am = result.analysis_metrics

        po_summary.iterations = max(po_summary.iterations, result.iteration)
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

        if em.compression_accepted:
            po_summary.compression_accepted_count += 1
        if am.compression_accepted:
            ap_summary.compression_accepted_count += 1

        extraction_cr = getattr(extraction_stage, "compression_report", None)
        if extraction_cr is not None and getattr(extraction_cr, "triggered", False):
            po_summary.compression_triggered_count += 1
        analysis_cr = getattr(analysis_stage, "compression_report", None)
        if analysis_cr is not None and getattr(analysis_cr, "triggered", False):
            ap_summary.compression_triggered_count += 1

        if po_summary.base_accuracy_first is None and em.base_accuracy is not None:
            po_summary.base_accuracy_first = em.base_accuracy
        if ap_summary.base_accuracy_first is None and am.base_accuracy is not None:
            ap_summary.base_accuracy_first = am.base_accuracy
        if em.final_accuracy is not None:
            po_summary.final_accuracy_last = em.final_accuracy
            if po_summary.best_accuracy is None or em.final_accuracy > po_summary.best_accuracy:
                po_summary.best_accuracy = em.final_accuracy
        if am.final_accuracy is not None:
            ap_summary.final_accuracy_last = am.final_accuracy

    def _accumulate_fewshot_iteration_summary(
        self,
        fo_summary: FewshotOptimizationSummary,
        result: Any,
    ) -> None:
        fo_summary.iterations = max(fo_summary.iterations, result.iteration)
        if fo_summary.base_accuracy_first is None and result.metrics.base_accuracy is not None:
            fo_summary.base_accuracy_first = result.metrics.base_accuracy
        if result.metrics.final_accuracy is not None:
            fo_summary.final_accuracy_last = result.metrics.final_accuracy
        if result.metrics.accepted:
            fo_summary.accepted = True

    def _save_run_plan(self) -> None:
        """保存 Run Plan。"""
        import json
        write_json_artifact(self.output_dir / "run_plan.json", self.run_plan)

    def _save_sample_states(self) -> None:
        """保存样本状态。"""
        if self.sample_set is None:
            return

        states_dict = {
            sample_id: state.to_dict()
            for sample_id, state in self.sample_set.states.items()
        }

        write_json_artifact(self.output_dir / "sample_states.json", states_dict)

    def _save_sample_traces(self) -> None:
        if self.sample_set is None:
            return
        traces_file = self.output_dir / "sample_traces.jsonl"
        write_jsonl_artifact(traces_file, self.sample_set.traces)

    def _save_current_prompts(self) -> None:
        if self.structured_extraction_prompt is not None:
            write_json_artifact(self.output_dir / "current_extraction_prompt.json", self.structured_extraction_prompt)
        if self.structured_analysis_prompt is not None:
            write_json_artifact(self.output_dir / "current_analysis_prompt.json", self.structured_analysis_prompt)

    def _save_checkpoint(
        self,
        *,
        run_status: str = "running",
        current_phase: str | None = None,
        current_step_id: str | None = None,
        current_iteration: int | None = None,
        current_stage: str | None = None,
        last_error: str | None = None,
        event: str | None = None,
    ) -> None:
        completed_steps = [
            step.id for step in self.run_plan.steps if step.status == "completed"
        ]
        self.checkpoint.run_status = run_status
        self.checkpoint.current_phase = current_phase or self.checkpoint.current_phase
        self.checkpoint.current_step_id = current_step_id or self.checkpoint.current_step_id
        self.checkpoint.current_iteration = current_iteration
        self.checkpoint.current_stage = current_stage
        self.checkpoint.completed_steps = completed_steps
        self.checkpoint.structured_extraction_prompt_path = "structured_extraction_prompt.json"
        self.checkpoint.structured_analysis_prompt_path = "structured_analysis_prompt.json"
        self.checkpoint.current_extraction_prompt_path = "current_extraction_prompt.json"
        self.checkpoint.current_analysis_prompt_path = "current_analysis_prompt.json"
        self.checkpoint.sample_states_path = "sample_states.json"
        self.checkpoint.sample_traces_path = "sample_traces.jsonl"
        self.checkpoint.batch_size_controller_path = self._latest_batch_controller_path()
        self.checkpoint.fewshot_examples_path = "final_fewshot_examples.jsonl"
        self.checkpoint.last_error = last_error
        self.checkpoint_store.save(self.checkpoint, event=event)

    def _restore_from_checkpoint(self) -> None:
        self.checkpoint = self.checkpoint_store.load()
        run_plan_file = self.output_dir / "run_plan.json"
        if run_plan_file.exists():
            self.run_plan = RunPlan.from_dict(json.loads(run_plan_file.read_text(encoding="utf-8")))
        summary_file = self.output_dir / "run_summary.json"
        if summary_file.exists():
            data = json.loads(summary_file.read_text(encoding="utf-8"))
            self.run_summary = RunSummary.from_dict(data)
        self._load_current_prompts()
        self._load_sample_set()
        self._save_checkpoint(event="run_resumed")

    def _load_current_prompts(self) -> None:
        extraction_candidates = [
            self.output_dir / "current_extraction_prompt.json",
            self.output_dir / "final_extraction_prompt.json",
            self.output_dir / "structured_extraction_prompt.json",
        ]
        analysis_candidates = [
            self.output_dir / "current_analysis_prompt.json",
            self.output_dir / "final_analysis_prompt.json",
            self.output_dir / "structured_analysis_prompt.json",
        ]
        for path in extraction_candidates:
            if path.exists():
                self.structured_extraction_prompt = StructuredPrompt.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                break
        for path in analysis_candidates:
            if path.exists():
                self.structured_analysis_prompt = StructuredPrompt.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
                break

    def _load_sample_set(self) -> None:
        loader = DatasetLoader(
            dataset_path=self.config.dataset.path,
            format=self.config.dataset.format,
            image_root=self.config.dataset.image_root,
        )
        self.sample_set = loader.load_with_ground_truth(self.config.dataset.ground_truth_path)
        states_file = self.output_dir / "sample_states.json"
        if states_file.exists():
            states_data = json.loads(states_file.read_text(encoding="utf-8"))
            self.sample_set.states = {
                sid: SampleState.from_dict({"sample_id": sid, **data})
                for sid, data in states_data.items()
            }
        traces_file = self.output_dir / "sample_traces.jsonl"
        if traces_file.exists():
            traces: list[SampleTrace] = []
            for line in traces_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    traces.append(SampleTrace.from_dict(json.loads(line)))
            self.sample_set.traces = traces

    def _next_iteration_for_phase(self, phase: str) -> int:
        completed = [
            step.iteration or 0
            for step in self.run_plan.steps
            if step.phase == phase and step.status == "completed"
        ]
        return (max(completed) + 1) if completed else 1

    def _latest_batch_controller_path(self) -> str | None:
        candidates = sorted(
            (self.output_dir / "prompt_optimization").glob(
                "iteration_*/batch_size_controller_after.json"
            )
        )
        if not candidates:
            return None
        return str(candidates[-1].relative_to(self.output_dir))

    def _restore_batch_size_controller(
        self,
        phase: PromptOptimizationPhase,
        start_iteration: int,
    ) -> None:
        if start_iteration <= 1:
            return
        previous = start_iteration - 1
        path = (
            self.output_dir
            / "prompt_optimization"
            / f"iteration_{previous}"
            / "batch_size_controller_after.json"
        )
        if path.exists():
            phase.batch_size_controller = BatchSizeController.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )

    def _on_prompt_iteration_completed(
        self,
        iteration: int,
        phase: PromptOptimizationPhase,
    ) -> None:
        self.structured_extraction_prompt = phase.extraction_prompt
        self.structured_analysis_prompt = phase.analysis_prompt
        step_index = iteration
        if step_index < len(self.run_plan.steps):
            self.run_plan.steps[step_index].status = "completed"
            self.run_plan.current_step_index = max(
                self.run_plan.current_step_index,
                step_index + 1,
            )
        self._save_run_plan()
        self._save_sample_states()
        self._save_sample_traces()
        self._save_current_prompts()
        self._save_checkpoint(
            current_phase="prompt_optimization",
            current_step_id=f"prompt_iter_{iteration:03d}",
            current_iteration=iteration,
            current_stage="iteration_completed",
            event="prompt_iteration_completed",
        )

    def _on_fewshot_iteration_completed(
        self,
        iteration: int,
        phase: FewshotOptimizationPhase,
    ) -> None:
        prompt_opt_steps = self.config.prompt_optimization.rounds
        step_index = prompt_opt_steps + iteration
        if step_index < len(self.run_plan.steps):
            self.run_plan.steps[step_index].status = "completed"
            self.run_plan.current_step_index = max(
                self.run_plan.current_step_index,
                step_index + 1,
            )
        self._save_run_plan()
        self._save_sample_states()
        self._save_sample_traces()
        self._save_fewshot_examples(phase.fewshot_examples)
        self._save_checkpoint(
            current_phase="fewshot_optimization",
            current_step_id=f"fewshot_iter_{iteration:03d}",
            current_iteration=iteration,
            current_stage="iteration_completed",
            event="fewshot_iteration_completed",
        )

    def _save_fewshot_examples(self, examples: list[FewshotExample]) -> None:
        fewshot_file = self.output_dir / "final_fewshot_examples.jsonl"
        write_jsonl_artifact(fewshot_file, examples)

    def _load_fewshot_examples(self) -> list[FewshotExample]:
        fewshot_file = self.output_dir / "final_fewshot_examples.jsonl"
        if not fewshot_file.exists():
            return []
        examples: list[FewshotExample] = []
        for line in fewshot_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                examples.append(FewshotExample.from_dict(json.loads(line)))
        return examples

    def _save_final_artifacts(self) -> None:
        """保存最终 artifacts。"""
        import json

        # 保存 Run Summary
        write_json_artifact(self.output_dir / "run_summary.json", self.run_summary)

        # 保存最终的 prompt
        if self.structured_extraction_prompt:
            write_json_artifact(self.output_dir / "final_extraction_prompt.json", self.structured_extraction_prompt)

        if self.structured_analysis_prompt:
            write_json_artifact(self.output_dir / "final_analysis_prompt.json", self.structured_analysis_prompt)
