"""重构后的 Sample 三层设计。

根据设计文档，Sample 拆成三层：
- SampleSpec：静态样本事实
- SampleState：跨轮动态状态
- SampleTrace：单轮过程记录
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast


@dataclass
class SampleOutcomeHistoryItem:
    """单个样本的跨轮评估结果历史，用于动态采样。"""
    sample_id: str
    prompt_type: Literal["extraction", "analysis"]
    iteration: int
    status: Literal["pass", "fail", "unknown"] = "unknown"
    transition: str = "unknown"
    selected: bool = True
    patch_decision: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "prompt_type": self.prompt_type,
            "iteration": self.iteration,
            "status": self.status,
            "transition": self.transition,
            "selected": self.selected,
            "patch_decision": self.patch_decision,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleOutcomeHistoryItem":
        status = str(data.get("status", "unknown"))
        if status not in {"pass", "fail", "unknown"}:
            status = "unknown"
        prompt_type = data.get("prompt_type", "extraction")
        if prompt_type not in {"extraction", "analysis"}:
            prompt_type = "extraction"
        return cls(
            sample_id=str(data.get("sample_id", "")),
            prompt_type=cast(Literal["extraction", "analysis"], prompt_type),
            iteration=int(data.get("iteration", 0)),
            status=cast(Literal["pass", "fail", "unknown"], status),
            transition=str(data.get("transition", "unknown")),
            selected=bool(data.get("selected", True)),
            patch_decision=str(data.get("patch_decision", "unknown")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SamplePatchAttempt:
    """一个 sample 触发的一次 patch 尝试事件。"""
    patch_id: str
    prompt_type: Literal["extraction", "analysis"]
    iteration: int
    attempt_id: str = ""
    stage: str = "generated"
    stage_status: str = "generated"
    event_index: int = 0
    target_section_id: str = ""
    operation_type: str = ""
    direction: str = ""
    content: str = ""
    rationale: str = ""
    generation_status: str = "generated"
    validation_status: str = "unknown"
    merge_status: str = "unknown"
    regression_effect: str = "unknown"
    toxicity_status: str = "not_tested"
    tested_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    fixed_sample_ids: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    final_decision: str = "unknown"
    rejection_reason: str | None = None
    evidence_scope: str = "sample"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "patch_id": self.patch_id,
            "prompt_type": self.prompt_type,
            "iteration": self.iteration,
            "stage": self.stage,
            "stage_status": self.stage_status,
            "event_index": self.event_index,
            "target_section_id": self.target_section_id,
            "operation_type": self.operation_type,
            "direction": self.direction,
            "content": self.content,
            "rationale": self.rationale,
            "generation_status": self.generation_status,
            "validation_status": self.validation_status,
            "merge_status": self.merge_status,
            "regression_effect": self.regression_effect,
            "toxicity_status": self.toxicity_status,
            "tested_sample_ids": list(self.tested_sample_ids),
            "broken_sample_ids": list(self.broken_sample_ids),
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "stop_reason": self.stop_reason,
            "final_decision": self.final_decision,
            "rejection_reason": self.rejection_reason,
            "evidence_scope": self.evidence_scope,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SamplePatchAttempt":
        prompt_type = data.get("prompt_type", "extraction")
        if prompt_type not in {"extraction", "analysis"}:
            prompt_type = "extraction"
        attempt_id = str(data.get("attempt_id", "")) or str(data.get("patch_id", ""))
        return cls(
            attempt_id=attempt_id,
            patch_id=str(data.get("patch_id", "")),
            prompt_type=cast(Literal["extraction", "analysis"], prompt_type),
            iteration=int(data.get("iteration", 0)),
            stage=str(data.get("stage", "generated")),
            stage_status=str(data.get("stage_status", data.get("generation_status", "generated"))),
            event_index=int(data.get("event_index", 0)),
            target_section_id=str(data.get("target_section_id", "")),
            operation_type=str(data.get("operation_type", "")),
            direction=str(data.get("direction", "")),
            content=str(data.get("content", "")),
            rationale=str(data.get("rationale", "")),
            generation_status=str(data.get("generation_status", "generated")),
            validation_status=str(data.get("validation_status", "unknown")),
            merge_status=str(data.get("merge_status", "unknown")),
            regression_effect=str(data.get("regression_effect", "unknown")),
            toxicity_status=str(data.get("toxicity_status", "not_tested")),
            tested_sample_ids=[str(sid) for sid in data.get("tested_sample_ids", [])],
            broken_sample_ids=[str(sid) for sid in data.get("broken_sample_ids", [])],
            fixed_sample_ids=[str(sid) for sid in data.get("fixed_sample_ids", [])],
            stop_reason=data.get("stop_reason"),
            final_decision=str(data.get("final_decision", "unknown")),
            rejection_reason=data.get("rejection_reason"),
            evidence_scope=str(data.get("evidence_scope", "sample")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SampleOptimizationTrajectory:
    """一个 sample 在某一轮某个 prompt 类型下的优化轨迹。"""
    sample_id: str
    prompt_type: Literal["extraction", "analysis"]
    iteration: int
    selected: bool = True
    base_status: str = "unknown"
    final_status: str = "unknown"
    base_raw_status: str = "unknown"
    final_raw_status: str = "unknown"
    sample_transition: str = "unknown"
    analysis_summary: dict[str, Any] = field(default_factory=dict)
    reflection_summary: dict[str, Any] = field(default_factory=dict)
    patch_attempts: list[SamplePatchAttempt] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_patch_attempt(self, attempt: SamplePatchAttempt) -> None:
        if not attempt.attempt_id:
            attempt.attempt_id = attempt.patch_id or f"{self.sample_id}:{len(self.patch_attempts) + 1}"
        if attempt.event_index <= 0:
            attempt.event_index = self._next_patch_event_index(attempt.attempt_id)
        self.patch_attempts.append(attempt)

    def latest_patch_attempts(self, limit: int | None = None) -> list[SamplePatchAttempt]:
        latest_by_attempt = self.latest_patch_attempt_map()
        attempts = sorted(
            latest_by_attempt.values(),
            key=lambda item: (item.iteration, item.event_index, item.attempt_id),
        )
        if limit is None:
            return attempts
        return attempts[-limit:]

    def latest_patch_attempt_map(self) -> dict[str, SamplePatchAttempt]:
        latest: dict[str, SamplePatchAttempt] = {}
        for attempt in sorted(
            self.patch_attempts,
            key=lambda item: (item.iteration, item.event_index, item.attempt_id),
        ):
            latest[attempt.attempt_id] = attempt
        return latest

    def patch_attempt_events(self, attempt_id: str) -> list[SamplePatchAttempt]:
        return [
            item for item in sorted(
                self.patch_attempts,
                key=lambda value: (value.iteration, value.event_index, value.attempt_id),
            )
            if item.attempt_id == attempt_id
        ]

    def _next_patch_event_index(self, attempt_id: str) -> int:
        max_index = 0
        for item in self.patch_attempts:
            if item.attempt_id == attempt_id:
                max_index = max(max_index, item.event_index)
        return max_index + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "prompt_type": self.prompt_type,
            "iteration": self.iteration,
            "selected": self.selected,
            "base_status": self.base_status,
            "final_status": self.final_status,
            "base_raw_status": self.base_raw_status,
            "final_raw_status": self.final_raw_status,
            "sample_transition": self.sample_transition,
            "analysis_summary": dict(self.analysis_summary),
            "reflection_summary": dict(self.reflection_summary),
            "patch_attempts": [attempt.to_dict() for attempt in self.patch_attempts],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleOptimizationTrajectory":
        prompt_type = data.get("prompt_type", "extraction")
        if prompt_type not in {"extraction", "analysis"}:
            prompt_type = "extraction"
        return cls(
            sample_id=str(data.get("sample_id", "")),
            prompt_type=cast(Literal["extraction", "analysis"], prompt_type),
            iteration=int(data.get("iteration", 0)),
            selected=bool(data.get("selected", True)),
            base_status=str(data.get("base_status", "unknown")),
            final_status=str(data.get("final_status", "unknown")),
            base_raw_status=str(data.get("base_raw_status", "unknown")),
            final_raw_status=str(data.get("final_raw_status", "unknown")),
            sample_transition=str(data.get("sample_transition", "unknown")),
            analysis_summary=dict(data.get("analysis_summary", {})),
            reflection_summary=dict(data.get("reflection_summary", {})),
            patch_attempts=[
                SamplePatchAttempt.from_dict(item)
                for item in data.get("patch_attempts", [])
                if isinstance(item, dict)
            ],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SampleAsset:
    """样本资产（如图片）。"""
    id: str
    sample_id: str
    type: str = "image"
    uri: str | None = None
    local_path: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sample_id": self.sample_id,
            "type": self.type,
            "uri": self.uri,
            "local_path": self.local_path,
            "mime_type": self.mime_type,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleAsset":
        return cls(
            id=data.get("id", ""),
            sample_id=data.get("sample_id", ""),
            type=data.get("type", "image"),
            uri=data.get("uri"),
            local_path=data.get("local_path"),
            mime_type=data.get("mime_type"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class SampleSpec:
    """静态样本事实，不随优化过程变化。"""
    id: str
    input: dict[str, Any]
    ground_truth: dict[str, Any]
    assets: list[SampleAsset] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input": dict(self.input),
            "ground_truth": dict(self.ground_truth),
            "assets": [asset.to_dict() for asset in self.assets],
            "metadata": dict(self.metadata),
            "tags": list(self.tags),
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleSpec":
        return cls(
            id=data.get("id", ""),
            input=dict(data.get("input", {})),
            ground_truth=dict(data.get("ground_truth", {})),
            assets=[SampleAsset.from_dict(a) for a in data.get("assets", [])],
            metadata=dict(data.get("metadata", {})),
            tags=list(data.get("tags", [])),
            active=bool(data.get("active", True)),
        )


@dataclass
class SampleState:
    """跨轮动态状态，记录样本在整个优化过程中的状态变化。"""
    sample_id: str

    # 抽样频率相关
    selected_count: int = 0
    selection_ema: float = 0.0
    last_selected_iteration: int | None = None
    frequency_score: float = 1.0

    # 困难度相关
    error_count: int = 0
    error_ema: float = 0.0
    difficulty_score: float = 0.0

    # 最近状态
    last_extraction_status: str = "unknown"
    last_analysis_status: str = "unknown"

    # 历史统计
    historical_fixed_count: int = 0
    historical_broken_count: int = 0
    generated_extraction_patch_count: int = 0
    generated_analysis_patch_count: int = 0
    outcome_history: list[SampleOutcomeHistoryItem] = field(default_factory=list)
    optimization_trajectory: list[SampleOptimizationTrajectory] = field(default_factory=list)

    def update_selection(self, selected: bool, iteration: int, alpha: float = 0.3) -> None:
        """更新抽样频率状态。"""
        selected_signal = 1 if selected else 0
        self.selection_ema = alpha * selected_signal + (1 - alpha) * self.selection_ema

        if selected:
            self.selected_count += 1
            self.last_selected_iteration = iteration
            self.frequency_score = 1 / (1 + self.selected_count)

    def update_error(self, has_error: bool, alpha: float = 0.3) -> None:
        """更新困难度状态。"""
        error_signal = 1 if has_error else 0
        self.error_ema = alpha * error_signal + (1 - alpha) * self.error_ema
        self.difficulty_score = self.error_ema

        if has_error:
            self.error_count += 1

    def add_outcome_history(
        self,
        item: SampleOutcomeHistoryItem,
        max_items_per_type: int = 20,
    ) -> None:
        """追加跨轮评估历史，并按 prompt_type 保留最近记录。"""
        self.outcome_history.append(item)
        grouped: dict[str, list[SampleOutcomeHistoryItem]] = {}
        for outcome in self.outcome_history:
            grouped.setdefault(outcome.prompt_type, []).append(outcome)

        trimmed: list[SampleOutcomeHistoryItem] = []
        for prompt_type in sorted(grouped):
            outcomes = sorted(grouped[prompt_type], key=lambda outcome: outcome.iteration)
            trimmed.extend(outcomes[-max_items_per_type:])
        self.outcome_history = sorted(
            trimmed,
            key=lambda outcome: (outcome.iteration, outcome.prompt_type),
        )

    def get_outcome_history(
        self,
        prompt_type: str | None = None,
        limit: int | None = None,
    ) -> list[SampleOutcomeHistoryItem]:
        """获取最近评估历史。"""
        if prompt_type is None:
            outcomes = list(self.outcome_history)
        else:
            outcomes = [o for o in self.outcome_history if o.prompt_type == prompt_type]
        outcomes = sorted(outcomes, key=lambda outcome: outcome.iteration)
        if limit is None:
            return outcomes
        return outcomes[-limit:]

    def get_or_create_trajectory(
        self,
        prompt_type: Literal["extraction", "analysis"],
        iteration: int,
    ) -> SampleOptimizationTrajectory:
        """获取或创建当前 sample 的单轮优化轨迹。"""
        for trajectory in self.optimization_trajectory:
            if trajectory.prompt_type == prompt_type and trajectory.iteration == iteration:
                return trajectory
        trajectory = SampleOptimizationTrajectory(
            sample_id=self.sample_id,
            prompt_type=prompt_type,
            iteration=iteration,
        )
        self.optimization_trajectory.append(trajectory)
        self._trim_optimization_trajectory()
        return trajectory

    def add_optimization_trajectory(
        self,
        trajectory: SampleOptimizationTrajectory,
        max_items_per_type: int = 20,
    ) -> None:
        """追加或替换 sample 优化轨迹。"""
        self.optimization_trajectory = [
            item for item in self.optimization_trajectory
            if not (
                item.prompt_type == trajectory.prompt_type
                and item.iteration == trajectory.iteration
            )
        ]
        self.optimization_trajectory.append(trajectory)
        self._trim_optimization_trajectory(max_items_per_type=max_items_per_type)

    def get_optimization_trajectory(
        self,
        prompt_type: str | None = None,
        limit: int | None = None,
    ) -> list[SampleOptimizationTrajectory]:
        """获取 sample 优化轨迹。"""
        if prompt_type is None:
            items = list(self.optimization_trajectory)
        else:
            items = [item for item in self.optimization_trajectory if item.prompt_type == prompt_type]
        items = sorted(items, key=lambda item: (item.iteration, item.prompt_type))
        if limit is None:
            return items
        return items[-limit:]

    def _trim_optimization_trajectory(self, max_items_per_type: int = 20) -> None:
        grouped: dict[str, list[SampleOptimizationTrajectory]] = {}
        for trajectory in self.optimization_trajectory:
            grouped.setdefault(trajectory.prompt_type, []).append(trajectory)

        trimmed: list[SampleOptimizationTrajectory] = []
        for prompt_type in sorted(grouped):
            trajectories = sorted(grouped[prompt_type], key=lambda item: item.iteration)
            trimmed.extend(trajectories[-max_items_per_type:])
        self.optimization_trajectory = sorted(
            trimmed,
            key=lambda item: (item.iteration, item.prompt_type),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "selected_count": self.selected_count,
            "selection_ema": self.selection_ema,
            "last_selected_iteration": self.last_selected_iteration,
            "frequency_score": self.frequency_score,
            "error_count": self.error_count,
            "error_ema": self.error_ema,
            "difficulty_score": self.difficulty_score,
            "last_extraction_status": self.last_extraction_status,
            "last_analysis_status": self.last_analysis_status,
            "historical_fixed_count": self.historical_fixed_count,
            "historical_broken_count": self.historical_broken_count,
            "generated_extraction_patch_count": self.generated_extraction_patch_count,
            "generated_analysis_patch_count": self.generated_analysis_patch_count,
            "outcome_history": [item.to_dict() for item in self.outcome_history],
            "optimization_trajectory": [
                item.to_dict() for item in self.optimization_trajectory
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleState":
        state = cls(sample_id=data.get("sample_id", ""))
        for key in (
            "selected_count",
            "selection_ema",
            "last_selected_iteration",
            "frequency_score",
            "error_count",
            "error_ema",
            "difficulty_score",
            "last_extraction_status",
            "last_analysis_status",
            "historical_fixed_count",
            "historical_broken_count",
            "generated_extraction_patch_count",
            "generated_analysis_patch_count",
        ):
            if key in data:
                setattr(state, key, data[key])
        state.outcome_history = [
            SampleOutcomeHistoryItem.from_dict(item)
            for item in data.get("outcome_history", [])
            if isinstance(item, dict)
        ]
        state.optimization_trajectory = [
            SampleOptimizationTrajectory.from_dict(item)
            for item in data.get("optimization_trajectory", [])
            if isinstance(item, dict)
        ]
        return state


@dataclass
class SampleTrace:
    """单轮过程记录，记录样本在某一轮优化中的详细过程。"""
    sample_id: str
    phase: str  # "prompt_optimization" 或 "fewshot_optimization"
    iteration: int
    selected: bool = False
    participated_in_extraction: bool = False
    participated_in_analysis: bool = False

    # 抽取结果
    base_extraction_result_id: str | None = None
    base_extraction_status: str | None = None
    final_extraction_result_id: str | None = None
    final_extraction_status: str | None = None

    # 分析结果
    analysis_result_id: str | None = None
    analysis_correct: bool | None = None

    # 反思结果
    reflection_result_id: str | None = None
    reflection_success: bool | None = None

    # Patch 相关
    generated_extraction_patch_ids: list[str] = field(default_factory=list)
    generated_analysis_patch_ids: list[str] = field(default_factory=list)

    # 转换记录
    fixed_by_patch_ids: list[str] = field(default_factory=list)
    broken_by_patch_ids: list[str] = field(default_factory=list)
    toxic_trigger_patch_ids: list[str] = field(default_factory=list)

    # 转换类型
    extraction_transition: str | None = None  # "fixed", "broken", "unchanged_wrong", "unchanged_correct"
    analysis_transition: str | None = None  # "fixed", "broken", "unchanged_wrong", "unchanged_correct"

    # 其他
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "phase": self.phase,
            "iteration": self.iteration,
            "selected": self.selected,
            "participated_in_extraction": self.participated_in_extraction,
            "participated_in_analysis": self.participated_in_analysis,
            "base_extraction_result_id": self.base_extraction_result_id,
            "base_extraction_status": self.base_extraction_status,
            "final_extraction_result_id": self.final_extraction_result_id,
            "final_extraction_status": self.final_extraction_status,
            "analysis_result_id": self.analysis_result_id,
            "analysis_correct": self.analysis_correct,
            "reflection_result_id": self.reflection_result_id,
            "reflection_success": self.reflection_success,
            "generated_extraction_patch_ids": list(self.generated_extraction_patch_ids),
            "generated_analysis_patch_ids": list(self.generated_analysis_patch_ids),
            "fixed_by_patch_ids": list(self.fixed_by_patch_ids),
            "broken_by_patch_ids": list(self.broken_by_patch_ids),
            "toxic_trigger_patch_ids": list(self.toxic_trigger_patch_ids),
            "extraction_transition": self.extraction_transition,
            "analysis_transition": self.analysis_transition,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleTrace":
        return cls(
            sample_id=data.get("sample_id", ""),
            phase=data.get("phase", ""),
            iteration=int(data.get("iteration", 0)),
            selected=bool(data.get("selected", False)),
            participated_in_extraction=bool(data.get("participated_in_extraction", False)),
            participated_in_analysis=bool(data.get("participated_in_analysis", False)),
            base_extraction_result_id=data.get("base_extraction_result_id"),
            base_extraction_status=data.get("base_extraction_status"),
            final_extraction_result_id=data.get("final_extraction_result_id"),
            final_extraction_status=data.get("final_extraction_status"),
            analysis_result_id=data.get("analysis_result_id"),
            analysis_correct=data.get("analysis_correct"),
            reflection_result_id=data.get("reflection_result_id"),
            reflection_success=data.get("reflection_success"),
            generated_extraction_patch_ids=list(data.get("generated_extraction_patch_ids", [])),
            generated_analysis_patch_ids=list(data.get("generated_analysis_patch_ids", [])),
            fixed_by_patch_ids=list(data.get("fixed_by_patch_ids", [])),
            broken_by_patch_ids=list(data.get("broken_by_patch_ids", [])),
            toxic_trigger_patch_ids=list(data.get("toxic_trigger_patch_ids", [])),
            extraction_transition=data.get("extraction_transition", data.get("transition")),
            analysis_transition=data.get("analysis_transition"),
            notes=list(data.get("notes", [])),
        )


@dataclass
class SampleSet:
    """样本集合，管理所有样本及其状态。"""
    specs: dict[str, SampleSpec] = field(default_factory=dict)
    states: dict[str, SampleState] = field(default_factory=dict)
    traces: list[SampleTrace] = field(default_factory=list)

    def add_spec(self, spec: SampleSpec) -> None:
        """添加样本规格。"""
        self.specs[spec.id] = spec
        if spec.id not in self.states:
            self.states[spec.id] = SampleState(sample_id=spec.id)

    def get_active_specs(self) -> list[SampleSpec]:
        """获取所有活跃样本。"""
        return [s for s in self.specs.values() if s.active]

    def add_trace(self, trace: SampleTrace) -> None:
        """添加本轮过程记录。"""
        self.traces.append(trace)

    def get_traces_for_iteration(self, phase: str, iteration: int) -> list[SampleTrace]:
        """获取特定轮次的过程记录。"""
        return [t for t in self.traces if t.phase == phase and t.iteration == iteration]

    def clear_traces_for_iteration(self, phase: str, iteration: int) -> None:
        """清除特定轮次的过程记录。"""
        self.traces = [t for t in self.traces if t.phase != phase or t.iteration != iteration]


@dataclass
class SampleBatch:
    """抽样批次，记录某一轮抽样的结果。"""
    id: str
    phase: str
    iteration: int
    sample_ids: list[str]
    sampler_name: str
    scores: dict[str, dict] = field(default_factory=dict)  # sample_id -> score details
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phase": self.phase,
            "iteration": self.iteration,
            "sample_ids": list(self.sample_ids),
            "sampler_name": self.sampler_name,
            "scores": dict(self.scores),
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleBatch":
        return cls(
            id=data.get("id", ""),
            phase=data.get("phase", ""),
            iteration=int(data.get("iteration", 0)),
            sample_ids=list(data.get("sample_ids", [])),
            sampler_name=data.get("sampler_name", ""),
            scores=dict(data.get("scores", {})),
            metadata=dict(data.get("metadata", {})),
            warnings=list(data.get("warnings", [])),
        )
