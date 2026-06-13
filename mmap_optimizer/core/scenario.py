"""Scenario configuration loading for MMAP optimizer runs.

A scenario is a directory that follows this convention::

    scenarios/<scenario_id>/
      optimizer.yaml
      prompts/
      schemas/
      data/

The loader treats ``optimizer.yaml`` as the scenario-level override for the
optimizer defaults and records the content of prompts, schemas, and data files
so runs can be reproduced and identified by a stable configuration hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_OPTIMIZER_CONFIG: dict[str, Any] = {
    "model": {
        "name": "gpt-5.5",
        "temperature": 0.0,
    },
    "sampling": {
        "temperature": 0.0,
        "top_p": 1.0,
    },
    "compression": {
        "enabled": False,
    },
    "fewshot": {
        "enabled": False,
        "examples": [],
    },
    "patch_merge": {
        "strategy": "three_way",
    },
    "run_dir": "runs/default",
}

_CONFIG_FILE_NAMES = ("optimizer.yaml", "optimizer.yml", "optimizer.json")
_TEXT_SUFFIXES = {".txt", ".md", ".prompt", ".jinja", ".j2", ".tmpl"}
_STRUCTURED_SUFFIXES = {".json", ".yaml", ".yml"}


@dataclass(frozen=True)
class ScenarioConfig:
    """Loaded scenario configuration and resources.

    Attributes:
        scenario_id: Identifier derived from the scenario directory name.
        root: Absolute scenario directory path.
        optimizer_config: Optimizer defaults deep-merged with scenario overrides.
        optimizer_overrides: Raw values loaded from ``optimizer.yaml``.
        prompts: Prompt file contents keyed by path relative to ``prompts/``.
        schemas: Schema file contents keyed by path relative to ``schemas/``.
        data: Data file contents keyed by path relative to ``data/``.
        config_hash: Stable SHA-256 hash of scenario-owned config/resources.
    """

    scenario_id: str
    root: Path
    optimizer_config: dict[str, Any]
    optimizer_overrides: dict[str, Any]
    prompts: dict[str, Any] = field(default_factory=dict)
    schemas: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""

    @classmethod
    def load(
        cls,
        scenario_path: str | Path,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> "ScenarioConfig":
        """Load a scenario directory and compute its stable config hash."""

        root = Path(scenario_path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Scenario directory does not exist: {root}")
        if not root.is_dir():
            raise NotADirectoryError(f"Scenario path is not a directory: {root}")

        config_file = _find_optimizer_config(root)
        optimizer_overrides = _load_mapping(config_file)
        base_defaults = _deep_copy(defaults if defaults is not None else DEFAULT_OPTIMIZER_CONFIG)
        optimizer_config = _deep_merge(base_defaults, optimizer_overrides)

        prompts = _load_resource_directory(root / "prompts", required=False)
        schemas = _load_resource_directory(root / "schemas", required=True)
        data = _load_resource_directory(root / "data", required=False)

        hash_value = _scenario_hash(
            scenario_id=root.name,
            optimizer_overrides=optimizer_overrides,
            prompts=prompts,
            schemas=schemas,
            data=data,
        )

        return cls(
            scenario_id=root.name,
            root=root,
            optimizer_config=optimizer_config,
            optimizer_overrides=optimizer_overrides,
            prompts=prompts,
            schemas=schemas,
            data=data,
            config_hash=hash_value,
        )

    def with_run_dir(self, run_dir: str | Path | None) -> "ScenarioConfig":
        """Return a copy with a runtime ``run_dir`` override.

        The scenario hash is intentionally unchanged because ``run_dir`` is a
        runtime destination, not scenario-owned configuration.
        """

        if run_dir is None:
            return self
        updated = _deep_copy(self.optimizer_config)
        updated["run_dir"] = str(run_dir)
        return ScenarioConfig(
            scenario_id=self.scenario_id,
            root=self.root,
            optimizer_config=updated,
            optimizer_overrides=self.optimizer_overrides,
            prompts=self.prompts,
            schemas=self.schemas,
            data=self.data,
            config_hash=self.config_hash,
        )

    def artifact_metadata(self) -> dict[str, Any]:
        """Metadata that should be embedded into run artifacts."""

        return {
            "scenario_id": self.scenario_id,
            "scenario_config_hash": self.config_hash,
        }


def _find_optimizer_config(root: Path) -> Path:
    for file_name in _CONFIG_FILE_NAMES:
        candidate = root / file_name
        if candidate.is_file():
            return candidate
    expected = ", ".join(_CONFIG_FILE_NAMES)
    raise FileNotFoundError(f"Scenario {root} is missing optimizer config ({expected})")


def _load_mapping(path: Path) -> dict[str, Any]:
    value = _load_file(path)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}, got {type(value).__name__}")
    return value


def _load_resource_directory(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required scenario directory is missing: {path}")
        return {}
    if not path.is_dir():
        raise NotADirectoryError(f"Scenario resource path is not a directory: {path}")

    resources: dict[str, Any] = {}
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        relative = file_path.relative_to(path).as_posix()
        resources[relative] = _load_file(file_path)

    if required and not resources:
        raise FileNotFoundError(f"Required scenario directory has no schema files: {path}")
    return resources


def _load_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        return _load_yaml_subset(path.read_text(encoding="utf-8"), path)
    if suffix in _TEXT_SUFFIXES or suffix not in _STRUCTURED_SUFFIXES:
        return path.read_text(encoding="utf-8")
    return path.read_text(encoding="utf-8")


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = _deep_copy(value)
    return base


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True))


def _scenario_hash(
    *,
    scenario_id: str,
    optimizer_overrides: dict[str, Any],
    prompts: dict[str, Any],
    schemas: dict[str, Any],
    data: dict[str, Any],
) -> str:
    payload = {
        "scenario_id": scenario_id,
        "optimizer_overrides": optimizer_overrides,
        "prompts": prompts,
        "schemas": schemas,
        "data": data,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()



def _load_yaml_subset(text: str, path: Path) -> Any:
    """Parse the small YAML subset used by scenario configs.

    The project intentionally avoids requiring a YAML dependency for the core
    CLI path. This parser supports nested mappings, lists, strings, booleans,
    nulls, and numeric scalars, which covers the scenario configuration files.
    """

    lines = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        without_comment = raw_line.split("#", 1)[0].rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        if indent % 2:
            raise ValueError(f"Invalid YAML indentation in {path}:{line_number}")
        lines.append((indent, without_comment.strip(), line_number))

    if not lines:
        return None

    value, next_index = _parse_yaml_block(lines, 0, lines[0][0], path)
    if next_index != len(lines):
        _, _, line_number = lines[next_index]
        raise ValueError(f"Could not parse YAML near {path}:{line_number}")
    return value


def _parse_yaml_block(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
    path: Path,
) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index

    current_indent, content, _ = lines[index]
    if current_indent < indent:
        return {}, index
    if current_indent != indent:
        _, _, line_number = lines[index]
        raise ValueError(f"Unexpected YAML indentation in {path}:{line_number}")

    if content.startswith("- "):
        return _parse_yaml_list(lines, index, indent, path)
    return _parse_yaml_mapping(lines, index, indent, path)


def _parse_yaml_mapping(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
    path: Path,
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        current_indent, content, line_number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected nested YAML value in {path}:{line_number}")
        if content.startswith("- "):
            break
        key, separator, raw_value = content.partition(":")
        if not separator:
            raise ValueError(f"Expected YAML mapping entry in {path}:{line_number}")
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            mapping[key] = _parse_yaml_scalar(raw_value)
        elif index < len(lines) and lines[index][0] > indent:
            mapping[key], index = _parse_yaml_block(lines, index, lines[index][0], path)
        else:
            mapping[key] = {}
    return mapping, index


def _parse_yaml_list(
    lines: list[tuple[int, str, int]],
    index: int,
    indent: int,
    path: Path,
) -> tuple[list[Any], int]:
    values: list[Any] = []
    while index < len(lines):
        current_indent, content, line_number = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"Unexpected nested YAML list value in {path}:{line_number}")
        if not content.startswith("- "):
            break
        item = content[2:].strip()
        index += 1
        if not item:
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_yaml_block(lines, index, lines[index][0], path)
                values.append(value)
            else:
                values.append(None)
        elif ":" in item and not item.startswith(('"', "'")):
            key, _, raw_value = item.partition(":")
            item_mapping: dict[str, Any] = {}
            if raw_value.strip():
                item_mapping[key.strip()] = _parse_yaml_scalar(raw_value.strip())
            elif index < len(lines) and lines[index][0] > indent:
                item_mapping[key.strip()], index = _parse_yaml_block(lines, index, lines[index][0], path)
            else:
                item_mapping[key.strip()] = {}
            values.append(item_mapping)
        else:
            values.append(_parse_yaml_scalar(item))
    return values, index


def _parse_yaml_scalar(raw_value: str) -> Any:
    lowered = raw_value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    if raw_value.startswith(('"', "'")) and raw_value.endswith(('"', "'")):
        return raw_value[1:-1]
    if raw_value.startswith("[") or raw_value.startswith("{"):
        return json.loads(raw_value)
    if re.fullmatch(r"-?\d+", raw_value):
        return int(raw_value)
    if re.fullmatch(r"-?\d+\.\d+", raw_value):
        return float(raw_value)
    return raw_value
