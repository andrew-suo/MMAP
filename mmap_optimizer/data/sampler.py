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
    ) -> SampleBatch:
        """执行抽样。"""
        rng = random.Random(seed + iteration)

        # 获取活跃样本
        active_specs = sample_set.get_active_specs()

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
            id=f"batch_{self.name()}_{iteration}",
            phase="unknown",  # 由调用者设置
            iteration=iteration,
            sample_ids=selected_ids,
            sampler_name=self.name(),
            scores=scores_dict,
        )

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
    else:
        raise ValueError(f"Unknown sampler type: {sampler_type}")
