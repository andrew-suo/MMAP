from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


TEXT_LEVEL_OPERATION_MODES = {"replace_in_section", "insert_after", "insert_before", "delete"}


@dataclass
class Patch:
    id: str
    type: str
    status: str
    target_prompt_type: str
    base_version_id: str
    section_id: str
    operation_type: str
    operation_mode: str
    intent_name: str
    intent_description: str
    patch_text: str
    rationale: str
    old_text: str | None = None
    target_text: str | None = None
    new_text: str | None = None
    source_sample_ids: list[str] = field(default_factory=list)
    source_analysis_ids: list[str] = field(default_factory=list)
    risk_level: str = "unknown"
    possible_side_effects: list[str] = field(default_factory=list)
    fixed_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    toxicity_result: str = "not_tested"
    effectiveness_result: str = "not_tested"
    rejection_reason: str | None = None
    target: dict[str, Any] = field(default_factory=dict)
    operation: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    # New additive fields for exact text-level patches. Safe default values
    # mean existing callers that don't use these fields continue to work.
    insert_text: str | None = None
    insert_position: str | None = None
    locator: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Patch":
        """Build a patch from a dict-like object.

        Unknown keys are stored in :attr:`extra` so callers can attach provenance
        information without losing it. This makes the schema backward compatible
        with older patch dictionaries and with new locator/payload shapes.
        """

        known = {
            "id", "type", "status", "target_prompt_type", "base_version_id",
            "section_id", "operation_type", "operation_mode", "intent_name",
            "intent_description", "patch_text", "rationale", "old_text",
            "target_text", "new_text", "source_sample_ids", "source_analysis_ids",
            "risk_level", "possible_side_effects", "fixed_sample_ids",
            "broken_sample_ids", "toxicity_result", "effectiveness_result",
            "rejection_reason", "extra", "insert_text", "insert_position",
            "locator", "payload", "target", "operation", "evidence", "risk",
            "audit", "constraints",
        }
        kwargs: dict[str, Any] = {key: data[key] for key in known if key in data}
        extra = dict(kwargs.get("extra") or {})
        for key, value in data.items():
            if key not in known:
                extra[key] = value
        if extra:
            kwargs["extra"] = extra
        return cls(**kwargs)

    def locator_value(self, key: str) -> Any:
        """Return a locator value, preferring flat fields over nested ``locator`` data."""

        flat_value = getattr(self, key, None)
        if flat_value is not None:
            return flat_value
        if isinstance(self.locator, dict):
            return self.locator.get(key)
        return None

    def payload_value(self, *keys: str) -> Any:
        """Return the first available payload value from flat or nested ``payload`` data."""

        for key in keys:
            flat_value = getattr(self, key, None)
            if flat_value is not None:
                return flat_value
            if isinstance(self.payload, dict) and key in self.payload:
                return self.payload[key]
        return None

    @property
    def effective_operation_mode(self) -> str:
        """Normalize insert-position hints to concrete operation modes."""

        if self.operation_mode in {"insert", "insert_in_section"}:
            if self.insert_position == "before":
                return "insert_before"
            if self.insert_position == "after":
                return "insert_after"
        return self.operation_mode

    def is_text_level(self) -> bool:
        """Return whether this patch targets a specific text location within a section."""

        return self.effective_operation_mode in TEXT_LEVEL_OPERATION_MODES

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dict snapshot of the patch."""

        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "target_prompt_type": self.target_prompt_type,
            "base_version_id": self.base_version_id,
            "section_id": self.section_id,
            "operation_type": self.operation_type,
            "operation_mode": self.operation_mode,
            "intent_name": self.intent_name,
            "intent_description": self.intent_description,
            "patch_text": self.patch_text,
            "rationale": self.rationale,
            "old_text": self.old_text,
            "target_text": self.target_text,
            "new_text": self.new_text,
            "source_sample_ids": list(self.source_sample_ids),
            "source_analysis_ids": list(self.source_analysis_ids),
            "risk_level": self.risk_level,
            "possible_side_effects": list(self.possible_side_effects),
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "broken_sample_ids": list(self.broken_sample_ids),
            "toxicity_result": self.toxicity_result,
            "effectiveness_result": self.effectiveness_result,
            "rejection_reason": self.rejection_reason,
            "target": dict(self.target),
            "operation": dict(self.operation),
            "evidence": dict(self.evidence),
            "risk": dict(self.risk),
            "audit": dict(self.audit),
            "constraints": dict(self.constraints),
            "extra": dict(self.extra),
            "insert_text": self.insert_text,
            "insert_position": self.insert_position,
            "locator": dict(self.locator),
            "payload": dict(self.payload),
        }

    def compact_dict(self) -> dict[str, Any]:
        """Minimal public view – only fields typically needed for UI/logs."""

        return {
            "id": self.id,
            "section_id": self.section_id,
            "operation_type": self.operation_type,
            "status": self.status,
            "risk_level": self.risk_level,
            "rejection_reason": self.rejection_reason,
            "toxicity_result": self.toxicity_result,
            "effectiveness_result": self.effectiveness_result,
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "broken_sample_ids": list(self.broken_sample_ids),
        }
