"""Backward-compatible config exports.

Several feature branches imported ``mmap_optimizer.config`` directly.  Keep that
path working while the canonical implementation lives in ``mmap_optimizer.core``.
"""

from mmap_optimizer.core.config import (  # noqa: F401
    ExecutionConfig,
    ModelConfig,
    OptimizerConfig,
    execution_config_from_mapping,
    load_mapping,
    model_config_from_mapping,
    model_config_to_request_dict,
    optimizer_config_from_mapping,
    validate_optimizer_config_mapping,
)
