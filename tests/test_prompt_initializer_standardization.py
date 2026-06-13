from mmap_optimizer.cli import build_parser
from mmap_optimizer.prompt.initializer import initialize_prompt_version


LEGACY_PROMPT = """# Task
Intro.
3. first
3. second
## Notes
alpha
## Notes
beta
## Output Schema
1. DO NOT CHANGE


{"type":"object"}
"""


def test_default_initialization_preserves_legacy_text():
    assert initialize_prompt_version(LEGACY_PROMPT) == LEGACY_PROMPT


def test_enabled_standardization_fixes_numbering_spacing_and_duplicate_headings():
    prompt = "# Task\nIntro.\n3. first\n3. second\n## Notes\nalpha\n## Notes\nbeta\n"

    initialized = initialize_prompt_version(
        prompt,
        fix_numbering=True,
        normalize_spacing=True,
        unique_headings=True,
    )

    assert "1. first\n2. second" in initialized
    assert "# Task\n\nIntro." in initialized
    assert "## Notes\n" in initialized
    assert "## Notes (2)\n" in initialized


def test_output_schema_section_remains_frozen_when_standardizing():
    prompt = """# Task
Intro.
## Output Schema
3. must stay three


{"title":"same spacing"}
## After
3. first
3. second
"""

    initialized = initialize_prompt_version(
        prompt,
        fix_numbering=True,
        normalize_spacing=True,
        unique_headings=True,
    )

    assert "## Output Schema\n3. must stay three\n\n\n{\"title\":\"same spacing\"}" in initialized
    assert "## After\n\n1. first\n2. second" in initialized


def test_run_and_run_smoke_accept_prompt_format_flags():
    parser = build_parser()

    run_args = parser.parse_args(["run", "--normalize-prompt-format"])
    smoke_args = parser.parse_args(["run-smoke", "--normalize-prompt-format"])

    assert run_args.normalize_prompt_format is True
    assert smoke_args.normalize_prompt_format is True
