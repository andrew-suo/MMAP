"""Command line interface for MMAP optimizer utilities."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("configs/optimizer.yaml")
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
REQUIRED_OPENAI_COMPATIBLE_FIELDS = ("base_url", "model")


class ConfigValidationError(ValueError):
    """Raised when the optimizer configuration is invalid."""


def load_config(config_path: Path) -> dict[str, Any]:
    """Load a YAML optimizer configuration file."""

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    raw_config = config_path.read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:
        loaded = _load_simple_yaml(raw_config)
    else:
        loaded = yaml.safe_load(raw_config) or {}

    if not isinstance(loaded, dict):
        raise ConfigValidationError("Configuration root must be a mapping/object.")

    return loaded


def _load_simple_yaml(raw_config: str) -> dict[str, Any]:
    """Parse the small mapping-only YAML subset used by optimizer configs.

    PyYAML is preferred when installed. This fallback keeps the validation command
    usable in minimal environments for simple nested key/value configuration files.
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line_number, raw_line in enumerate(raw_config.splitlines(), start=1):
        without_comment = raw_line.split("#", 1)[0].rstrip()
        if not without_comment.strip():
            continue

        indent = len(without_comment) - len(without_comment.lstrip(" "))
        stripped = without_comment.strip()
        if ":" not in stripped:
            raise ConfigValidationError(f"Invalid YAML line {line_number}: {raw_line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ConfigValidationError(f"Invalid YAML line {line_number}: empty key")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigValidationError(f"Invalid YAML indentation on line {line_number}")

        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_simple_yaml_scalar(value)

    return root


def _parse_simple_yaml_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def validate_model_config(config: dict[str, Any], model_path: str) -> list[str]:
    """Validate one model block and return human-readable error messages."""

    current: Any = config
    for part in model_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return [f"{model_path} is required."]
        current = current[part]

    if not isinstance(current, dict):
        return [f"{model_path} must be a mapping/object."]

    provider = current.get("provider")
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        return []

    errors: list[str] = []
    for field in REQUIRED_OPENAI_COMPATIBLE_FIELDS:
        if not current.get(field):
            errors.append(
                f"{model_path}.{field} is required when provider is "
                f"{OPENAI_COMPATIBLE_PROVIDER}."
            )

    if not (current.get("api_key_env") or current.get("api_key")):
        errors.append(
            f"{model_path}.api_key_env or {model_path}.api_key is required when "
            f"provider is {OPENAI_COMPATIBLE_PROVIDER}."
        )

    return errors


def validate_config(config: dict[str, Any]) -> None:
    """Validate the optimizer configuration.

    Raises:
        ConfigValidationError: if any validation rule fails.
    """

    errors = []
    errors.extend(validate_model_config(config, "models.extraction"))
    errors.extend(validate_model_config(config, "models.optimizer"))

    if errors:
        raise ConfigValidationError("\n".join(errors))


def _optimizer_model_config(config: dict[str, Any]) -> dict[str, Any]:
    models = config.get("models", {})
    if not isinstance(models, dict):
        raise ConfigValidationError("models must be a mapping/object.")
    optimizer = models.get("optimizer", {})
    if not isinstance(optimizer, dict):
        raise ConfigValidationError("models.optimizer must be a mapping/object.")
    return optimizer


def dry_run_optimizer_model_call(config: dict[str, Any]) -> None:
    """Send a tiny text-only request to the configured optimizer model."""

    optimizer = _optimizer_model_config(config)
    provider = optimizer.get("provider")
    if provider != OPENAI_COMPATIBLE_PROVIDER:
        print(
            "Dry-run model call skipped: models.optimizer.provider is "
            f"{provider!r}, not {OPENAI_COMPATIBLE_PROVIDER!r}."
        )
        return

    api_key = optimizer.get("api_key")
    api_key_env = optimizer.get("api_key_env")
    if not api_key and api_key_env:
        api_key = os.environ.get(str(api_key_env))
    if not api_key:
        raise ConfigValidationError(
            "Dry-run model call requires an API key value. Set the environment "
            f"variable named by models.optimizer.api_key_env ({api_key_env!r}) "
            "or provide models.optimizer.api_key."
        )

    base_url = str(optimizer["base_url"]).rstrip("/")
    endpoint = base_url
    if not endpoint.endswith("/chat/completions"):
        endpoint = f"{endpoint}/chat/completions"

    payload = {
        "model": optimizer["model"],
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Dry-run model call failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Dry-run model call failed: {exc.reason}") from exc

    print("Dry-run optimizer model call succeeded.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser(
        "validate-config",
        help="Validate optimizer model configuration without running optimization.",
    )
    validate_parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to optimizer YAML config (default: {DEFAULT_CONFIG_PATH}).",
    )
    validate_parser.add_argument(
        "--dry-run-model-call",
        action="store_true",
        help=(
            "After validation, send a tiny text-only request to the optimizer "
            "model without reading images or running optimization."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-config":
        try:
            config = load_config(args.config)
            validate_config(config)
            print(f"Configuration is valid: {args.config}")
            if args.dry_run_model_call:
                dry_run_optimizer_model_call(config)
        except (ConfigValidationError, FileNotFoundError, RuntimeError) as exc:
            print(f"Configuration validation failed: {exc}", file=sys.stderr)
            return 1
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
