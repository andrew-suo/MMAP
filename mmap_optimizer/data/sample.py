"""重构后的 Sample 三层设计。

根据设计文档，Sample 拆成三层：
- SampleSpec：静态样本事实
- SampleState：跨轮动态状态
- SampleTrace：单轮过程记录
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


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
        return state


@dataclass
class SampleTrace:
    """单轮过程记录，记录样本在某一轮优化中的详细过程。"""
    sample_id: str
    phase: str  # "prompt_optimization" 或 "fewshot_optimization"
    iteration: int
    selected: bool = False

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
    transition: str | None = None  # "fixed", "broken", "unchanged_wrong", "unchanged_correct"

    # 其他
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "phase": self.phase,
            "iteration": self.iteration,
            "selected": self.selected,
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
            "transition": self.transition,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SampleTrace":
        return cls(
            sample_id=data.get("sample_id", ""),
            phase=data.get("phase", ""),
            iteration=int(data.get("iteration", 0)),
            selected=bool(data.get("selected", False)),
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
            transition=data.get("transition"),
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
