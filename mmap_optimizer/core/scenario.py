from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig, load_mapping, optimizer_config_from_mapping
from mmap_optimizer.core.hashing import sha256_text


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
