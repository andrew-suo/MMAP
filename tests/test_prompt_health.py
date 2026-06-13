from mmap_optimizer.prompt.health import IssueType, check_prompt_health, safe_autofix
from mmap_optimizer.prompt.refactor import refactor_prompt
from mmap_optimizer.prompt.standardizer import standardize_prompt


def issue_types(report):
    return {issue.issue_type for issue in report.issues}


def test_duplicate_heading_is_reported():
    prompt = """# Task
Do work.
# Task
Do other work.
# Output Format
JSON.
"""

    report = check_prompt_health(prompt)

    assert IssueType.DUPLICATE_HEADING in issue_types(report)
    duplicate = next(issue for issue in report.issues if issue.issue_type is IssueType.DUPLICATE_HEADING)
    assert duplicate.section_id == "task"
    assert duplicate.suggested_fix


def test_numbering_jump_is_reported():
    prompt = """# 1 First
Do work.
# 3 Third
Do more work.
# Output Format
JSON.
"""

    report = check_prompt_health(prompt)

    assert IssueType.NUMBERING_JUMP in issue_types(report)


def test_schema_section_frozen_modification_is_reported():
    baseline = """# Output Schema
{"type":"object","required":["answer"]}
# Output Format
JSON.
"""
    current = """# Output Schema
{"type":"object","required":["answer","score"]}
# Output Format
JSON.
"""

    report = check_prompt_health(current, baseline_prompt=baseline)

    assert IssueType.FROZEN_SCHEMA_MODIFIED in issue_types(report)
    assert not report.passed


def test_legacy_unmapped_too_large_is_reported():
    prompt = """# Task
Do work.
# legacy_unmapped
{legacy}
# Output Format
JSON.
""".format(legacy=" ".join(["legacy"] * 8))

    report = check_prompt_health(prompt, legacy_unmapped_max_words=5)

    assert IssueType.LEGACY_UNMAPPED_TOO_LARGE in issue_types(report)


def test_safe_autofix_only_normalizes_section_marker():
    prompt = """<!-- SECTION: wrong -->
# Output Format
JSON.
"""

    fixed = safe_autofix(prompt)

    assert fixed == """<!-- SECTION: output_format -->
# Output Format
JSON.
"""
    assert standardize_prompt(prompt) == fixed
    assert refactor_prompt(prompt).prompt == fixed
