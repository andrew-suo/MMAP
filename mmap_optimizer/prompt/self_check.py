from __future__ import annotations

import re
from dataclasses import dataclass, field
from string import Formatter
from typing import Any


@dataclass
class PromptSelfCheckIssue:
    severity: str
    code: str
    message: str


@dataclass
class PromptSelfCheckReport:
    valid: bool
    issues: list[PromptSelfCheckIssue] = field(default_factory=list)
    recommendation: str = ""


def self_check_prompt_text(*, prompt_text: str, schema: dict[str, Any], declared_placeholders: set[str] | None = None) -> PromptSelfCheckReport:
    declared_placeholders = declared_placeholders or set()
    issues: list[PromptSelfCheckIssue] = []
    for placeholder in _placeholders(prompt_text):
        if placeholder not in declared_placeholders:
            issues.append(PromptSelfCheckIssue("warning", "UNDECLARED_PLACEHOLDER", f"Placeholder `{placeholder}` is not declared."))
    required = set(schema.get("required", []) or [])
    properties = set((schema.get("properties") or {}).keys())
    for field in required:
        if field not in prompt_text:
            issues.append(PromptSelfCheckIssue("warning", "SCHEMA_FIELD_NOT_MENTIONED", f"Required schema field `{field}` is not mentioned in prompt text."))
    if required - properties:
        issues.append(PromptSelfCheckIssue("error", "SCHEMA_REQUIRED_WITHOUT_PROPERTY", "Schema requires fields missing from properties: " + ", ".join(sorted(required - properties))))
    if "不要修改输出格式" in prompt_text and re.search(r"(扩展|新增).*输出", prompt_text):
        issues.append(PromptSelfCheckIssue("error", "CONTRADICTORY_OUTPUT_FORMAT_RULE", "Prompt both freezes and expands output format."))
    valid = not any(issue.severity == "error" for issue in issues)
    recommendation = "ready" if valid else "fix error-level prompt issues before optimization"
    return PromptSelfCheckReport(valid=valid, issues=issues, recommendation=recommendation)


def _placeholders(text: str) -> set[str]:
    names: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(text):
        if field_name and field_name.isidentifier():
            names.add(field_name)
    names.update(match.group(1) for match in re.finditer(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}", text))
    return names
