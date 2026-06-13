"""Scenario discovery, validation, configuration, and artifact helpers.

A scenario is stored in the standard layout::

    scenarios/<scenario_id>/
      scenario.yaml
      optimizer.yaml
      data/
      prompts/
      schemas/
      README.md

``scenario.yaml`` is the manifest. It must contain ``id``, ``description``,
``task_type``, schema path information, and optional ``default_config`` values.
Scenario configuration is built by loading ``configs/optimizer.yaml`` first and
then recursively overlaying the scenario's ``optimizer.yaml`` and manifest
``default_config`` values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:  # Prefer PyYAML when available, but keep the package dependency-free.
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover - exercised when PyYAML is absent.
    _yaml = None

STANDARD_SCENARIO_FILES: tuple[str, ...] = (
    "scenario.yaml",
    "optimizer.yaml",
    "README.md",
)
STANDARD_SCENARIO_DIRS: tuple[str, ...] = ("data", "prompts", "schemas")
STANDARD_SCENARIO_ENTRIES: tuple[str, ...] = STANDARD_SCENARIO_FILES + STANDARD_SCENARIO_DIRS
DEFAULT_SCENARIOS_DIR = "scenarios"
DEFAULT_BASE_CONFIG_PATH = "configs/optimizer.yaml"


class ScenarioError(ValueError):
    """Base class for scenario validation and loading failures."""


class ScenarioValidationError(ScenarioError):
    """Raised when a scenario does not satisfy the standard contract."""


@dataclass(frozen=True)
class ScenarioManifest:
    """Parsed ``scenario.yaml`` manifest."""

    id: str
    description: str
    task_type: str
    schema_paths: tuple[str, ...]
    default_config: Mapping[str, Any] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    """A validated scenario with resolved configuration and stable hashes."""

    root: Path
    manifest: ScenarioManifest
    config: Mapping[str, Any]
    config_hash: str
    prompt_hashes: Mapping[str, str]
    schema_hashes: Mapping[str, str]

    @property
    def id(self) -> str:
        return self.manifest.id


@dataclass(frozen=True)
class ScenarioSummary:
    """Small object returned by ``list_scenarios``."""

    id: str
    description: str
    task_type: str
    path: Path


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    lowered = value.lower()
    if lowered in {"null", "~", "none"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        try:
            return ast.literal_eval(value)
        except Exception:
            return value[1:-1]
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except Exception:
            try:
                return ast.literal_eval(value)
            except Exception:
                return value
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def _minimal_yaml_load(text: str) -> Any:
    """Parse the small YAML subset used by project configs/manifests.

    The fallback supports nested mappings, block lists, inline JSON/Python-style
    lists/maps, strings, booleans, numbers, and null values. It intentionally
    avoids advanced YAML features such as anchors and multi-document streams.
    """

    prepared: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = _strip_yaml_comment(raw_line).rstrip()
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip("\t "))]:
            raise ScenarioValidationError("YAML indentation must use spaces, not tabs")
        prepared.append((len(line) - len(line.lstrip(" ")), line.strip()))

    if not prepared:
        return {}

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(prepared):
            return {}, index
        is_list = prepared[index][0] == indent and prepared[index][1].startswith("- ")
        if is_list:
            result: list[Any] = []
            while index < len(prepared):
                current_indent, content = prepared[index]
                if current_indent < indent:
                    break
                if current_indent != indent or not content.startswith("- "):
                    break
                item = content[2:].strip()
                index += 1
                if item == "":
                    value, index = parse_block(index, indent + 2)
                    result.append(value)
                elif ":" in item and not item.startswith(('"', "'")):
                    key, raw_value = item.split(":", 1)
                    mapping: dict[str, Any] = {}
                    if raw_value.strip():
                        mapping[key.strip()] = _parse_scalar(raw_value.strip())
                    else:
                        value, index = parse_block(index, indent + 2)
                        mapping[key.strip()] = value
                    while index < len(prepared) and prepared[index][0] == indent + 2:
                        nested_key, nested_value = prepared[index][1].split(":", 1)
                        index += 1
                        if nested_value.strip():
                            mapping[nested_key.strip()] = _parse_scalar(nested_value.strip())
                        else:
                            value, index = parse_block(index, indent + 4)
                            mapping[nested_key.strip()] = value
                    result.append(mapping)
                else:
                    result.append(_parse_scalar(item))
            return result, index

        result: dict[str, Any] = {}
        while index < len(prepared):
            current_indent, content = prepared[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ScenarioValidationError(f"Unexpected indentation near: {content!r}")
            if content.startswith("- "):
                break
            if ":" not in content:
                raise ScenarioValidationError(f"Expected key/value pair near: {content!r}")
            key, raw_value = content.split(":", 1)
            key = key.strip()
            index += 1
            if raw_value.strip():
                result[key] = _parse_scalar(raw_value.strip())
            else:
                value, index = parse_block(index, indent + 2)
                result[key] = value
        return result, index

    parsed, final_index = parse_block(0, prepared[0][0])
    if final_index != len(prepared):
        raise ScenarioValidationError("Could not parse complete YAML document")
    return parsed


def load_yaml(path: str | Path) -> Any:
    """Load YAML from ``path`` with a dependency-free fallback parser."""

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScenarioValidationError(f"Required file is missing: {path}") from exc
    if _yaml is not None:
        loaded = _yaml.safe_load(text)
        return {} if loaded is None else loaded
    return _minimal_yaml_load(text)


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


def stable_json(data: Any) -> str:
    """Return canonical JSON used for stable hashing."""

    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(data: Any) -> str:
    """Return a stable SHA-256 hash for structured data."""

    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    """Return the SHA-256 hash of a file's bytes."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_file_hashes(root: str | Path) -> dict[str, str]:
    """Hash every regular file under ``root`` keyed by POSIX relative path."""

    root = Path(root)
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): file_hash(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _coerce_str_list(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        coerced = tuple(str(item) for item in value.values())
        if coerced:
            return coerced
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        coerced = tuple(str(item) for item in value)
        if coerced:
            return coerced
    raise ScenarioValidationError(
        f"scenario.yaml field {field_name!r} must be a non-empty string, list, or mapping"
    )


def read_manifest(scenario_root: str | Path) -> ScenarioManifest:
    """Read and validate the manifest file for a scenario directory."""

    scenario_root = Path(scenario_root)
    manifest_path = scenario_root / "scenario.yaml"
    data = load_yaml(manifest_path)
    if not isinstance(data, Mapping):
        raise ScenarioValidationError(f"{manifest_path} must contain a mapping")

    missing = [field for field in ("id", "description", "task_type") if not data.get(field)]
    if missing:
        raise ScenarioValidationError(f"{manifest_path} is missing required field(s): {', '.join(missing)}")

    schema_value = data.get("schema_paths", data.get("schemas"))
    if schema_value is None:
        raise ScenarioValidationError(f"{manifest_path} is missing required field: schema_paths")
    schema_paths = _coerce_str_list(schema_value, "schema_paths")
    default_config = data.get("default_config", {})
    if default_config is None:
        default_config = {}
    if not isinstance(default_config, Mapping):
        raise ScenarioValidationError("scenario.yaml field 'default_config' must be a mapping")

    return ScenarioManifest(
        id=str(data["id"]),
        description=str(data["description"]),
        task_type=str(data["task_type"]),
        schema_paths=schema_paths,
        default_config=dict(default_config),
        raw=dict(data),
    )


def resolve_scenario_root(
    scenario: str | Path, scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR
) -> Path:
    """Resolve either a scenario id or an explicit scenario directory path."""

    candidate = Path(scenario)
    if candidate.exists() or candidate.parts and len(candidate.parts) > 1:
        return candidate
    return Path(scenarios_dir) / str(scenario)


def validate_scenario(
    scenario: str | Path,
    scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR,
) -> ScenarioManifest:
    """Validate a scenario directory and return its parsed manifest.

    Validation checks the standard entries, manifest id/path consistency, and all
    manifest-declared schema paths.
    """

    root = resolve_scenario_root(scenario, scenarios_dir)
    if not root.exists():
        raise ScenarioValidationError(f"Scenario directory does not exist: {root}")
    if not root.is_dir():
        raise ScenarioValidationError(f"Scenario path is not a directory: {root}")

    missing: list[str] = []
    for name in STANDARD_SCENARIO_FILES:
        if not (root / name).is_file():
            missing.append(name)
    for name in STANDARD_SCENARIO_DIRS:
        if not (root / name).is_dir():
            missing.append(name + "/")
    if missing:
        raise ScenarioValidationError(
            f"Scenario {root} is missing required standard entr{'y' if len(missing) == 1 else 'ies'}: "
            + ", ".join(missing)
        )

    manifest = read_manifest(root)
    if root.name != manifest.id:
        raise ScenarioValidationError(
            f"scenario.yaml id {manifest.id!r} must match scenario directory name {root.name!r}"
        )

    for schema_path in manifest.schema_paths:
        full_path = root / schema_path
        try:
            full_path.relative_to(root)
        except ValueError as exc:
            raise ScenarioValidationError(f"Schema path escapes scenario directory: {schema_path}") from exc
        if not full_path.is_file():
            raise ScenarioValidationError(f"Manifest schema path does not exist: {schema_path}")
    return manifest


def load_scenario(
    scenario: str | Path,
    scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR,
    base_config_path: str | Path = DEFAULT_BASE_CONFIG_PATH,
) -> Scenario:
    """Validate and load a scenario, applying base config inheritance."""

    root = resolve_scenario_root(scenario, scenarios_dir)
    manifest = validate_scenario(root, scenarios_dir=scenarios_dir)

    base_path = Path(base_config_path)
    base_config = load_yaml(base_path) if base_path.exists() else {}
    scenario_config = load_yaml(root / "optimizer.yaml")
    if not isinstance(base_config, Mapping):
        raise ScenarioValidationError(f"Base config must be a mapping: {base_path}")
    if not isinstance(scenario_config, Mapping):
        raise ScenarioValidationError(f"Scenario config must be a mapping: {root / 'optimizer.yaml'}")

    merged = deep_merge(base_config, scenario_config)
    merged = deep_merge(merged, manifest.default_config)

    return Scenario(
        root=root,
        manifest=manifest,
        config=merged,
        config_hash=stable_hash(merged),
        prompt_hashes=directory_file_hashes(root / "prompts"),
        schema_hashes={path: file_hash(root / path) for path in sorted(manifest.schema_paths)},
    )


def list_scenarios(scenarios_dir: str | Path = DEFAULT_SCENARIOS_DIR) -> list[ScenarioSummary]:
    """List valid scenarios under ``scenarios_dir`` sorted by id.

    Invalid children are skipped here so the command remains useful while a new
    scenario is being authored; use ``validate_scenario`` for strict diagnostics.
    """

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


def run_artifact_metadata(scenario: Scenario) -> dict[str, Any]:
    """Build the scenario metadata that should be persisted with run artifacts."""

    return {
        "scenario_id": scenario.id,
        "scenario_config_hash": scenario.config_hash,
        "prompt_hashes": dict(sorted(scenario.prompt_hashes.items())),
        "schema_hashes": dict(sorted(scenario.schema_hashes.items())),
    }


def write_run_artifacts(artifact_dir: str | Path, scenario: Scenario) -> Path:
    """Write scenario run metadata to ``scenario_artifacts.json``.

    Returns the created file path so callers can include it in larger run
    manifests.
    """

    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "scenario_artifacts.json"
    artifact_path.write_text(
        json.dumps(run_artifact_metadata(scenario), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_path


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
