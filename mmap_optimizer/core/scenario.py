from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from mmap_optimizer.core.config import OptimizerConfig, load_mapping, optimizer_config_from_mapping
from mmap_optimizer.core.hashing import sha256_text

DEFAULT_SCENARIOS_DIR = "scenarios"
DEFAULT_OPTIMIZER_CONFIG_NAMES = ("optimizer.yaml", "optimizer.yml", "optimizer.json")
STANDARD_SCENARIO_DIRS = ("data", "prompts", "schemas")


class ScenarioError(ValueError):
    """Base class for scenario loading and validation failures."""


class ScenarioValidationError(ScenarioError):
    """Raised when a scenario directory does not satisfy the scenario contract."""


@dataclass(frozen=True)
class ScenarioManifest:
    """Parsed scenario manifest metadata."""

    id: str
    description: str = ""
    task_type: str = ""
    optimizer_config: str = "optimizer.yaml"
    data_dir: str = "data"
    prompts_dir: str = "prompts"
    schemas_dir: str = "schemas"
    schema_paths: tuple[str, ...] = ()
    default_config: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioSummary:
    """Compact scenario listing entry."""

    id: str
    description: str
    task_type: str
    path: Path


@dataclass
class ScenarioConfig:
    """Loaded scenario with resolved paths, config, and stable metadata."""

    id: str
    root: Path
    optimizer_config: OptimizerConfig
    config_hash: str
    data_dir: Path
    prompts_dir: Path
    schemas_dir: Path
    optimizer_config_path: Path | None = None
    manifest: dict[str, object] = field(default_factory=dict)
    config_mapping: dict[str, Any] = field(default_factory=dict)
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    schema_hashes: dict[str, str] = field(default_factory=dict)
    data_hashes: dict[str, str] = field(default_factory=dict)
    description: str = ""
    task_type: str = ""
    schema_paths: tuple[str, ...] = ()

    @property
    def scenario_id(self) -> str:
        return self.id

    def artifact_metadata(self) -> dict[str, Any]:
        return run_artifact_metadata(self)


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(data: Any) -> str:
    return sha256(stable_json(data).encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_file_hashes(root: str | Path) -> dict[str, str]:
    root = Path(root)
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` without mutating either."""

    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        old_value = merged.get(key)
        if isinstance(old_value, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(old_value, value)
        else:
            merged[key] = value
    return merged


def _coerce_str_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(str(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(str(item) for item in value)
    raise ScenarioValidationError(f"scenario.yaml field {field_name!r} must be a string, list, or mapping")


def _safe_relative(root: Path, relative_path: str, field_name: str) -> Path:
    path = root / relative_path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ScenarioValidationError(f"Scenario {field_name} escapes scenario directory: {relative_path}") from exc
    return path


def resolve_scenario_root(scenario: str | Path, scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR) -> Path:
    candidate = Path(scenario)
    if candidate.exists() or candidate.is_absolute() or len(candidate.parts) > 1:
        return candidate
    return Path(scenarios_dir) / str(scenario)


def _find_optimizer_config(root: Path, manifest: ScenarioManifest | None = None) -> str:
    if manifest is not None and manifest.optimizer_config:
        return manifest.optimizer_config
    for name in DEFAULT_OPTIMIZER_CONFIG_NAMES:
        if (root / name).is_file():
            return name
    return "optimizer.yaml"


def _read_block_list(text: str, key: str) -> tuple[str, ...]:
    values: list[str] = []
    lines = text.splitlines()
    for index, raw_line in enumerate(lines):
        if raw_line.strip().startswith(f"{key}:"):
            base_indent = len(raw_line) - len(raw_line.lstrip(" "))
            for child in lines[index + 1 :]:
                stripped = child.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                indent = len(child) - len(child.lstrip(" "))
                if indent <= base_indent:
                    break
                if stripped.startswith("- "):
                    values.append(stripped[2:].strip().strip("\"'"))
            break
    return tuple(values)


def read_manifest(scenario_root: str | Path) -> ScenarioManifest:
    root = Path(scenario_root)
    manifest_path = root / "scenario.yaml"
    manifest_text = ""
    if manifest_path.exists():
        manifest_text = manifest_path.read_text(encoding="utf-8")
        data = load_mapping(manifest_path)
        if not isinstance(data, Mapping):
            raise ScenarioValidationError(f"{manifest_path} must contain a mapping")
    else:
        data = {"id": root.name}

    schema_value = data.get("schema_paths", data.get("schemas"))
    if not schema_value and manifest_text:
        schema_value = _read_block_list(manifest_text, "schema_paths") or _read_block_list(manifest_text, "schemas")
    default_config = data.get("default_config", {}) or {}
    if not isinstance(default_config, Mapping):
        raise ScenarioValidationError("scenario.yaml field 'default_config' must be a mapping")

    return ScenarioManifest(
        id=str(data.get("id") or root.name),
        description=str(data.get("description", "")),
        task_type=str(data.get("task_type", "")),
        optimizer_config=str(data.get("optimizer_config", data.get("config", "optimizer.yaml"))),
        data_dir=str(data.get("data_dir", "data")),
        prompts_dir=str(data.get("prompts_dir", "prompts")),
        schemas_dir=str(data.get("schemas_dir", "schemas")),
        schema_paths=_coerce_str_list(schema_value, "schema_paths"),
        default_config=dict(default_config),
        raw=dict(data),
    )


def validate_scenario(
    scenario: str | Path,
    scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR,
    *,
    require_resources: bool = True,
) -> ScenarioManifest:
    root = resolve_scenario_root(scenario, scenarios_dir)
    if not root.exists():
        raise ScenarioValidationError(f"Scenario directory does not exist: {root}")
    if not root.is_dir():
        raise ScenarioValidationError(f"Scenario path is not a directory: {root}")

    manifest = read_manifest(root)
    if root.name != manifest.id:
        raise ScenarioValidationError(
            f"scenario.yaml id {manifest.id!r} must match scenario directory name {root.name!r}"
        )

    config_path = _safe_relative(root, _find_optimizer_config(root, manifest), "optimizer_config")
    if not config_path.is_file():
        raise ScenarioValidationError(f"Scenario optimizer config not found: {config_path}")
    if not require_resources:
        return manifest

    for attr_name in STANDARD_SCENARIO_DIRS:
        relative = getattr(manifest, f"{attr_name}_dir", attr_name) if attr_name != "data" else manifest.data_dir
        directory = _safe_relative(root, str(relative), f"{attr_name}_dir")
        if not directory.is_dir():
            raise ScenarioValidationError(f"Scenario {attr_name} directory not found: {directory}")

    schema_paths = manifest.schema_paths or tuple(
        (Path(manifest.schemas_dir) / path.name).as_posix()
        for path in sorted((root / manifest.schemas_dir).glob("*.json"))
    )
    if not schema_paths:
        raise ScenarioValidationError("Scenario must declare schema_paths or include schema files")
    for schema_path in schema_paths:
        full_path = _safe_relative(root, schema_path, "schema_paths")
        if not full_path.is_file():
            raise ScenarioValidationError(f"Manifest schema path does not exist: {schema_path}")
    return manifest


def load_scenario(
    scenario: str | Path,
    scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR,
    base_config_path: str | Path | None = None,
) -> ScenarioConfig:
    root = resolve_scenario_root(scenario, scenarios_dir)
    manifest = validate_scenario(root, scenarios_dir=scenarios_dir, require_resources=False)
    config_path = _safe_relative(root, _find_optimizer_config(root, manifest), "optimizer_config")
    scenario_mapping = load_mapping(config_path)
    if not isinstance(scenario_mapping, Mapping):
        raise ScenarioValidationError(f"Scenario config must be a mapping: {config_path}")

    base_mapping: Mapping[str, Any] = {}
    base_path = Path(base_config_path) if base_config_path is not None else None
    if base_path is not None and base_path.exists():
        loaded_base = load_mapping(base_path)
        if not isinstance(loaded_base, Mapping):
            raise ScenarioValidationError(f"Base config must be a mapping: {base_path}")
        base_mapping = loaded_base

    merged_mapping = deep_merge(base_mapping, scenario_mapping)
    merged_mapping = deep_merge(merged_mapping, manifest.default_config)
    merged_mapping.setdefault("scenario_id", manifest.id)
    raw_config = stable_json(merged_mapping)
    config = optimizer_config_from_mapping(dict(merged_mapping))
    config.scenario_id = manifest.id

    data_dir = _safe_relative(root, manifest.data_dir, "data_dir")
    prompts_dir = _safe_relative(root, manifest.prompts_dir, "prompts_dir")
    schemas_dir = _safe_relative(root, manifest.schemas_dir, "schemas_dir")
    schema_paths = manifest.schema_paths or tuple(
        (Path(manifest.schemas_dir) / path.name).as_posix() for path in sorted(schemas_dir.glob("*.json"))
    )
    return ScenarioConfig(
        id=manifest.id,
        root=root,
        optimizer_config=config,
        config_hash=sha256_text(raw_config),
        data_dir=data_dir,
        prompts_dir=prompts_dir,
        schemas_dir=schemas_dir,
        optimizer_config_path=config_path,
        manifest=dict(manifest.raw),
        config_mapping=dict(merged_mapping),
        prompt_hashes=directory_file_hashes(prompts_dir),
        schema_hashes={path: file_hash(root / path) for path in sorted(schema_paths)},
        data_hashes=directory_file_hashes(data_dir),
        description=manifest.description,
        task_type=manifest.task_type,
        schema_paths=tuple(schema_paths),
    )


def list_scenarios(scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR) -> list[ScenarioSummary]:
    root = Path(scenarios_dir)
    if not root.exists():
        return []
    summaries: list[ScenarioSummary] = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            manifest = validate_scenario(child, scenarios_dir=root)
        except ScenarioValidationError:
            continue
        summaries.append(
            ScenarioSummary(
                id=manifest.id,
                description=manifest.description,
                task_type=manifest.task_type,
                path=child,
            )
        )
    return sorted(summaries, key=lambda item: item.id)


def summaries_as_dicts(summaries: Iterable[ScenarioSummary]) -> list[dict[str, str]]:
    return [
        {
            "id": summary.id,
            "description": summary.description,
            "task_type": summary.task_type,
            "path": str(summary.path),
        }
        for summary in summaries
    ]


def run_artifact_metadata(scenario: ScenarioConfig) -> dict[str, Any]:
    return {
        "scenario_id": scenario.id,
        "scenario_config_hash": scenario.config_hash,
        "prompt_hashes": dict(sorted(scenario.prompt_hashes.items())),
        "schema_hashes": dict(sorted(scenario.schema_hashes.items())),
        "data_hashes": dict(sorted(scenario.data_hashes.items())),
    }


def write_scenario_artifact_metadata(artifact_dir: str | Path, scenario: ScenarioConfig) -> Path:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "scenario_artifacts.json"
    artifact_path.write_text(
        json.dumps(run_artifact_metadata(scenario), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_path


write_run_artifacts = write_scenario_artifact_metadata
