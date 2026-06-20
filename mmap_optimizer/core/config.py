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
    timeout: int = 120
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
    extraction_token_budget: int | None = None
    analysis_token_budget: int | None = None
    fewshot_enabled: bool = False
    fewshot_max_rounds: int = 5
    fewshot_max_slots: int = 5
    fewshot_min_accuracy_delta: float = 0.0
    analysis_json_repair_enabled: bool = False
    analysis_json_repair_max_attempts: int = 1
    patch_semantic_merge_enabled: bool = True
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
    # Post-apply regression verification
    post_apply_regression_enabled: bool = True
    post_apply_regression_sample_ratio: float = 0.3
    # Canary sample protection
    canary_protection_enabled: bool = True
    canary_min_consecutive_correct: int = 3
    canary_max_count: int = 10
    # Historical regression detection
    historical_regression_check_enabled: bool = True
    # Blind evaluation & analysis prompt optimization (v4.0)
    blind_evaluation_enabled: bool = True
    blind_eval_three_analysis_vote_enabled: bool = True
    max_restart_attempts: int = 3
    analysis_prompt_optimization_enabled: bool = True
    analysis_patch_semantic_merge_enabled: bool = True
    patch_toxic_test_sample_ratio: float = 0.5
    extraction_model: ModelConfig = field(default_factory=ModelConfig)
    # Patch merge strategy
    patch_merge_strategy: str = "tree_reduce"  # "tree_reduce" 或 "hierarchical"
    optimizer_model: ModelConfig = field(default_factory=ModelConfig)

    def validate(self) -> list[str]:
        """Return human-readable validation issues; empty list means OK."""

        issues: list[str] = []
        if self.batch_size < 1:
            issues.append("text_optimization.batch_size must be >= 1")
        if self.dynamic_validation_batch_size < 1:
            issues.append("dynamic_validation.batch_size must be >= 1")
        if self.dynamic_validation_min_label_count < 1:
            issues.append("dynamic_validation.min_label_count must be >= 1")
        if self.dynamic_validation_recent_window_rounds < 1:
            issues.append("dynamic_validation.recent_window_rounds must be >= 1")
        if self.dynamic_validation_max_recent_selections < 1:
            issues.append("dynamic_validation.max_recent_selections must be >= 1")
        if self.max_text_rounds < 0:
            issues.append("text_optimization.max_rounds must be >= 0")
        if self.execution_max_workers < 1:
            issues.append("execution.max_workers must be >= 1")
        if self.eval_vote_rounds < 1:
            issues.append("evaluation.vote_rounds must be >= 1")
        if self.extraction_line_budget is not None and self.extraction_line_budget < 1:
            issues.append("compression.extraction_line_budget must be None or >= 1")
        if self.analysis_line_budget is not None and self.analysis_line_budget < 1:
            issues.append("compression.analysis_line_budget must be None or >= 1")
        if self.extraction_token_budget is not None and self.extraction_token_budget < 1:
            issues.append("compression.extraction_token_budget must be None or >= 1")
        if self.analysis_token_budget is not None and self.analysis_token_budget < 1:
            issues.append("compression.analysis_token_budget must be None or >= 1")
        if self.fewshot_max_rounds < 0:
            issues.append("fewshot.max_rounds must be >= 0")
        if self.fewshot_max_slots < 0:
            issues.append("fewshot.max_slots must be >= 0")
        if not -1.0 <= self.fewshot_min_accuracy_delta <= 1.0:
            issues.append("fewshot.min_accuracy_delta must be in [-1.0, 1.0]")
        if self.patch_repair_max_attempts < 0:
            issues.append("patch_repair.max_attempts must be >= 0")
        if self.analysis_json_repair_max_attempts < 0:
            issues.append("analysis.json_repair_max_attempts must be >= 0")
        if not 0.0 < self.post_apply_regression_sample_ratio <= 1.0:
            issues.append("post_apply_regression.sample_ratio must be in (0.0, 1.0]")
        if self.canary_min_consecutive_correct < 1:
            issues.append("canary.min_consecutive_correct must be >= 1")
        if self.canary_max_count < 1:
            issues.append("canary.max_count must be >= 1")
        if self.max_restart_attempts < 1:
            issues.append("max_restart_attempts must be >= 1")
        if not 0.0 < self.patch_toxic_test_sample_ratio <= 1.0:
            issues.append("patch_toxic_test_sample_ratio must be in (0.0, 1.0]")
        return issues


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
    issues = config.validate()
    if issues:
        errors.extend(issues)
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


def _int_safe(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _float_safe(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        timeout=int(data.get("timeout", data.get("request_timeout", 120))),
        verify_ssl=_bool_value(data.get("verify_ssl", data.get("ssl_verify", True))),
        chat_template_kwargs=data.get("chat_template_kwargs"),
    )


def model_config_to_request_dict(config: ModelConfig) -> dict[str, Any]:
    request = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "timeout": config.timeout,
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
    patch_merge_strategy = str(patch_merge.get("strategy", "tree_reduce"))
    patch_repair = data.get("patch_repair", {}) or {}
    health = data.get("health", {}) or {}
    snapshots = data.get("snapshots", {}) or {}
    evaluation = data.get("evaluation", {}) or {}
    execution = data.get("execution", {}) or {}
    contribution = data.get("contribution", {}) or {}
    debug = data.get("debug", {}) or {}
    post_apply_regression = data.get("post_apply_regression", {}) or {}
    canary = data.get("canary", {}) or {}
    historical_regression = data.get("historical_regression", {}) or {}
    blind_eval = data.get("blind_evaluation", {}) or {}
    analysis_prompt_opt = data.get("analysis_prompt_optimization", {}) or {}
    models = data.get("models", {}) or {}
    extraction_model_data = data.get("extraction_model") or models.get("extraction") or {}
    optimizer_model_data = data.get("optimizer_model") or models.get("optimizer") or {}
    return OptimizerConfig(
        run_dir=data.get("run_dir", "runs"),
        batch_size=_int_safe(text.get("batch_size", data.get("batch_size", 24)), 24),
        dynamic_validation_batch_size=_int_safe(dval.get("batch_size", data.get("dynamic_validation_batch_size", 48)), 48),
        dynamic_validation_min_label_count=_int_safe(
            dval.get("min_label_count", data.get("dynamic_validation_min_label_count", 1)), 1
        ),
        dynamic_validation_cover_difficulty_bins=_bool_value(
            dval.get("cover_difficulty_bins", data.get("dynamic_validation_cover_difficulty_bins", True))
        ),
        dynamic_validation_recent_window_rounds=_int_safe(
            dval.get("recent_window_rounds", data.get("dynamic_validation_recent_window_rounds", 3)), 3
        ),
        dynamic_validation_max_recent_selections=_int_safe(
            dval.get("max_recent_selections", data.get("dynamic_validation_max_recent_selections", 1)), 1
        ),
        max_text_rounds=_int_safe(text.get("max_rounds", data.get("max_text_rounds", 10)), 10),
        extraction_line_budget=compression.get("extraction_line_budget", data.get("extraction_line_budget")),
        analysis_line_budget=compression.get("analysis_line_budget", data.get("analysis_line_budget")),
        extraction_token_budget=compression.get("extraction_token_budget", data.get("extraction_token_budget")),
        analysis_token_budget=compression.get("analysis_token_budget", data.get("analysis_token_budget")),
        fewshot_enabled=_bool_value(fewshot.get("enabled", data.get("fewshot_enabled", False))),
        fewshot_max_rounds=_int_safe(fewshot.get("max_rounds", data.get("fewshot_max_rounds", 5)), 5),
        fewshot_max_slots=_int_safe(fewshot.get("max_slots", data.get("fewshot_max_slots", 5)), 5),
        fewshot_min_accuracy_delta=_float_safe(fewshot.get("min_accuracy_delta", data.get("fewshot_min_accuracy_delta", 0.0)), 0.0),
        analysis_json_repair_enabled=_bool_value(analysis.get("json_repair_enabled", data.get("analysis_json_repair_enabled", False))),
        analysis_json_repair_max_attempts=_int_safe(analysis.get("json_repair_max_attempts", data.get("analysis_json_repair_max_attempts", 1)), 1),
        patch_semantic_merge_enabled=_bool_value(patch_merge.get("semantic_enabled", data.get("patch_semantic_merge_enabled", False))),
        patch_root_audit_enabled=_bool_value(patch_merge.get("root_audit_enabled", data.get("patch_root_audit_enabled", False))),
        llm_compression_enabled=_bool_value(compression.get("llm_enabled", data.get("llm_compression_enabled", False))),
        patch_repair_enabled=_bool_value(patch_repair.get("enabled", data.get("patch_repair_enabled", False))),
        patch_repair_max_attempts=_int_safe(patch_repair.get("max_attempts", data.get("patch_repair_max_attempts", 1)), 1),
        prompt_health_check_enabled=_bool_value(health.get("enabled", data.get("prompt_health_check_enabled", True))),
        prompt_snapshot_enabled=_bool_value(snapshots.get("enabled", data.get("prompt_snapshot_enabled", True))),
        eval_voting_enabled=_bool_value(evaluation.get("voting_enabled", data.get("eval_voting_enabled", True))),
        eval_vote_rounds=_int_safe(evaluation.get("vote_rounds", data.get("eval_vote_rounds", 3)), 3),
        execution_max_workers=_int_safe(execution.get("max_workers", data.get("execution_max_workers", 1)), 1),
        contribution_feedback_enabled=_bool_value(contribution.get("feedback_enabled", data.get("contribution_feedback_enabled", True))),
        debug_enabled=_bool_value(debug.get("enabled", data.get("debug_enabled", True))),
        post_apply_regression_enabled=_bool_value(post_apply_regression.get("enabled", data.get("post_apply_regression_enabled", True))),
        post_apply_regression_sample_ratio=_float_safe(post_apply_regression.get("sample_ratio", data.get("post_apply_regression_sample_ratio", 0.3)), 0.3),
        canary_protection_enabled=_bool_value(canary.get("protection_enabled", data.get("canary_protection_enabled", True))),
        canary_min_consecutive_correct=_int_safe(canary.get("min_consecutive_correct", data.get("canary_min_consecutive_correct", 3)), 3),
        canary_max_count=_int_safe(canary.get("max_count", data.get("canary_max_count", 10)), 10),
        historical_regression_check_enabled=_bool_value(historical_regression.get("enabled", data.get("historical_regression_check_enabled", True))),
        blind_evaluation_enabled=_bool_value(blind_eval.get("enabled", data.get("blind_evaluation_enabled", True))),
        blind_eval_three_analysis_vote_enabled=_bool_value(blind_eval.get("three_analysis_vote_enabled", data.get("blind_eval_three_analysis_vote_enabled", True))),
        max_restart_attempts=_int_safe(data.get("max_restart_attempts", 3), 3),
        analysis_prompt_optimization_enabled=_bool_value(analysis_prompt_opt.get("enabled", data.get("analysis_prompt_optimization_enabled", True))),
        analysis_patch_semantic_merge_enabled=_bool_value(analysis_prompt_opt.get("semantic_merge_enabled", data.get("analysis_patch_semantic_merge_enabled", True))),
        patch_toxic_test_sample_ratio=_float_safe(
            data.get("patch_toxic_test_sample_ratio", 0.5),
            0.5,
        ),
        scenario_id=data.get("scenario_id"),
        extraction_model=model_config_from_mapping(extraction_model_data),
        patch_merge_strategy=patch_merge_strategy,
        optimizer_model=model_config_from_mapping(optimizer_model_data),
    )
