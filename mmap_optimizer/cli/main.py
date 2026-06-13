"""Command-line entry point for the MMAP optimizer."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request

from mmap_optimizer.config import OptimizerConfig, optimizer_config_from_mapping


class ConfigValidationError(ValueError):
    """Raised when an optimizer config fails CLI validation."""


def _load_config(path: Path) -> Mapping[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix == ".json":
        data = json.loads(raw)
    elif suffix == ".toml":
        data = tomllib.loads(raw)
    elif suffix in {".yaml", ".yml"}:
        data = _load_yaml(raw)
    else:
        data = _load_config_without_suffix(raw)

    if not isinstance(data, Mapping):
        raise ConfigValidationError("config file must contain a mapping/object")
    return data


def _load_yaml(raw: str) -> Any:
    if importlib.util.find_spec("yaml") is None:  # pragma: no cover - depends on environment
        raise ConfigValidationError(
            "YAML config files require PyYAML; use JSON/TOML or install PyYAML."
        )

    import yaml

    return yaml.safe_load(raw)


def _load_config_without_suffix(raw: str) -> Mapping[str, Any]:
    loaders = (json.loads, tomllib.loads)
    last_error: Exception | None = None
    for loader in loaders:
        try:
            data = loader(raw)
            if isinstance(data, Mapping):
                return data
        except Exception as exc:  # noqa: BLE001 - collect parse attempts
            last_error = exc

    if importlib.util.find_spec("yaml") is not None:
        try:
            data = _load_yaml(raw)
            if isinstance(data, Mapping):
                return data
        except Exception as exc:  # noqa: BLE001 - report a concise config error
            last_error = exc

    raise ConfigValidationError(f"could not parse config file: {last_error}")


def _validate_optimizer_config(config: OptimizerConfig) -> None:
    model_config = config.optimizer_model

    if model_config.provider == "openai_compatible" and not model_config.base_url:
        raise ConfigValidationError("provider=openai_compatible requires base_url")

    if not model_config.model:
        raise ConfigValidationError("optimizer model config requires model")

    if not model_config.api_key and not model_config.api_key_env:
        raise ConfigValidationError("optimizer model config requires api_key or api_key_env")

    if model_config.api_key_env and not os.environ.get(model_config.api_key_env):
        raise ConfigValidationError(
            f"api_key_env {model_config.api_key_env!r} is not set in the environment"
        )


def _api_key_for_config(config: OptimizerConfig) -> str:
    model_config = config.optimizer_model
    if model_config.api_key:
        return model_config.api_key
    if model_config.api_key_env:
        return os.environ[model_config.api_key_env]
    raise ConfigValidationError("optimizer model config requires api_key or api_key_env")


def _dry_run_model_call(config: OptimizerConfig) -> None:
    model_config = config.optimizer_model

    if model_config.provider == "mock":
        return

    if model_config.provider not in {"openai", "openai_compatible"}:
        raise ConfigValidationError(
            f"--dry-run-model-call is not implemented for provider={model_config.provider}"
        )

    base_url = model_config.base_url or "https://api.openai.com/v1"
    endpoint = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": model_config.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
    ).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {_api_key_for_config(config)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=30) as response:  # noqa: S310
            if response.status >= 400:
                raise ConfigValidationError(
                    f"dry-run model call failed with HTTP {response.status}"
                )
            response.read(1024)
    except error.HTTPError as exc:
        detail = exc.read(1024).decode("utf-8", errors="replace")
        raise ConfigValidationError(
            f"dry-run model call failed with HTTP {exc.code}: {detail}"
        ) from exc
    except error.URLError as exc:
        raise ConfigValidationError(f"dry-run model call failed: {exc.reason}") from exc


def _handle_validate_config(args: argparse.Namespace) -> int:
    try:
        raw_config = _load_config(Path(args.config))
        config = optimizer_config_from_mapping(raw_config)
        _validate_optimizer_config(config)
        if args.dry_run_model_call:
            _dry_run_model_call(config)
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError, ConfigValidationError, TypeError) as exc:
        print(f"Config validation failed: {exc}", file=sys.stderr)
        return 1

    print("Config validation succeeded")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_config = subparsers.add_parser(
        "validate-config", help="Validate optimizer model configuration"
    )
    validate_config.add_argument("--config", required=True, help="Path to config file")
    validate_config.add_argument(
        "--dry-run-model-call",
        action="store_true",
        help="Send a tiny text-only request to the optimizer model after validation",
    )
    validate_config.set_defaults(func=_handle_validate_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
