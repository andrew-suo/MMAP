"""Executor 模块。

导出所有 executor 类和工厂函数。

根据设计文档，executor 负责实际执行抽取、评估、分析、
patch 生成/应用/合并、测毒、压缩、few-shot 等操作。
所有 executor 遵循统一的 Protocol 接口。
"""

from __future__ import annotations

from .factory import create_executors
from .interfaces import (
    AnalysisExecutorProtocol,
    CompressionExecutorProtocol,
    EvaluationExecutorProtocol,
    ExtractionExecutorProtocol,
    FewshotExecutorProtocol,
    MergeExecutorProtocol,
    PatchApplyExecutorProtocol,
    PatchGenerationExecutorProtocol,
    ToxicityTestExecutorProtocol,
)

__all__ = [
    # Protocol 接口
    "ExtractionExecutorProtocol",
    "EvaluationExecutorProtocol",
    "AnalysisExecutorProtocol",
    "PatchGenerationExecutorProtocol",
    "PatchApplyExecutorProtocol",
    "MergeExecutorProtocol",
    "ToxicityTestExecutorProtocol",
    "CompressionExecutorProtocol",
    "FewshotExecutorProtocol",
    # 工厂函数
    "create_executors",
]
