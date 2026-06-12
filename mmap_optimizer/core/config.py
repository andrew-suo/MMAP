from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency fallback
    yaml = None


@dataclass
class ModelConfig:
    provider: str = "mock"
    model: str = "mock-model"
    base_url: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048


@dataclass
class OptimizerConfig:
    run_dir: str = "runs"
    batch_size: int = 24
    dynamic_validation_batch_size: int = 48
    max_text_rounds: int = 10
    extraction_line_budget: int | None = None
    analysis_line_budget: int | None = None
    fewshot_enabled: bool = False
    fewshot_max_rounds: int = 5
    fewshot_max_slots: int = 5
    fewshot_min_accuracy_delta: float = 0.0
    extraction_model: ModelConfig = field(default_factory=ModelConfig)
    optimizer_model: ModelConfig = field(default_factory=ModelConfig)


def load_mapping(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"} and yaml is not None:
        data = yaml.safe_load(text)
        return data or {}
    return json.loads(text)
