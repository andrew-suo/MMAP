"""Command line interface for optimizer orchestration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .orchestration import OptimizerLoop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MMAP optimizer loop")
    parser.add_argument("--output-dir", type=Path, default=Path("runs/default"), help="Run output directory")
    parser.add_argument("--rounds", type=int, default=1, help="Number of additional rounds to execute")
    parser.add_argument("--fewshot-pool-path", default=None, help="Path to the few-shot pool file")
    parser.add_argument("--resume", action="store_true", help="Resume from output-dir/checkpoint.json")
    parser.add_argument("--rollback-to", dest="rollback_to_snapshot_id", default=None, help="Prompt snapshot id to restore before running")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loop = OptimizerLoop(
        args.output_dir,
        rounds=args.rounds,
        fewshot_pool_path=args.fewshot_pool_path,
        resume=args.resume,
        rollback_to_snapshot_id=args.rollback_to_snapshot_id,
    )
    checkpoint = loop.run()
    print(json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
