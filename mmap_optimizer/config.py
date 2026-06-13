"""Configuration helpers for the MMAP optimizer CLI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class OptimizerModelConfig:
    """Connection settings for the optimizer language model."""

    provider: str = "openai"
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None


@dataclass(frozen=True)
class OptimizerConfig:
    """Top-level optimizer configuration used by CLI commands."""

    optimizer_model: OptimizerModelConfig


def _first_mapping(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Mapping[str, Any] | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def optimizer_config_from_mapping(mapping: Mapping[str, Any]) -> OptimizerConfig:
    """Build an :class:`OptimizerConfig` from a raw config mapping.

    The CLI accepts either a flat model mapping or a nested mapping using one of
    the common keys below. This makes validation useful for small examples while
    remaining compatible with full optimizer config files.
    """

    if not isinstance(mapping, Mapping):
        raise TypeError("optimizer config must be a mapping")

    model_mapping = _first_mapping(
        mapping,
        (
            "optimizer_model",
            "optimizer_model_config",
            "model_config",
            "model",
            "optimizer",
        ),
    )
    raw_model = model_mapping if model_mapping is not None else mapping

    provider = str(raw_model.get("provider", "openai"))
    model_value = raw_model.get("model") or raw_model.get("model_name")
    api_key_value = raw_model.get("api_key")
    api_key_env_value = raw_model.get("api_key_env")
    base_url_value = raw_model.get("base_url")

    return OptimizerConfig(
        optimizer_model=OptimizerModelConfig(
            provider=provider,
            model=str(model_value) if model_value is not None else None,
            api_key=str(api_key_value) if api_key_value is not None else None,
            api_key_env=str(api_key_env_value) if api_key_env_value is not None else None,
            base_url=str(base_url_value) if base_url_value is not None else None,
        )
    )
