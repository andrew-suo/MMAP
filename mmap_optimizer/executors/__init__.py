"""Executor 模块。

导出所有 executor 类和工厂函数。

根据设计文档，executor 负责实际执行抽取、评估、分析、
patch 生成/应用/合并、测毒、压缩、few-shot 等操作。
所有 executor 遵循统一的 Protocol 接口。
"""

from __future__ import annotations

from ..patch.types import CompressionReport, PatchTestRecord, ToxicityReport
from .compression_executor import CompressionExecutor
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
from .merge_executor import MergeExecutor
from .patch_apply_executor import PatchApplyExecutor, PatchApplyReport
from .patch_generation_executor import PatchGenerationExecutor
from .patch_validator import PatchValidator
from .toxicity_executor import ToxicityTestExecutor

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
    # 真实实现
    "PatchGenerationExecutor",
    "PatchApplyExecutor",
    "PatchApplyReport",
    "PatchValidator",
    "MergeExecutor",
    "ToxicityTestExecutor",
    "CompressionExecutor",
    # 数据模型
    "ToxicityReport",
    "PatchTestRecord",
    "CompressionReport",
    # 工厂函数
    "create_executors",
]
