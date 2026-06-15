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
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    verify_ssl: bool = True
    chat_template_kwargs: dict[str, Any] | None = None


@dataclass
class OptimizerConfig:
    run_dir: str = "runs"
    batch_size: int = 24
    dynamic_validation_batch_size: int = 48
    dynamic_validation_min_label_count: int = 1
    dynamic_validation_cover_difficulty_bins: bool = True
    dynamic_validation_recent_window_rounds: int = 3
    dynamic_validation_max_recent_selections: int = 1
    max_text_rounds: int = 10
    extraction_line_budget: int | None = None
    analysis_line_budget: int | None = None
    fewshot_enabled: bool = False
    fewshot_max_rounds: int = 5
    fewshot_max_slots: int = 5
    fewshot_min_accuracy_delta: float = 0.0
    analysis_json_repair_enabled: bool = False
    analysis_json_repair_max_attempts: int = 1
    patch_semantic_merge_enabled: bool = False
    patch_root_audit_enabled: bool = False
    llm_compression_enabled: bool = False
    patch_repair_enabled: bool = False
    patch_repair_max_attempts: int = 1
    prompt_health_check_enabled: bool = True
    prompt_snapshot_enabled: bool = True
    eval_voting_enabled: bool = True
    eval_vote_rounds: int = 3
    execution_max_workers: int = 1
    contribution_feedback_enabled: bool = True
    debug_enabled: bool = True
    scenario_id: str | None = None
    extraction_model: ModelConfig = field(default_factory=ModelConfig)
    optimizer_model: ModelConfig = field(default_factory=ModelConfig)


@dataclass
class ExecutionConfig:
    """Execution controls shared by CLI, runners, and executor adapters."""

    mode: str = "serial"
    max_workers: int = 1
    timeout_seconds: float | None = None
    retry_attempts: int = 0
    retry_backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.mode not in {"serial", "thread_pool"}:
            raise ValueError("ExecutionConfig.mode must be 'serial' or 'thread_pool'")
        if self.max_workers < 1:
            raise ValueError("ExecutionConfig.max_workers must be >= 1")
        if self.retry_attempts < 0:
            raise ValueError("ExecutionConfig.retry_attempts must be >= 0")


def execution_config_from_mapping(data: dict[str, Any] | None) -> ExecutionConfig:
    data = data or {}
    return ExecutionConfig(
        mode=str(data.get("mode", "thread_pool" if int(data.get("max_workers", 1)) > 1 else "serial")),
        max_workers=int(data.get("max_workers", 1)),
        timeout_seconds=(None if data.get("timeout_seconds") is None else float(data.get("timeout_seconds"))),
        retry_attempts=int(data.get("retry_attempts", data.get("retries", 0))),
        retry_backoff_seconds=float(data.get("retry_backoff_seconds", data.get("retry_backoff", 0.0))),
    )


def validate_optimizer_config_mapping(data: dict[str, Any] | None) -> list[str]:
    """Return human-readable config validation errors without raising."""

    errors: list[str] = []
    try:
        config = optimizer_config_from_mapping(data)
    except Exception as exc:  # validation entry point intentionally reports all parse failures
        return [f"CONFIG_PARSE_ERROR: {exc}"]
    if config.batch_size < 1:
        errors.append("text_optimization.batch_size must be >= 1")
    if config.dynamic_validation_batch_size < 1:
        errors.append("dynamic_validation.batch_size must be >= 1")
    if config.max_text_rounds < 0:
        errors.append("text_optimization.max_rounds must be >= 0")
    if config.execution_max_workers < 1:
        errors.append("execution.max_workers must be >= 1")
    if config.eval_vote_rounds < 1:
        errors.append("evaluation.vote_rounds must be >= 1")
    return errors


def load_mapping(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in {".yaml", ".yml"}:
        if yaml is not None:
            data = yaml.safe_load(text)
            return data or {}
        return _parse_simple_yaml_mapping(text)
    return json.loads(text)


def _parse_scalar(value: str) -> Any:
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


def _parse_simple_yaml_mapping(text: str) -> dict[str, Any]:
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


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def model_config_from_mapping(data: dict[str, Any] | None) -> ModelConfig:
    data = data or {}
    return ModelConfig(
        provider=data.get("provider", "mock"),
        model=data.get("model", "mock-model"),
        base_url=data.get("base_url"),
        api_key_env=data.get("api_key_env"),
        api_key=data.get("api_key"),
        temperature=float(data.get("temperature", 0.0)),
        max_tokens=int(data.get("max_tokens", 2048)),
        verify_ssl=_bool_value(data.get("verify_ssl", data.get("ssl_verify", True))),
        chat_template_kwargs=data.get("chat_template_kwargs"),
    )


def model_config_to_request_dict(config: ModelConfig) -> dict[str, Any]:
    request = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    if config.chat_template_kwargs is not None:
        request["chat_template_kwargs"] = config.chat_template_kwargs
    return request


def optimizer_config_from_mapping(data: dict[str, Any] | None) -> OptimizerConfig:
    data = data or {}
    text = data.get("text_optimization", {}) or {}
    dval = data.get("dynamic_validation", {}) or {}
    compression = data.get("compression", {}) or {}
    fewshot = data.get("fewshot", {}) or {}
    analysis = data.get("analysis", {}) or {}
    patch_merge = data.get("patch_merge", {}) or {}
    patch_repair = data.get("patch_repair", {}) or {}
    health = data.get("health", {}) or {}
    snapshots = data.get("snapshots", {}) or {}
    evaluation = data.get("evaluation", {}) or {}
    execution = data.get("execution", {}) or {}
    contribution = data.get("contribution", {}) or {}
    debug = data.get("debug", {}) or {}
    models = data.get("models", {}) or {}
    extraction_model_data = data.get("extraction_model") or models.get("extraction") or {}
    optimizer_model_data = data.get("optimizer_model") or models.get("optimizer") or {}
    return OptimizerConfig(
        run_dir=data.get("run_dir", "runs"),
        batch_size=int(text.get("batch_size", data.get("batch_size", 24))),
        dynamic_validation_batch_size=int(dval.get("batch_size", data.get("dynamic_validation_batch_size", 48))),
        dynamic_validation_min_label_count=int(
            dval.get("min_label_count", data.get("dynamic_validation_min_label_count", 1))
        ),
        dynamic_validation_cover_difficulty_bins=_bool_value(
            dval.get("cover_difficulty_bins", data.get("dynamic_validation_cover_difficulty_bins", True))
        ),
        dynamic_validation_recent_window_rounds=int(
            dval.get("recent_window_rounds", data.get("dynamic_validation_recent_window_rounds", 3))
        ),
        dynamic_validation_max_recent_selections=int(
            dval.get("max_recent_selections", data.get("dynamic_validation_max_recent_selections", 1))
        ),
        max_text_rounds=int(text.get("max_rounds", data.get("max_text_rounds", 10))),
        extraction_line_budget=compression.get("extraction_line_budget", data.get("extraction_line_budget")),
        analysis_line_budget=compression.get("analysis_line_budget", data.get("analysis_line_budget")),
        fewshot_enabled=_bool_value(fewshot.get("enabled", data.get("fewshot_enabled", False))),
        fewshot_max_rounds=int(fewshot.get("max_rounds", data.get("fewshot_max_rounds", 5))),
        fewshot_max_slots=int(fewshot.get("max_slots", data.get("fewshot_max_slots", 5))),
        fewshot_min_accuracy_delta=float(fewshot.get("min_accuracy_delta", data.get("fewshot_min_accuracy_delta", 0.0))),
        analysis_json_repair_enabled=_bool_value(analysis.get("json_repair_enabled", data.get("analysis_json_repair_enabled", False))),
        analysis_json_repair_max_attempts=int(analysis.get("json_repair_max_attempts", data.get("analysis_json_repair_max_attempts", 1))),
        patch_semantic_merge_enabled=_bool_value(patch_merge.get("semantic_enabled", data.get("patch_semantic_merge_enabled", False))),
        patch_root_audit_enabled=_bool_value(patch_merge.get("root_audit_enabled", data.get("patch_root_audit_enabled", False))),
        llm_compression_enabled=_bool_value(compression.get("llm_enabled", data.get("llm_compression_enabled", False))),
        patch_repair_enabled=_bool_value(patch_repair.get("enabled", data.get("patch_repair_enabled", False))),
        patch_repair_max_attempts=int(patch_repair.get("max_attempts", data.get("patch_repair_max_attempts", 1))),
        prompt_health_check_enabled=_bool_value(health.get("enabled", data.get("prompt_health_check_enabled", True))),
        prompt_snapshot_enabled=_bool_value(snapshots.get("enabled", data.get("prompt_snapshot_enabled", True))),
        eval_voting_enabled=_bool_value(evaluation.get("voting_enabled", data.get("eval_voting_enabled", True))),
        eval_vote_rounds=int(evaluation.get("vote_rounds", data.get("eval_vote_rounds", 3))),
        execution_max_workers=int(execution.get("max_workers", data.get("execution_max_workers", 1))),
        contribution_feedback_enabled=_bool_value(contribution.get("feedback_enabled", data.get("contribution_feedback_enabled", True))),
        debug_enabled=_bool_value(debug.get("enabled", data.get("debug_enabled", True))),
        scenario_id=data.get("scenario_id"),
        extraction_model=model_config_from_mapping(extraction_model_data),
        optimizer_model=model_config_from_mapping(optimizer_model_data),
    )
