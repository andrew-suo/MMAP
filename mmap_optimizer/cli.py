"""Command line interface for MMAP optimizer."""

from __future__ import annotations

import argparse
from pathlib import Path

from .prompt.initializer import initialize_prompt_version


def _add_prompt_format_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--normalize-prompt-format",
        action="store_true",
        help="Apply all prompt-format normalization passes before running.",
    )
    parser.add_argument(
        "--fix-prompt-numbering",
        action="store_true",
        help="Renumber ordered Markdown lists in the prompt before running.",
    )
    parser.add_argument(
        "--normalize-prompt-spacing",
        action="store_true",
        help="Normalize Markdown spacing in the prompt before running.",
    )
    parser.add_argument(
        "--unique-prompt-headings",
        action="store_true",
        help="Make duplicate Markdown heading titles unique before running.",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help="Optional prompt file to initialize. If omitted, an empty prompt is used.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mmap-optimizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("run", "run-smoke"):
        subparser = subparsers.add_parser(command)
        _add_prompt_format_flags(subparser)
        subparser.set_defaults(handler=_handle_run)

    return parser


def _prompt_kwargs(args: argparse.Namespace) -> dict[str, bool]:
    normalize_all = bool(args.normalize_prompt_format)
    return {
        "fix_numbering": normalize_all or bool(args.fix_prompt_numbering),
        "normalize_spacing": normalize_all or bool(args.normalize_prompt_spacing),
        "unique_headings": normalize_all or bool(args.unique_prompt_headings),
    }


def _handle_run(args: argparse.Namespace) -> int:
    prompt = args.prompt_file.read_text() if args.prompt_file else ""
    initialize_prompt_version(prompt, **_prompt_kwargs(args))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
