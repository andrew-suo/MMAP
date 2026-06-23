"""Batch Size Controller。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BatchSizeControllerConfig:
    """Batch Size 控制器配置。"""
    enabled: bool = True
    initial_batch_size: int = 16
    min_batch_size: int = 8
    max_batch_size: int = 99
    growth_factor: float = 2.0
    decrease_factor: float = 0.8
    improvement_epsilon: float = 0.0
    shrink_on_rollback: bool = True
    shrink_on_no_progress: bool = True


@dataclass
class BatchSizeControllerState:
    """Batch Size 控制器状态。"""
    current_batch_size: int
    last_accuracy_delta: float | None = None
    history: list[dict[str, Any]] = field(default_factory=list)


class BatchSizeController:
    """自适应 Batch Size 控制器。"""

    def __init__(self, config: BatchSizeControllerConfig):
        self.config = config
        self.state = BatchSizeControllerState(current_batch_size=config.initial_batch_size)

    def get_current_batch_size(self) -> int:
        """获取当前 batch size。"""
        return self.state.current_batch_size

    def update(
        self,
        base_accuracy: float,
        final_accuracy: float | None,
        rollback: bool = False,
        no_progress: bool = False,
    ) -> int:
        """根据本轮结果更新下一轮 batch size。"""
        if not self.config.enabled:
            return self.state.current_batch_size

        delta = None
        if final_accuracy is not None:
            delta = final_accuracy - base_accuracy

        record = {
            "base_accuracy": base_accuracy,
            "final_accuracy": final_accuracy,
            "delta": delta,
            "rollback": rollback,
            "no_progress": no_progress,
            "batch_size_before": self.state.current_batch_size,
        }

        next_batch_size = self.state.current_batch_size

        if rollback and self.config.shrink_on_rollback:
            next_batch_size = max(
                self.config.min_batch_size,
                int(self.state.current_batch_size * self.config.decrease_factor),
            )
        elif no_progress and self.config.shrink_on_no_progress:
            next_batch_size = max(
                self.config.min_batch_size,
                int(self.state.current_batch_size * self.config.decrease_factor),
            )
        elif delta is not None:
            if delta > self.config.improvement_epsilon:
                next_batch_size = min(
                    self.config.max_batch_size,
                    int(self.state.current_batch_size * self.config.growth_factor),
                )
            elif delta < -self.config.improvement_epsilon:
                next_batch_size = max(
                    self.config.min_batch_size,
                    int(self.state.current_batch_size * self.config.decrease_factor),
                )

        self.state.current_batch_size = next_batch_size
        self.state.last_accuracy_delta = delta
        record["batch_size_after"] = next_batch_size
        self.state.history.append(record)

        return next_batch_size

    def reset(self) -> None:
        """重置到初始状态。"""
        self.state = BatchSizeControllerState(current_batch_size=self.config.initial_batch_size)

    def get_history(self) -> list[dict[str, Any]]:
        """获取历史记录。"""
        return self.state.history

    def to_dict(self) -> dict[str, Any]:
        """导出为字典格式。"""
        return {
            "config": {
                "enabled": self.config.enabled,
                "initial_batch_size": self.config.initial_batch_size,
                "min_batch_size": self.config.min_batch_size,
                "max_batch_size": self.config.max_batch_size,
                "growth_factor": self.config.growth_factor,
                "decrease_factor": self.config.decrease_factor,
                "improvement_epsilon": self.config.improvement_epsilon,
                "shrink_on_rollback": self.config.shrink_on_rollback,
                "shrink_on_no_progress": self.config.shrink_on_no_progress,
            },
            "state": {
                "current_batch_size": self.state.current_batch_size,
                "last_accuracy_delta": self.state.last_accuracy_delta,
                "history": self.state.history,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchSizeController":
        """从字典格式导入。"""
        config_data = data.get("config", {})
        config = BatchSizeControllerConfig(
            enabled=config_data.get("enabled", True),
            initial_batch_size=config_data.get("initial_batch_size", 16),
            min_batch_size=config_data.get("min_batch_size", 8),
            max_batch_size=config_data.get("max_batch_size", 99),
            growth_factor=config_data.get("growth_factor", 2.0),
            decrease_factor=config_data.get("decrease_factor", 0.8),
            improvement_epsilon=config_data.get("improvement_epsilon", 0.0),
            shrink_on_rollback=config_data.get("shrink_on_rollback", True),
            shrink_on_no_progress=config_data.get("shrink_on_no_progress", True),
        )

        controller = cls(config)

        state_data = data.get("state", {})
        controller.state.current_batch_size = state_data.get("current_batch_size", config.initial_batch_size)
        controller.state.last_accuracy_delta = state_data.get("last_accuracy_delta")
        controller.state.history = state_data.get("history", [])

        return controller
