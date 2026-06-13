"""Command line interface for scenario-aware MMAP optimizer runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from mmap_optimizer.core.scenario import ScenarioConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MMAP optimizer with a scenario directory.")
    parser.add_argument(
        "--scenario",
        default="scenarios/default",
        help="Path to a scenario directory (for example: scenarios/foo).",
    )
    parser.add_argument(
        "--run-dir",
        help="Override the output run directory configured by the scenario.",
    )
    parser.add_argument(
        "--artifact-name",
        default="artifact.json",
        help="Artifact file name to write inside the run directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scenario = ScenarioConfig.load(args.scenario).with_run_dir(args.run_dir)
    artifact_path = write_artifact(scenario, args.artifact_name)
    print(f"Wrote artifact: {artifact_path}")
    return 0


def write_artifact(scenario: ScenarioConfig, artifact_name: str = "artifact.json") -> Path:
    run_dir = Path(scenario.optimizer_config["run_dir"]).expanduser()
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / artifact_name
    artifact = {
        **scenario.artifact_metadata(),
        "scenario_root": str(scenario.root),
        "optimizer_config": scenario.optimizer_config,
        "resources": {
            "prompts": sorted(scenario.prompts),
            "schemas": sorted(scenario.schemas),
            "data": sorted(scenario.data),
        },
    }
    artifact_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact_path


if __name__ == "__main__":
    raise SystemExit(main())
