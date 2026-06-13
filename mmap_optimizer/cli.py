"""Command line interface for MMAP optimizer utilities."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from mmap_optimizer.core.scenario import (
    DEFAULT_BASE_CONFIG_PATH,
    DEFAULT_SCENARIOS_DIR,
    ScenarioValidationError,
    list_scenarios,
    load_scenario,
    run_artifact_metadata,
    summaries_as_dicts,
)


def _add_common_scenario_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scenarios-dir",
        default=DEFAULT_SCENARIOS_DIR,
        help=f"Directory containing scenario subdirectories (default: {DEFAULT_SCENARIOS_DIR})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-scenarios", help="List valid scenarios")
    _add_common_scenario_dir(list_parser)
    list_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    validate_parser = subparsers.add_parser("validate-scenario", help="Validate and load a scenario")
    validate_parser.add_argument("scenario", help="Scenario id or path to validate")
    _add_common_scenario_dir(validate_parser)
    validate_parser.add_argument(
        "--base-config",
        default=DEFAULT_BASE_CONFIG_PATH,
        help=f"Base optimizer config inherited by the scenario (default: {DEFAULT_BASE_CONFIG_PATH})",
    )
    validate_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    return parser


def _handle_list(args: argparse.Namespace) -> int:
    summaries = list_scenarios(args.scenarios_dir)
    if args.json:
        print(json.dumps(summaries_as_dicts(summaries), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not summaries:
        print("No valid scenarios found.")
        return 0
    for summary in summaries:
        print(f"{summary.id}\t{summary.task_type}\t{summary.description}")
    return 0


def _handle_validate(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario, args.scenarios_dir, args.base_config)
    metadata = run_artifact_metadata(scenario)
    if args.json:
        payload = {
            "valid": True,
            "id": scenario.id,
            "description": scenario.manifest.description,
            "task_type": scenario.manifest.task_type,
            "config": scenario.config,
            **metadata,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"Scenario {scenario.id!r} is valid.")
    print(f"task_type: {scenario.manifest.task_type}")
    print(f"scenario_config_hash: {scenario.config_hash}")
    print(f"prompt_hashes: {len(scenario.prompt_hashes)} file(s)")
    print(f"schema_hashes: {len(scenario.schema_hashes)} file(s)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list-scenarios":
            return _handle_list(args)
        if args.command == "validate-scenario":
            return _handle_validate(args)
    except ScenarioValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
