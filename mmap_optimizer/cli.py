"""Command line interface for MMAP optimizer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .orchestration.optimizer_loop import OptimizerLoop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run optimizer rounds")
    run_parser.add_argument("--run-dir", default=".", help="directory for checkpoint.json")
    run_parser.add_argument("--rounds", type=int, default=1, help="rounds to execute")
    run_parser.add_argument("--resume", action="store_true", help="resume from checkpoint.json")
    run_parser.add_argument(
        "--fewshot-pool-path",
        default="fewshot_pool.json",
        help="path recorded for the few-shot pool",
    )
    run_parser.set_defaults(func=_run)
    return parser


def _run(args: argparse.Namespace) -> int:
    result = OptimizerLoop(
        run_dir=Path(args.run_dir),
        rounds=args.rounds,
        resume=args.resume,
        fewshot_pool_path=args.fewshot_pool_path,
    ).run()
    print(
        json.dumps(
            {
                "completed_round_ids": result.completed_round_ids,
                "latest_metrics_summary": result.latest_metrics_summary,
                "checkpoint_path": str(result.checkpoint_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
