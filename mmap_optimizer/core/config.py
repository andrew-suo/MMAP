"""重构后的配置模块。

根据设计文档，配置结构如下：
- run: 运行配置
- dataset: 数据集配置
- prompt_structuring: Prompt Structuring 配置
- sampling: 抽样配置
- prompt_optimization: Prompt Optimization 配置
- fewshot_optimization: Few-shot Optimization 配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:
    yaml = None

from ..stages.batch_size_controller import BatchSizeControllerConfig
from ..phases.fewshot_optimization import FewshotConfig
from ..phases.prompt_structuring import PromptStructuringConfig
from ..phases.prompt_optimization import PromptOptimizationConfig
from ..data.sampler import SamplerConfig


@dataclass
class ModelConfig:
    """模型配置（内联自 core.config.ModelConfig）。"""
    provider: str = "mock"
    model: str = "mock-model"
    base_url: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout: int = 120
    verify_ssl: bool = True
    chat_template_kwargs: dict[str, Any] | None = None


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def model_config_from_mapping(data: dict[str, Any] | None) -> ModelConfig:
    """从字典构建 ModelConfig（内联自 core.config.model_config_from_mapping）。"""
    data = data or {}
    return ModelConfig(
        provider=data.get("provider", "mock"),
        model=data.get("model", "mock-model"),
        base_url=data.get("base_url"),
        api_key_env=data.get("api_key_env"),
        api_key=data.get("api_key"),
        temperature=float(data.get("temperature", 0.0)),
        max_tokens=int(data.get("max_tokens", 2048)),
        timeout=int(data.get("timeout", data.get("request_timeout", 120))),
        verify_ssl=_bool_value(data.get("verify_ssl", data.get("ssl_verify", True))),
        chat_template_kwargs=data.get("chat_template_kwargs"),
    )


@dataclass
class RunConfig:
    """运行配置。"""
    seed: int = 42
    output_dir: str = "runs/exp_001"
    # PR4: Mock 边界收敛。None=自动判断（有 model_client 则真实，否则 mock）；
    # True=强制 mock；False=强制真实（缺 model_client 时报错）
    use_mock: bool | None = None


@dataclass
class DatasetConfig:
    """数据集配置。"""
    path: str = "data/samples.jsonl"
    format: str = "jsonl"
    image_root: str | None = None
    ground_truth_path: str | None = None


@dataclass
class PromptsConfig:
    """Prompt 文件路径配置。"""
    extraction: str = "prompts/extraction.txt"
    analysis: str = "prompts/analysis.txt"
    analysis_task: str = "prompts/analysis_task.txt"
    analysis_reflection: str = "prompts/analysis_reflection.txt"
    prompt_standardization: str = "prompts/prompt_standardization.txt"
    patch_generation: str = "prompts/patch_generation.txt"


@dataclass
class RefactoredConfig:
    """重构后的完整配置。"""
    run: RunConfig = field(default_factory=RunConfig)
    dataset: DatasetConfig = field(default_factory=DatasetConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    prompt_structuring: PromptStructuringConfig = field(default_factory=PromptStructuringConfig)
    sampling: SamplerConfig = field(default_factory=SamplerConfig)
    prompt_optimization: PromptOptimizationConfig = field(default_factory=PromptOptimizationConfig)
    fewshot_optimization: FewshotConfig = field(default_factory=FewshotConfig)
    # model client 配置，用于构建真实 executor
    models: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "run": {
                "seed": self.run.seed,
                "output_dir": self.run.output_dir,
                "use_mock": self.run.use_mock,
            },
            "dataset": {
                "path": self.dataset.path,
                "format": self.dataset.format,
                "image_root": self.dataset.image_root,
                "ground_truth_path": self.dataset.ground_truth_path,
            },
            "prompts": {
                "extraction": self.prompts.extraction,
                "analysis": self.prompts.analysis,
                "analysis_task": self.prompts.analysis_task,
                "analysis_reflection": self.prompts.analysis_reflection,
                "prompt_standardization": self.prompts.prompt_standardization,
                "patch_generation": self.prompts.patch_generation,
            },
            "prompt_structuring": {
                "enabled": self.prompt_structuring.enabled,
                "use_model_when_structure_poor": self.prompt_structuring.use_model_when_structure_poor,
            },
            "sampling": {
                "ema_alpha": self.sampling.random_noise_scale,  # 使用 noise scale 作为 alpha 的近似
            },
            "prompt_optimization": {
                "enabled": self.prompt_optimization.enabled,
                "rounds": self.prompt_optimization.rounds,
                "initial_batch_size": self.prompt_optimization.initial_batch_size,
                "min_batch_size": self.prompt_optimization.min_batch_size,
                "max_batch_size": self.prompt_optimization.max_batch_size,
                "batch_size_controller": {
                    "enabled": self.prompt_optimization.batch_size_controller.enabled,
                    "growth_factor": self.prompt_optimization.batch_size_controller.growth_factor,
                    "decrease_factor": self.prompt_optimization.batch_size_controller.decrease_factor,
                    "improvement_epsilon": self.prompt_optimization.batch_size_controller.improvement_epsilon,
                    "shrink_on_rollback": self.prompt_optimization.batch_size_controller.shrink_on_rollback,
                    "shrink_on_no_progress": self.prompt_optimization.batch_size_controller.shrink_on_no_progress,
                },
                "sampler": {
                    "type": self.prompt_optimization.sampler.type,
                    "difficulty_weight": self.prompt_optimization.sampler.difficulty_weight,
                    "frequency_weight": self.prompt_optimization.sampler.frequency_weight,
                },
                "extraction_prompt": {
                    "line_limit": self.prompt_optimization.extraction_prompt_line_limit,
                    "char_limit": self.prompt_optimization.extraction_prompt_char_limit,
                    "compression_enabled": self.prompt_optimization.extraction_prompt_compression_enabled,
                },
                "analysis_prompt": {
                    "line_limit": self.prompt_optimization.analysis_prompt_line_limit,
                    "char_limit": self.prompt_optimization.analysis_prompt_char_limit,
                    "compression_enabled": self.prompt_optimization.analysis_prompt_compression_enabled,
                },
                "patch": {
                    "merge_strategy": self.prompt_optimization.patch_merge_strategy,
                    "toxicity_test": {
                        "enabled": self.prompt_optimization.toxicity_test_enabled,
                        "early_stop": self.prompt_optimization.toxicity_test_early_stop,
                        "sort_by_source_difficulty": self.prompt_optimization.toxicity_test_sort_by_source_difficulty,
                    },
                },
            },
            "fewshot_optimization": {
                "enabled": self.fewshot_optimization.enabled,
                "rounds": self.fewshot_optimization.rounds,
                "batch_size": self.fewshot_optimization.batch_size,
                "slot_count": self.fewshot_optimization.slot_count,
                "sampler": {
                    "type": self.fewshot_optimization.sampler.type,
                },
            },
            "models": dict(self.models) if isinstance(self.models, dict) else {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RefactoredConfig":
        """从字典格式创建。"""
        run_data = data.get("run", {})
        dataset_data = data.get("dataset", {})
        prompt_structuring_data = data.get("prompt_structuring", {})
        sampling_data = data.get("sampling", {})
        prompt_optimization_data = data.get("prompt_optimization", {})
        fewshot_optimization_data = data.get("fewshot_optimization", {})
        models_data = data.get("models", {})
        # PR4: 简单 YAML 解析器可能将 `models: {}` 解析为字符串 "{}"，
        # 这里做一次类型修正，确保 models 始终为 dict。
        if not isinstance(models_data, dict):
            models_data = {}

        # 构建 RunConfig
        run_config = RunConfig(
            seed=run_data.get("seed", 42),
            output_dir=run_data.get("output_dir", "runs/exp_001"),
            use_mock=run_data.get("use_mock", None),
        )

        # 构建 DatasetConfig
        dataset_config = DatasetConfig(
            path=dataset_data.get("path", "data/samples.jsonl"),
            format=dataset_data.get("format", "jsonl"),
            image_root=dataset_data.get("image_root"),
            ground_truth_path=dataset_data.get("ground_truth_path"),
        )

        # 构建 PromptsConfig
        prompts_data = data.get("prompts", {})
        prompts_config = PromptsConfig(
            extraction=prompts_data.get("extraction", "prompts/extraction.txt"),
            analysis=prompts_data.get("analysis", "prompts/analysis.txt"),
            analysis_task=prompts_data.get("analysis_task", "prompts/analysis_task.txt"),
            analysis_reflection=prompts_data.get("analysis_reflection", "prompts/analysis_reflection.txt"),
            prompt_standardization=prompts_data.get("prompt_standardization", "prompts/prompt_standardization.txt"),
            patch_generation=prompts_data.get("patch_generation", "prompts/patch_generation.txt"),
        )

        # 构建 PromptStructuringConfig
        prompt_structuring_config = PromptStructuringConfig(
            enabled=prompt_structuring_data.get("enabled", True),
            use_model_when_structure_poor=prompt_structuring_data.get("use_model_when_structure_poor", True),
            standardization_prompt_path=prompts_config.prompt_standardization,
        )

        # 构建 SamplerConfig
        sampling_config = SamplerConfig(
            type=sampling_data.get("type", "difficulty_frequency"),
            difficulty_weight=sampling_data.get("difficulty_weight", 0.7),
            frequency_weight=sampling_data.get("frequency_weight", 0.3),
            random_noise_scale=sampling_data.get("ema_alpha", 0.01),
        )

        # 构建 PromptOptimizationConfig
        po_batch_size_controller_data = prompt_optimization_data.get("batch_size_controller", {})
        po_sampler_data = prompt_optimization_data.get("sampler", {})
        po_extraction_prompt_data = prompt_optimization_data.get("extraction_prompt", {})
        po_analysis_prompt_data = prompt_optimization_data.get("analysis_prompt", {})
        po_patch_data = prompt_optimization_data.get("patch", {})
        po_toxicity_test_data = po_patch_data.get("toxicity_test", {})

        prompt_optimization_config = PromptOptimizationConfig(
            enabled=prompt_optimization_data.get("enabled", True),
            rounds=prompt_optimization_data.get("rounds", 3),
            initial_batch_size=prompt_optimization_data.get("initial_batch_size", 16),
            min_batch_size=prompt_optimization_data.get("min_batch_size", 8),
            max_batch_size=prompt_optimization_data.get("max_batch_size", 99),
            batch_size_controller=BatchSizeControllerConfig(
                enabled=po_batch_size_controller_data.get("enabled", True),
                initial_batch_size=prompt_optimization_data.get("initial_batch_size", 16),
                min_batch_size=prompt_optimization_data.get("min_batch_size", 8),
                max_batch_size=prompt_optimization_data.get("max_batch_size", 99),
                growth_factor=po_batch_size_controller_data.get("growth_factor", 2.0),
                decrease_factor=po_batch_size_controller_data.get("decrease_factor", 0.8),
                improvement_epsilon=po_batch_size_controller_data.get("improvement_epsilon", 0.0),
                shrink_on_rollback=po_batch_size_controller_data.get("shrink_on_rollback", True),
                shrink_on_no_progress=po_batch_size_controller_data.get("shrink_on_no_progress", True),
            ),
            sampler=SamplerConfig(
                type=po_sampler_data.get("type", "difficulty_frequency"),
                difficulty_weight=po_sampler_data.get("difficulty_weight", 0.7),
                frequency_weight=po_sampler_data.get("frequency_weight", 0.3),
            ),
            extraction_prompt_line_limit=po_extraction_prompt_data.get("line_limit", 300),
            extraction_prompt_char_limit=po_extraction_prompt_data.get("char_limit", 20000),
            extraction_prompt_compression_enabled=po_extraction_prompt_data.get("compression_enabled", True),
            analysis_prompt_line_limit=po_analysis_prompt_data.get("line_limit", 250),
            analysis_prompt_char_limit=po_analysis_prompt_data.get("char_limit", 16000),
            analysis_prompt_compression_enabled=po_analysis_prompt_data.get("compression_enabled", True),
            patch_merge_strategy=po_patch_data.get("merge_strategy", "tree_merge"),
            toxicity_test_enabled=po_toxicity_test_data.get("enabled", True),
            toxicity_test_early_stop=po_toxicity_test_data.get("early_stop", True),
            toxicity_test_sort_by_source_difficulty=po_toxicity_test_data.get("sort_by_source_difficulty", True),
        )

        # 构建 FewshotConfig
        fewshot_sampler_data = fewshot_optimization_data.get("sampler", {})

        fewshot_config = FewshotConfig(
            enabled=fewshot_optimization_data.get("enabled", True),
            rounds=fewshot_optimization_data.get("rounds", 2),
            batch_size=fewshot_optimization_data.get("batch_size", 99),
            slot_count=fewshot_optimization_data.get("slot_count", 5),
            sampler=SamplerConfig(
                type=fewshot_sampler_data.get("type", "frequency"),
            ),
        )

        return cls(
            run=run_config,
            dataset=dataset_config,
            prompts=prompts_config,
            prompt_structuring=prompt_structuring_config,
            sampling=sampling_config,
            prompt_optimization=prompt_optimization_config,
            fewshot_optimization=fewshot_config,
            models=models_data,
        )


def load_config(path: str | Path) -> RefactoredConfig:
    """从文件加载配置。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8")

    if p.suffix.lower() in {".yaml", ".yml"}:
        if yaml is not None:
            data = yaml.safe_load(text)
        else:
            # 简单解析 YAML
            data = _parse_simple_yaml(text)
    else:
        import json
        data = json.loads(text)

    return RefactoredConfig.from_dict(data or {})


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """简单 YAML 解析器。"""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        if not line_without_comment.strip():
            continue

        indent = len(line_without_comment) - len(line_without_comment.lstrip(" "))
        stripped = line_without_comment.strip()

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()

        current = stack[-1][1]

        if value == "":
            child: dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    """解析标量值。"""
    if value in {"", "null", "None", "~"}:
        return None

    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False

    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        return value
