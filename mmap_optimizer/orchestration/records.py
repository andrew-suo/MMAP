from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunRecord:
    id: str
    round_id: str | None
    run_type: str
    sample_id: str | None
    prompt_version_id: str
    rendered_prompt_hash: str
    model_id: str
    raw_output: str | None
    parsed_output: dict[str, Any] | None = None
    success: bool = True
    error_type: str | None = None
    retry_count: int = 0


@dataclass
class OptimizationRound:
    id: str
    index: int
    status: str
    base_extraction_prompt_version_id: str
    base_analysis_prompt_version_id: str
    optimization_batch_ids: list[str] = field(default_factory=list)
    dynamic_validation_batch_id: str | None = None
    extraction_run_ids: list[str] = field(default_factory=list)
    dynamic_validation_run_ids: list[str] = field(default_factory=list)
    accepted_patch_ids: list[str] = field(default_factory=list)
    rejected_patch_ids: list[str] = field(default_factory=list)
    round_metrics_id: str | None = None
    analysis_evolution_report_id: str | None = None
    compression_report_ids: list[str] = field(default_factory=list)
    fewshot_report_ids: list[str] = field(default_factory=list)
    failure_reason: str | None = None
