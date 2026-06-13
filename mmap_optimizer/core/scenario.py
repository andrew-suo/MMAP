from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mmap_optimizer.core.config import OptimizerConfig, load_mapping, optimizer_config_from_mapping
from mmap_optimizer.core.hashing import sha256_json, sha256_text


class ScenarioValidationError(Exception):
    """Raised when scenario validation fails."""
    pass


STANDARD_SCENARIO_FILES = ("scenario.yaml", "optimizer.yaml", "README.md")
STANDARD_SCENARIO_DIRS = ("data", "prompts", "schemas")
DEFAULT_SCENARIOS_DIR = "scenarios"
DEFAULT_BASE_CONFIG_PATH = "configs/optimizer.yaml"


@dataclass
class ScenarioConfig:
    id: str
    root: Path
    optimizer_config: OptimizerConfig
    config_hash: str
    data_dir: Path
    prompts_dir: Path
    schemas_dir: Path
    manifest: dict[str, object] = field(default_factory=dict)


def load_scenario(path: str | Path) -> ScenarioConfig:
    root = Path(path)
    manifest_path = root / "scenario.yaml"
    manifest = load_mapping(manifest_path) if manifest_path.exists() else {}
    config_name = str(manifest.get("optimizer_config", "optimizer.yaml"))
    config_path = root / config_name
    if not config_path.exists():
        raise FileNotFoundError(f"Scenario optimizer config not found: {config_path}")
    raw = config_path.read_text(encoding="utf-8")
    config = optimizer_config_from_mapping(load_mapping(config_path))
    return ScenarioConfig(
        id=root.name,
        root=root,
        optimizer_config=config,
        config_hash=sha256_text(raw),
        data_dir=root / str(manifest.get("data_dir", "data")),
        prompts_dir=root / str(manifest.get("prompts_dir", "prompts")),
        schemas_dir=root / str(manifest.get("schemas_dir", "schemas")),
        manifest=manifest,
    )


def validate_scenario(scenario: str | Path, scenarios_dir: str | Path | None = None) -> ScenarioConfig:
    """Validate a scenario directory structure and manifest fields, then return ScenarioConfig via load_scenario.

    Args:
        scenario: Path to the scenario directory or scenario ID
        scenarios_dir: Base directory containing all scenarios (optional)

    Returns:
        ScenarioConfig loaded from the scenario

    Raises:
        ScenarioValidationError: If validation fails
    """
    scenario_path = Path(scenario)
    if scenarios_dir is not None and not scenario_path.is_absolute():
        scenarios_dir_path = Path(scenarios_dir)
        scenario_path = scenarios_dir_path / scenario

    if not scenario_path.exists():
        raise ScenarioValidationError(f"Scenario directory does not exist: {scenario_path}")

    if not scenario_path.is_dir():
        raise ScenarioValidationError(f"Scenario path is not a directory: {scenario_path}")

    for filename in STANDARD_SCENARIO_FILES:
        file_path = scenario_path / filename
        if not file_path.exists():
            raise ScenarioValidationError(f"Missing standard scenario file: {filename}")

    for dirname in STANDARD_SCENARIO_DIRS:
        dir_path = scenario_path / dirname
        if not dir_path.exists():
            raise ScenarioValidationError(f"Missing standard scenario directory: {dirname}")
        if not dir_path.is_dir():
            raise ScenarioValidationError(f"Standard path is not a directory: {dirname}")

    manifest_path = scenario_path / "scenario.yaml"
    if manifest_path.exists():
        manifest = load_mapping(manifest_path)
        schema_path = manifest.get("schema")
        if schema_path:
            schema_file = scenario_path / str(schema_path)
            if not schema_file.exists():
                raise ScenarioValidationError(f"Schema path in manifest does not exist: {schema_path}")

    try:
        scenario_config = load_scenario(scenario_path)
    except Exception as e:
        raise ScenarioValidationError(f"Failed to load scenario: {e}")

    return scenario_config


def list_scenarios(scenarios_dir: str | Path) -> list[dict[str, Any]]:
    """List all valid scenarios in the scenarios directory.

    Args:
        scenarios_dir: Path to the scenarios directory

    Returns:
        List of valid scenario summaries with id, root, and basic info
    """
    scenarios_path = Path(scenarios_dir)
    if not scenarios_path.exists():
        return []

    scenarios = []
    for entry in scenarios_path.iterdir():
        if not entry.is_dir():
            continue
        try:
            config = validate_scenario(entry, scenarios_dir=None)
            scenarios.append({
                "id": config.id,
                "root": str(config.root),
                "data_dir": str(config.data_dir),
                "prompts_dir": str(config.prompts_dir),
                "schemas_dir": str(config.schemas_dir),
            })
        except (ScenarioValidationError, Exception):
            continue

    return scenarios


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base configuration dictionary
        override: Override configuration dictionary

    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def stable_hash(data: Any) -> str:
    """Compute a stable hash of data using sha256_json.

    Args:
        data: Data to hash (must be JSON serializable)

    Returns:
        Hexadecimal hash string
    """
    return sha256_json(data)


def file_hash(path: str | Path) -> str:
    """Compute hash of a file's contents.

    Args:
        path: Path to the file

    Returns:
        Hexadecimal hash string
    """
    return sha256_text(Path(path).read_text(encoding="utf-8"))


def directory_file_hashes(root: str | Path) -> dict[str, str]:
    """Compute hashes of all files in a directory.

    Args:
        root: Root directory path

    Returns:
        Dictionary mapping relative file paths to their hashes
    """
    root_path = Path(root)
    hashes: dict[str, str] = {}
    for path in sorted(root_path.rglob("*")):
        if path.is_file():
            rel_path = str(path.relative_to(root_path))
            hashes[rel_path] = file_hash(path)
    return hashes


def run_artifact_metadata(scenario: ScenarioConfig) -> dict[str, Any]:
    """Generate run artifact metadata for a scenario.

    Args:
        scenario: ScenarioConfig instance

    Returns:
        Dictionary containing artifact metadata
    """
    dir_hashes = directory_file_hashes(scenario.root)
    return {
        "scenario_id": scenario.id,
        "scenario_root": str(scenario.root),
        "config_hash": scenario.config_hash,
        "directory_hashes": dir_hashes,
        "stable_hash": stable_hash({
            "id": scenario.id,
            "config_hash": scenario.config_hash,
            "directory_hashes": dir_hashes,
        }),
    }


def write_run_artifacts(artifact_dir: str | Path, scenario: ScenarioConfig) -> dict[str, Path]:
    """Write run artifacts for a scenario to a directory.

    Args:
        artifact_dir: Directory to write artifacts to
        scenario: ScenarioConfig instance

    Returns:
        Dictionary mapping artifact names to their written paths
    """
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)

    metadata = run_artifact_metadata(scenario)
    metadata_path = artifact_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    scenario_artifact_dir = artifact_path / scenario.id
    scenario_artifact_dir.mkdir(parents=True, exist_ok=True)

    config_path = scenario_artifact_dir / "optimizer.yaml"
    config_content = scenario.root / "optimizer.yaml"
    if config_content.exists():
        config_path.write_text(config_content.read_text(encoding="utf-8"), encoding="utf-8")

    return {
        "metadata": metadata_path,
        "scenario_config": config_path,
    }
