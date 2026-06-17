from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.templates import build_default_template_registry


@dataclass
class SemanticCompressionCandidate:
    content: str
    semantic_valid: bool
    reason: str | None = None
    retry_count: int = 0
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class OutputConstraintCheck:
    valid: bool
    violations: list[str] = field(default_factory=list)


def check_output_constraints(text: str, *, required_terms: list[str] | None = None, forbidden_terms: list[str] | None = None, max_lines: int | None = None) -> OutputConstraintCheck:
    violations: list[str] = []
    for term in required_terms or []:
        if term not in text:
            violations.append(f"missing required term: {term}")
    for term in forbidden_terms or []:
        if term in text:
            violations.append(f"contains forbidden term: {term}")
    if max_lines is not None and len(text.splitlines()) > max_lines:
        violations.append(f"line count exceeds max_lines={max_lines}")
    return OutputConstraintCheck(valid=not violations, violations=violations)


class SemanticCompressionEngine:
    def __init__(self, model_client: ModelClient, model_config: dict[str, Any] | None = None, max_validation_retries: int = 0):
        self.model_client = model_client
        self.model_config = model_config or {}
        self.max_validation_retries = max(0, max_validation_retries)
        self.registry = build_default_template_registry()

    def prune_section(self, *, section_header: str, section_content: str) -> SemanticCompressionCandidate:
        prune_template = self.registry.get("llm_prune")
        prune_prompt = prune_template.render(section_header=section_header, section_content=section_content)
        prune_response = self.model_client.complete(
            [{"role": "system", "content": prune_prompt}, {"role": "user", "content": json.dumps({"section_header": section_header, "section_content": section_content}, ensure_ascii=False)}],
            model_config=self.model_config,
            response_format=prune_template.output_contract,
        )
        pruned = prune_response.raw_output.strip()
        if not pruned or pruned.strip() == section_content.strip():
            return SemanticCompressionCandidate(content=section_content, semantic_valid=False, reason="NO_SEMANTIC_PRUNE_CHANGE")
        validation = self.validate_prune(original_section=section_content, pruned_section=pruned)
        if not validation.semantic_valid:
            validation.validation_errors.append(validation.reason or "SEMANTIC_VALIDATION_FAILED")
            return validation
        return SemanticCompressionCandidate(content=pruned, semantic_valid=True, reason=validation.reason)

    def validate_prune(self, *, original_section: str, pruned_section: str) -> SemanticCompressionCandidate:
        validation_template = self.registry.get("llm_prune_validation")
        validation_prompt = validation_template.render(original_section=original_section, pruned_section=pruned_section)
        response = self.model_client.complete(
            [{"role": "system", "content": validation_prompt}, {"role": "user", "content": json.dumps({"original_section": original_section, "pruned_section": pruned_section}, ensure_ascii=False)}],
            model_config=self.model_config,
            response_format=validation_template.output_contract,
        )
        try:
            parsed = json.loads(response.raw_output)
        except json.JSONDecodeError:
            return SemanticCompressionCandidate(content=pruned_section, semantic_valid=False, reason="PRUNE_VALIDATION_PARSE_ERROR")
        valid = bool(parsed.get("valid")) if isinstance(parsed, dict) else False
        reason = str(parsed.get("reason", "")) if isinstance(parsed, dict) else "PRUNE_VALIDATION_NOT_OBJECT"
        return SemanticCompressionCandidate(content=pruned_section, semantic_valid=valid, reason=reason)
