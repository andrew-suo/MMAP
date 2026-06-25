"""Section 贡献度追踪模块。

通过 EMA（指数移动平均）追踪各 prompt section 的累积贡献度。
压缩时优先压缩低贡献 section。
"""

from __future__ import annotations

from typing import Any


class SectionContributionTracker:
    """追踪各 section 的 EMA 贡献度。

    贡献度范围 [-1, 1]：
    - 正值表示该 section 在正确样本中被引用的频率高（有助于正确判断）
    - 负值表示该 section 在错误样本中被引用的频率高（可能导致错误）
    - 接近 0 表示该 section 很少被引用或正负抵消

    Attributes:
        alpha: EMA 平滑因子，越大越看重近期数据（默认 0.3）
    """

    def __init__(self, alpha: float = 0.3) -> None:
        self.alpha = alpha
        self._ema: dict[str, float] = {}

    def update(
        self,
        batch_attribution: dict[str, list[dict[str, Any]]],
        batch_results: dict[str, bool],
    ) -> None:
        """一轮 batch 后更新 EMA 贡献度。

        Args:
            batch_attribution: {sample_id: [{section_id, reason}, ...]}
                每个样本引用的 section 列表。
            batch_results: {sample_id: is_correct}
                每个样本的判定结果（True=正确，False=错误）。
        """
        if not batch_results:
            return

        total_samples = len(batch_results)

        # 计算本轮各 section 的 batch 平均贡献度
        positive_counts: dict[str, int] = {}
        negative_counts: dict[str, int] = {}

        for sample_id, is_correct in batch_results.items():
            attribution = batch_attribution.get(sample_id, [])
            cited_sections = {
                item.get("section_id", "")
                for item in attribution
                if item.get("section_id")
            }
            for section_id in cited_sections:
                if is_correct:
                    positive_counts[section_id] = positive_counts.get(section_id, 0) + 1
                else:
                    negative_counts[section_id] = negative_counts.get(section_id, 0) + 1

        # 合并所有出现过的 section
        all_sections = set(positive_counts.keys()) | set(negative_counts.keys())

        for section_id in all_sections:
            pos = positive_counts.get(section_id, 0)
            neg = negative_counts.get(section_id, 0)
            frequency = (pos - neg) / total_samples  # [-1, 1]
            prev_ema = self._ema.get(section_id, 0.0)
            self._ema[section_id] = self.alpha * frequency + (1 - self.alpha) * prev_ema

    def get_contribution(self, section_id: str) -> float:
        """获取 section 的 EMA 贡献度。

        Args:
            section_id: section ID

        Returns:
            贡献度 [-1, 1]，未追踪返回 0.0
        """
        return self._ema.get(section_id, 0.0)

    def get_priority_order(self, section_ids: list[str]) -> list[str]:
        """返回按贡献度升序排列的 section_id 列表。

        低贡献（或负贡献）的 section 排在前面，优先压缩。

        Args:
            section_ids: 需要排序的 section ID 列表

        Returns:
            排序后的 section ID 列表
        """
        return sorted(section_ids, key=lambda sid: self.get_contribution(sid))

    def to_dict(self) -> dict[str, float]:
        """序列化为字典。"""
        return dict(self._ema)

    @classmethod
    def from_dict(
        cls, data: dict[str, float], alpha: float = 0.3
    ) -> "SectionContributionTracker":
        """从字典反序列化。

        Args:
            data: to_dict 产生的字典
            alpha: EMA 平滑因子

        Returns:
            SectionContributionTracker 实例
        """
        tracker = cls(alpha=alpha)
        tracker._ema = dict(data)
        return tracker


__all__ = ["SectionContributionTracker"]
