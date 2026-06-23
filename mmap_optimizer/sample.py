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