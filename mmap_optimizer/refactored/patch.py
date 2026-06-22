"""Patch 相关模型。

根据设计文档，patch 需要记录：
- source_sample_ids
- target_section
- operation
- content
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ExtractionPatch:
    """Extraction Prompt Patch。"""
    id: str
    target_section_id: str
    operation_type: Literal["replace", "insert_before", "insert_after", "delete"]
    content: str
    rationale: str
    source_sample_ids: list[str] = field(default_factory=list)
    status: Literal["draft", "merged", "candidate_safe", "accepted", "rejected"] = "draft"
    rejection_reason: str | None = None
    fixed_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    toxic_sample_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "target_section_id": self.target_section_id,
            "operation_type": self.operation_type,
            "content": self.content,
            "rationale": self.rationale,
            "source_sample_ids": list(self.source_sample_ids),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "broken_sample_ids": list(self.broken_sample_ids),
            "toxic_sample_ids": list(self.toxic_sample_ids),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractionPatch":
        """从字典格式创建。"""
        return cls(
            id=data["id"],
            target_section_id=data["target_section_id"],
            operation_type=data["operation_type"],
            content=data["content"],
            rationale=data["rationale"],
            source_sample_ids=data.get("source_sample_ids", []),
            status=data.get("status", "draft"),
            rejection_reason=data.get("rejection_reason"),
            fixed_sample_ids=data.get("fixed_sample_ids", []),
            broken_sample_ids=data.get("broken_sample_ids", []),
            toxic_sample_ids=data.get("toxic_sample_ids", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class AnalysisPatch:
    """Analysis Prompt Patch。"""
    id: str
    target_section_id: str
    operation_type: Literal["replace", "insert_before", "insert_after", "delete"]
    content: str
    rationale: str
    source_sample_ids: list[str] = field(default_factory=list)
    status: Literal["draft", "merged", "candidate_safe", "accepted", "rejected"] = "draft"
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "target_section_id": self.target_section_id,
            "operation_type": self.operation_type,
            "content": self.content,
            "rationale": self.rationale,
            "source_sample_ids": list(self.source_sample_ids),
            "status": self.status,
            "rejection_reason": self.rejection_reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisPatch":
        """从字典格式创建。"""
        return cls(
            id=data["id"],
            target_section_id=data["target_section_id"],
            operation_type=data["operation_type"],
            content=data["content"],
            rationale=data["rationale"],
            source_sample_ids=data.get("source_sample_ids", []),
            status=data.get("status", "draft"),
            rejection_reason=data.get("rejection_reason"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class PatchMergeReport:
    """Patch 合并报告。"""
    id: str
    input_patch_count: int
    merged_patch_count: int
    conflict_count: int
    merged_patches: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "input_patch_count": self.input_patch_count,
            "merged_patch_count": self.merged_patch_count,
            "conflict_count": self.conflict_count,
            "merged_patches": list(self.merged_patches),
            "conflicts": list(self.conflicts),
            "metadata": dict(self.metadata),
        }


@dataclass
class ToxicityReport:
    """测毒报告。"""
    id: str
    tested_patch_count: int
    toxic_patch_count: int
    safe_patch_count: int
    toxic_patches: list[str] = field(default_factory=list)  # patch IDs
    safe_patches: list[str] = field(default_factory=list)  # patch IDs
    toxic_sample_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "tested_patch_count": self.tested_patch_count,
            "toxic_patch_count": self.toxic_patch_count,
            "safe_patch_count": self.safe_patch_count,
            "toxic_patches": list(self.toxic_patches),
            "safe_patches": list(self.safe_patches),
            "toxic_sample_ids": list(self.toxic_sample_ids),
            "metadata": dict(self.metadata),
        }