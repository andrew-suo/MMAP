"""抽样策略模块。

根据设计文档，第一版只保留四种抽样策略：
1. RandomSampler - 随机抽样
2. DifficultySampler - 困难样本优先
3. FrequencySampler - 低频样本优先
4. DifficultyFrequencySampler - 困难度和低频综合考虑
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .sample import SampleBatch, SampleSet, SampleSpec, SampleState


@dataclass
class SamplerConfig:
    """抽样器配置。"""
    type: str = "difficulty_frequency"
    difficulty_weight: float = 0.7
    frequency_weight: float = 0.3
    random_noise_scale: float = 0.01
    error_ratio: float = 0.6
    success_ratio: float = 0.25
    low_frequency_ratio: float = 0.15
    fallback_to_difficulty_frequency: bool = True


class BaseSampler(ABC):
    """抽样器基类。"""

    def __init__(self, config: SamplerConfig | None = None):
        self.config = config or SamplerConfig(type=self.name())

    @abstractmethod
    def name(self) -> str:
        """返回抽样器名称。"""
        pass

    @abstractmethod
    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        """计算样本得分，得分越高越优先被选中。"""
        pass

    def sample(
        self,
        sample_set: SampleSet,
        batch_size: int,
        iteration: int,
        seed: int = 42,
        update_state: bool = True,
        excluded_sample_ids: set[str] | None = None,
        batch_id_prefix: str = "batch",
    ) -> SampleBatch:
        """执行抽样。"""
        rng = random.Random(seed + iteration)
        excluded = excluded_sample_ids or set()

        # 获取活跃样本
        active_specs = [s for s in sample_set.get_active_specs() if s.id not in excluded]

        # 计算每个样本的得分
        scored_specs: list[tuple[SampleSpec, float, dict[str, Any]]] = []
        for spec in active_specs:
            state = sample_set.states.get(spec.id, SampleState(sample_id=spec.id))
            score = self.compute_score(spec, state, rng)
            score_details = {
                "difficulty_score": state.difficulty_score,
                "frequency_score": state.frequency_score,
                "error_ema": state.error_ema,
                "selected_count": state.selected_count,
            }
            scored_specs.append((spec, score, score_details))

        # 按得分排序（降序）
        scored_specs.sort(key=lambda x: x[1], reverse=True)

        # 选择前 batch_size 个样本
        selected_ids = [spec.id for spec, _, _ in scored_specs[:batch_size]]
        scores_dict = {spec.id: details for spec, _, details in scored_specs[:batch_size]}

        # 创建批次
        batch = SampleBatch(
            id=f"{batch_id_prefix}_{self.name()}_{iteration}",
            phase="unknown",  # 由调用者设置
            iteration=iteration,
            sample_ids=selected_ids,
            sampler_name=self.name(),
            scores=scores_dict,
        )

        if not update_state:
            return batch

        # 更新样本状态
        for spec_id in selected_ids:
            state = sample_set.states.get(spec_id)
            if state:
                state.update_selection(selected=True, iteration=iteration)

        # 更新未被选中的样本状态
        for spec in active_specs:
            if spec.id not in selected_ids:
                state = sample_set.states.get(spec.id)
                if state:
                    state.update_selection(selected=False, iteration=iteration)

        return batch

    def sample_validation(
        self,
        sample_set: SampleSet,
        batch_size: int,
        iteration: int,
        seed: int = 42,
        excluded_sample_ids: set[str] | None = None,
    ) -> SampleBatch:
        """抽取 validation batch，不更新样本选择状态。"""
        batch = self.sample(
            sample_set=sample_set,
            batch_size=batch_size,
            iteration=iteration,
            seed=seed,
            update_state=False,
            excluded_sample_ids=excluded_sample_ids,
            batch_id_prefix="validation_batch",
        )
        batch.phase = "prompt_optimization_validation"
        return batch


class RandomSampler(BaseSampler):
    """随机抽样器。"""

    def name(self) -> str:
        return "random"

    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        # 随机得分
        return rng.random()


class DifficultySampler(BaseSampler):
    """困难样本优先抽样器。

    困难主要来自错误次数和错误 EMA。
    score = difficulty_score + random_noise
    """

    def name(self) -> str:
        return "difficulty"

    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        difficulty_score = state.difficulty_score
        random_noise = rng.random() * self.config.random_noise_scale
        return difficulty_score + random_noise


class FrequencySampler(BaseSampler):
    """低频样本优先抽样器。

    低频主要来自采样次数和采样 EMA。
    frequency_score = 1 / (1 + selected_count)
    score = frequency_score + random_noise
    """

    def name(self) -> str:
        return "frequency"

    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        frequency_score = state.frequency_score
        random_noise = rng.random() * self.config.random_noise_scale
        return frequency_score + random_noise


class DifficultyFrequencySampler(BaseSampler):
    """困难度和低频综合考虑抽样器。

    score = difficulty_weight * difficulty_score
          + frequency_weight * frequency_score
          + random_noise

    Prompt Optimization 默认使用此策略。
    """

    def name(self) -> str:
        return "difficulty_frequency"

    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        difficulty_score = state.difficulty_score
        frequency_score = state.frequency_score
        random_noise = rng.random() * self.config.random_noise_scale

        return (
            self.config.difficulty_weight * difficulty_score
            + self.config.frequency_weight * frequency_score
            + random_noise
        )


class BalancedTraceSampler(BaseSampler):
    """按 error / success / low-frequency 样本池配额采样。"""

    def name(self) -> str:
        return "balanced_trace"

    def compute_score(self, spec: SampleSpec, state: SampleState, rng: random.Random) -> float:
        return (
            self.config.difficulty_weight * state.difficulty_score
            + self.config.frequency_weight * state.frequency_score
            + rng.random() * self.config.random_noise_scale
        )

    def sample(
        self,
        sample_set: SampleSet,
        batch_size: int,
        iteration: int,
        seed: int = 42,
        update_state: bool = True,
        excluded_sample_ids: set[str] | None = None,
        batch_id_prefix: str = "batch",
    ) -> SampleBatch:
        rng = random.Random(seed + iteration)
        excluded = excluded_sample_ids or set()
        active_specs = [s for s in sample_set.get_active_specs() if s.id not in excluded]
        states = {
            spec.id: sample_set.states.get(spec.id, SampleState(sample_id=spec.id))
            for spec in active_specs
        }

        error_count = int(batch_size * self.config.error_ratio)
        success_count = int(batch_size * self.config.success_ratio)
        low_frequency_count = max(0, batch_size - error_count - success_count)

        error_pool = [
            spec for spec in active_specs
            if states[spec.id].last_extraction_status in {"wrong", "invalid"}
            or states[spec.id].last_analysis_status == "wrong"
            or states[spec.id].error_ema > 0
        ]
        success_pool = [
            spec for spec in active_specs
            if states[spec.id].last_extraction_status == "correct"
            or states[spec.id].last_analysis_status == "correct"
        ]
        low_frequency_pool = list(active_specs)

        error_pool.sort(
            key=lambda s: (
                states[s.id].difficulty_score,
                states[s.id].error_count,
                rng.random() * self.config.random_noise_scale,
            ),
            reverse=True,
        )
        success_pool.sort(
            key=lambda s: (
                -states[s.id].historical_broken_count,
                states[s.id].frequency_score,
                -states[s.id].selected_count,
                rng.random() * self.config.random_noise_scale,
            ),
            reverse=True,
        )
        low_frequency_pool.sort(
            key=lambda s: (
                states[s.id].frequency_score,
                rng.random() * self.config.random_noise_scale,
            ),
            reverse=True,
        )

        selected: list[SampleSpec] = []
        source_by_id: dict[str, str] = {}

        def add_from(pool: list[SampleSpec], limit: int, source: str) -> None:
            for spec in pool:
                if len([sid for sid, src in source_by_id.items() if src == source]) >= limit:
                    break
                if spec.id in source_by_id:
                    continue
                selected.append(spec)
                source_by_id[spec.id] = source

        add_from(error_pool, error_count, "error")
        add_from(success_pool, success_count, "success")
        add_from(low_frequency_pool, low_frequency_count, "low_frequency")

        fallback_count = 0
        if len(selected) < batch_size and self.config.fallback_to_difficulty_frequency:
            fallback = DifficultyFrequencySampler(self.config)
            scored = []
            selected_ids = {spec.id for spec in selected}
            for spec in active_specs:
                if spec.id in selected_ids:
                    continue
                state = states[spec.id]
                scored.append((spec, fallback.compute_score(spec, state, rng)))
            scored.sort(key=lambda x: x[1], reverse=True)
            for spec, _ in scored:
                if len(selected) >= batch_size:
                    break
                selected.append(spec)
                source_by_id[spec.id] = "fallback"
                fallback_count += 1

        selected = selected[:batch_size]
        selected_ids = [spec.id for spec in selected]
        scores_dict = {
            spec.id: {
                "difficulty_score": states[spec.id].difficulty_score,
                "frequency_score": states[spec.id].frequency_score,
                "error_ema": states[spec.id].error_ema,
                "selected_count": states[spec.id].selected_count,
                "pool": source_by_id.get(spec.id, "unknown"),
            }
            for spec in selected
        }
        pool_counts = {
            "error": sum(1 for src in source_by_id.values() if src == "error"),
            "success": sum(1 for src in source_by_id.values() if src == "success"),
            "low_frequency": sum(1 for src in source_by_id.values() if src == "low_frequency"),
            "fallback": fallback_count,
        }
        batch = SampleBatch(
            id=f"{batch_id_prefix}_{self.name()}_{iteration}",
            phase="unknown",
            iteration=iteration,
            sample_ids=selected_ids,
            sampler_name=self.name(),
            scores=scores_dict,
            metadata={
                "pool_counts": pool_counts,
                "requested_ratios": {
                    "error": self.config.error_ratio,
                    "success": self.config.success_ratio,
                    "low_frequency": self.config.low_frequency_ratio,
                },
                "filled_by_fallback_count": fallback_count,
            },
        )

        if update_state:
            selected_set = set(selected_ids)
            for spec_id in selected_ids:
                state = sample_set.states.get(spec_id)
                if state:
                    state.update_selection(selected=True, iteration=iteration)
            for spec in active_specs:
                if spec.id not in selected_set:
                    state = sample_set.states.get(spec.id)
                    if state:
                        state.update_selection(selected=False, iteration=iteration)

        return batch


def create_sampler(config: SamplerConfig) -> BaseSampler:
    """根据配置创建抽样器。"""
    sampler_type = config.type.lower()

    if sampler_type == "random":
        return RandomSampler(config)
    elif sampler_type == "difficulty":
        return DifficultySampler(config)
    elif sampler_type == "frequency":
        return FrequencySampler(config)
    elif sampler_type == "difficulty_frequency":
        return DifficultyFrequencySampler(config)
    elif sampler_type == "balanced_trace":
        return BalancedTraceSampler(config)
    else:
        raise ValueError(f"Unknown sampler type: {sampler_type}")
