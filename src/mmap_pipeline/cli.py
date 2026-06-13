"""Command-line entry point for the optimizer loop."""

from __future__ import annotations

import argparse
import json

from .optimizer import OptimizerLoop


def build_parser() -> argparse.ArgumentParser:
    """Build the optimizer CLI argument parser."""

    parser = argparse.ArgumentParser(description="Run the MMAP optimizer loop.")
    parser.add_argument("--checkpoint", default="checkpoint.json", help="Path to checkpoint JSON.")
    parser.add_argument("--fewshot-pool", default="fewshot_pool.json", help="Path to fewshot pool JSON.")
    parser.add_argument("--rounds", type=int, default=1, help="Number of additional rounds to run.")
    parser.add_argument("--sample-id", action="append", dest="sample_ids", help="Sample id to track.")
    parser.add_argument("--resume", action="store_true", help="Resume optimizer state from the checkpoint.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the optimizer CLI."""

    args = build_parser().parse_args(argv)
    loop = OptimizerLoop(
        checkpoint_path=args.checkpoint,
        fewshot_pool_path=args.fewshot_pool,
        sample_ids=args.sample_ids,
        resume=args.resume,
    )
    state = loop.run(args.rounds)
    print(json.dumps(state.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
