"""Command-line entry point for MMAP optimizer utilities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from mmap_optimizer.prompt.snapshot import PromptVersion, load_prompt_snapshot


PROMPT_TYPES = ("extraction", "analysis")


def active_prompt_path(run_dir: str | Path, prompt_type: str) -> Path:
    """Return the run artifact path for the active prompt of ``prompt_type``."""

    return Path(run_dir) / "artifacts" / "prompts" / f"active_{prompt_type}_prompt.json"


def write_prompt_version(prompt_version: PromptVersion, output_path: str | Path) -> Path:
    """Write a prompt version to ``output_path`` as JSON."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(prompt_version.to_mapping(), output_file, ensure_ascii=False, indent=2)
        output_file.write("\n")
    return path


def update_run_state(run_dir: str | Path, snapshot_id: str, prompt_type: str) -> Path:
    """Record rollback metadata in ``run_state.json``."""

    path = Path(run_dir) / "run_state.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    else:
        state = {}

    state["stage"] = "rolled_back"
    state["rollback_snapshot_id"] = snapshot_id
    state["rollback_prompt_type"] = prompt_type

    with path.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")
    return path


def rollback_prompt(args: argparse.Namespace) -> Path:
    """Restore a prompt snapshot to a file or the run's active prompt artifact."""

    prompt_version = load_prompt_snapshot(
        run_dir=args.run_dir,
        snapshot_id=args.snapshot_id,
        prompt_type=args.prompt_type,
    )
    output_path = args.output_path or active_prompt_path(args.run_dir, args.prompt_type)
    written_path = write_prompt_version(prompt_version, output_path)

    if args.output_path is None:
        update_run_state(args.run_dir, args.snapshot_id, args.prompt_type)

    return written_path


def build_parser() -> argparse.ArgumentParser:
    """Build the MMAP optimizer CLI parser."""

    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    rollback_parser = subparsers.add_parser(
        "rollback-prompt",
        help="Restore a saved prompt snapshot to an output file or active run artifact.",
    )
    rollback_parser.add_argument(
        "--run-dir",
        required=True,
        help="Run directory containing prompt snapshots and run artifacts.",
    )
    rollback_parser.add_argument(
        "--snapshot-id",
        required=True,
        help="Prompt snapshot id to restore.",
    )
    rollback_parser.add_argument(
        "--prompt-type",
        required=True,
        choices=PROMPT_TYPES,
        help="Prompt type to restore.",
    )
    rollback_parser.add_argument(
        "--output-path",
        help=(
            "Optional file to write the restored prompt to. When omitted, the "
            "prompt is written back to the run's active prompt artifact."
        ),
    )
    rollback_parser.set_defaults(func=rollback_prompt)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    written_path = args.func(args)
    print(written_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
