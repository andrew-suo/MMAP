"""Command line interface for MMAP optimizer utilities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .prompt.health import check_prompt_health


def _read_text(path: str | None) -> str | None:
    if path is None:
        return None
    return Path(path).read_text(encoding="utf-8")


def check_prompt_command(args: argparse.Namespace) -> int:
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    baseline = _read_text(args.baseline_prompt)
    report = check_prompt_health(
        prompt,
        baseline_prompt=baseline,
        max_section_words=args.max_section_words,
        legacy_unmapped_max_words=args.legacy_unmapped_max_words,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_prompt = subparsers.add_parser("check-prompt", help="Run prompt health checks on a Markdown prompt.")
    check_prompt.add_argument("prompt", help="Path to the prompt file to check.")
    check_prompt.add_argument("--baseline-prompt", help="Optional baseline prompt containing frozen schema sections.")
    check_prompt.add_argument("--max-section-words", type=int, default=500)
    check_prompt.add_argument("--legacy-unmapped-max-words", type=int, default=120)
    check_prompt.set_defaults(func=check_prompt_command)

    validate = subparsers.add_parser(
        "validate-config",
        help="Validate configuration and optionally include prompt health checks.",
    )
    validate.add_argument("--prompt", help="Prompt file to include in validation.")
    validate.add_argument("--baseline-prompt", help="Optional baseline prompt containing frozen schema sections.")
    validate.add_argument("--max-section-words", type=int, default=500)
    validate.add_argument("--legacy-unmapped-max-words", type=int, default=120)
    validate.set_defaults(func=lambda args: check_prompt_command(args) if args.prompt else 0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
