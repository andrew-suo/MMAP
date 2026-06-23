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

from .analysis_prompt_optimization_stage import AnalysisMetrics
from .config import RefactoredConfig
from .dataset_loader import DatasetLoader
from .executors import create_executors
from .extraction_prompt_optimization_stage import ExtractionMetrics
from .fewshot_optimization_phase import FewshotMetrics, FewshotOptimizationPhase
from .prompt_optimization_phase import PromptOptimizationPhase
from .prompt_structuring_phase import PromptStructuringPhase
from .sample import SampleSet
from .structured_prompt import StructuredPrompt

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
class RunSummary:
    """运行总结。"""
    id: str
    status: str = "running"
    prompt_structuring_completed: bool = False
    prompt_optimization_rounds: int = 0
    fewshot_optimization_rounds: int = 0
    final_extraction_prompt_id: str | None = None
    final_analysis_prompt_id: str | None = None
    final_fewshot_example_count: int = 0
    total_extraction_accepted_patches: int = 0
    total_analysis_accepted_patches: int = 0
    extraction_accuracy_delta: float | None = None
    analysis_accuracy_delta: float | None = None
    fewshot_accuracy_delta: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "status": self.status,
            "prompt_structuring_completed": self.prompt_structuring_completed,
            "prompt_optimization_rounds": self.prompt_optimization_rounds,
            "fewshot_optimization_rounds": self.fewshot_optimization_rounds,
            "final_extraction_prompt_id": self.final_extraction_prompt_id,
            "final_analysis_prompt_id": self.final_analysis_prompt_id,
            "final_fewshot_example_count": self.final_fewshot_example_count,
            "total_extraction_accepted_patches": self.total_extraction_accepted_patches,
            "total_analysis_accepted_patches": self.total_analysis_accepted_patches,
            "extraction_accuracy_delta": self.extraction_accuracy_delta,
            "analysis_accuracy_delta": self.analysis_accuracy_delta,
            "fewshot_accuracy_delta": self.fewshot_accuracy_delta,
            "notes": list(self.notes),
        }


class MMAPRunner:
    """重构后的 MMAP 主运行器。"""

    def __init__(
        self,
        config: RefactoredConfig,
        extraction_prompt_path: str | Path,
        analysis_prompt_path: str | Path,
    ):
        self.config = config
        self.extraction_prompt_path = Path(extraction_prompt_path)
        self.analysis_prompt_path = Path(analysis_prompt_path)

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

        # 构建 executor 字典（根据 config.models 决定使用真实实现或 mock）
        self.executors = self._build_executors()

    def _build_executors(self) -> dict[str, Any]:
        """根据配置构建 executor 字典。"""
        return create_executors(self.config.to_dict())

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
        self.run_summary.prompt_structuring_completed = True
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

        # 更新 Run Summary
        self.run_summary.prompt_optimization_rounds = len(results)
        self.run_summary.final_extraction_prompt_id = self.structured_extraction_prompt.id
        self.run_summary.final_analysis_prompt_id = self.structured_analysis_prompt.id

        # 统计 patches
        for result in results:
            self.run_summary.total_extraction_accepted_patches += result.extraction_metrics.accepted_patch_count
            self.run_summary.total_analysis_accepted_patches += result.analysis_metrics.accepted_patch_count

        # 计算准确率变化
        if results:
            first_result = results[0]
            last_result = results[-1]

            if first_result.extraction_metrics.base_accuracy is not None and last_result.extraction_metrics.final_accuracy is not None:
                self.run_summary.extraction_accuracy_delta = last_result.extraction_metrics.final_accuracy - first_result.extraction_metrics.base_accuracy

            if first_result.analysis_metrics.base_accuracy is not None and last_result.analysis_metrics.final_accuracy is not None:
                self.run_summary.analysis_accuracy_delta = last_result.analysis_metrics.final_accuracy - first_result.analysis_metrics.base_accuracy

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

        # 更新 Run Summary
        self.run_summary.fewshot_optimization_rounds = len(results)
        self.run_summary.final_fewshot_example_count = len(phase.fewshot_examples)

        # 计算准确率变化
        if results:
            first_result = results[0]
            last_result = results[-1]

            if first_result.metrics.base_accuracy is not None and last_result.metrics.final_accuracy is not None:
                self.run_summary.fewshot_accuracy_delta = last_result.metrics.final_accuracy - first_result.metrics.base_accuracy

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