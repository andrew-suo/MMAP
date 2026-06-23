"""重构后的 MMAP 模块。

根据设计文档 v1.0，重构后的 MMAP 采用三阶段流程：
1. Prompt Structuring Phase
2. Prompt Optimization Phase
3. Few-shot Optimization Phase

模块导出：
- Sample 三层设计：SampleSpec, SampleState, SampleTrace, SampleSet, SampleBatch
- 数据加载：DatasetLoader
- 抽样策略：BaseSampler, RandomSampler, DifficultySampler, FrequencySampler, DifficultyFrequencySampler
- Batch Size 控制：BatchSizeController
- 结构化 Prompt：StructuredPrompt, PromptSection
- Prompt Structuring Phase：PromptStructuringPhase
- Prompt Optimization Phase：PromptOptimizationPhase, ExtractionPromptOptimizationStage, AnalysisPromptOptimizationStage
- Few-shot Optimization Phase：FewshotOptimizationPhase
- 配置：RefactoredConfig, RunConfig, DatasetConfig
- 运行器：MMAPRunner, RunPlan, RunSummary
"""

from .sample import (
    SampleAsset,
    SampleSpec,
    SampleState,
    SampleTrace,
    SampleSet,
    SampleBatch,
)

from .dataset_loader import (
    DatasetLoader,
    load_sample_specs,
    create_sample_set,
)

from .sampler import (
    SamplerConfig,
    BaseSampler,
    RandomSampler,
    DifficultySampler,
    FrequencySampler,
    DifficultyFrequencySampler,
    create_sampler,
)

from .batch_size_controller import (
    BatchSizeControllerConfig,
    BatchSizeControllerState,
    BatchSizeController,
)

from .structured_prompt import (
    PromptSection,
    StructuredPrompt,
)

from .prompt_structuring_phase import (
    PromptStructuringConfig,
    MarkdownParser,
    PromptStructuringPhase,
)

from .patch import (
    ExtractionPatch,
    AnalysisPatch,
    PatchMergeReport,
    ToxicityReport,
)

from .extraction_prompt_optimization_stage import (
    ExtractionResult,
    AnalysisResult,
    EvalRecord,
    ExtractionMetrics,
    ExtractionPromptOptimizationStage,
)

from .analysis_prompt_optimization_stage import (
    ReflectionResult,
    AnalysisMetrics,
    AnalysisPromptOptimizationStage,
)

from .prompt_optimization_phase import (
    PromptOptimizationConfig,
    PromptOptimizationIterationResult,
    PromptOptimizationPhase,
)

from .fewshot_optimization_phase import (
    FewshotExample,
    FewshotConfig,
    FewshotMetrics,
    FewshotOptimizationIterationResult,
    FewshotOptimizationPhase,
)

from .config import (
    RunConfig,
    DatasetConfig,
    RefactoredConfig,
    load_config,
)

from .runner import (
    RunPlanStep,
    RunPlan,
    RunSummary,
    MMAPRunner,
)


__all__ = [
    # Sample
    "SampleAsset",
    "SampleSpec",
    "SampleState",
    "SampleTrace",
    "SampleSet",
    "SampleBatch",
    # Dataset
    "DatasetLoader",
    "load_sample_specs",
    "create_sample_set",
    # Sampler
    "SamplerConfig",
    "BaseSampler",
    "RandomSampler",
    "DifficultySampler",
    "FrequencySampler",
    "DifficultyFrequencySampler",
    "create_sampler",
    # Batch Size Controller
    "BatchSizeControllerConfig",
    "BatchSizeControllerState",
    "BatchSizeController",
    # Structured Prompt
    "PromptSection",
    "StructuredPrompt",
    # Prompt Structuring Phase
    "PromptStructuringConfig",
    "MarkdownParser",
    "PromptStructuringPhase",
    # Patch
    "ExtractionPatch",
    "AnalysisPatch",
    "PatchMergeReport",
    "ToxicityReport",
    # Extraction Prompt Optimization Stage
    "ExtractionResult",
    "AnalysisResult",
    "EvalRecord",
    "ExtractionMetrics",
    "ExtractionPromptOptimizationStage",
    # Analysis Prompt Optimization Stage
    "ReflectionResult",
    "AnalysisMetrics",
    "AnalysisPromptOptimizationStage",
    # Prompt Optimization Phase
    "PromptOptimizationConfig",
    "PromptOptimizationIterationResult",
    "PromptOptimizationPhase",
    # Few-shot Optimization Phase
    "FewshotExample",
    "FewshotConfig",
    "FewshotMetrics",
    "FewshotOptimizationIterationResult",
    "FewshotOptimizationPhase",
    # Config
    "RunConfig",
    "DatasetConfig",
    "RefactoredConfig",
    "load_config",
    # Runner
    "RunPlanStep",
    "RunPlan",
    "RunSummary",
    "MMAPRunner",
]