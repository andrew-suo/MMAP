from mmap_optimizer.prompt.initializer import initialize_prompt


def test_default_behavior_preserves_legacy_unmapped():
    prompt = "# Task\n1. one\n1. two\n\n\n# Schema\n1. keep\n1. schema\n"

    initialized = initialize_prompt(prompt)

    assert initialized["legacy_unmapped"] == prompt
    assert initialized["sections"][0]["content"] == "# Task\n1. one\n1. two\n\n\n"


def test_enabled_tools_normalize_spacing_and_numbering():
    prompt = "# Task\n1. one   \n1. two\n\n\n# Notes\nBody\n"

    initialized = initialize_prompt(
        prompt,
        fix_numbering=True,
        normalize_spacing=True,
    )

    assert initialized["legacy_unmapped"] == "# Task\n\n1. one\n2. two\n\n# Notes\n\nBody\n"


def test_schema_section_stays_frozen_when_tools_enabled():
    prompt = "# Task\n1. one\n1. two\n\n# Output Schema\n1. keep\n1. schema\n"

    initialized = initialize_prompt(
        prompt,
        fix_numbering=True,
        normalize_spacing=True,
    )

    schema_section = initialized["sections"][1]
    assert schema_section["frozen"] is True
    assert schema_section["content"] == "# Output Schema\n1. keep\n1. schema\n"
    assert "# Output Schema\n1. keep\n1. schema\n" in initialized["legacy_unmapped"]
