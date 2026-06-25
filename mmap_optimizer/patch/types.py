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
    operation_type: Literal[
        "append_to_section",
        "insert_after",
        "insert_before",
        "replace_in_section",
        "replace_section",
        "add_after_section",
        "delete_section",
    ]
    content: str
    rationale: str
    source_sample_ids: list[str] = field(default_factory=list)
    status: Literal["draft", "merged", "candidate_safe", "accepted", "rejected"] = "draft"
    rejection_reason: str | None = None
    fixed_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    toxic_sample_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    target_text: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    new_header: str | None = None

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
            "target_text": self.target_text,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "new_header": self.new_header,
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
            target_text=data.get("target_text"),
            old_text=data.get("old_text"),
            new_text=data.get("new_text"),
            new_header=data.get("new_header"),
        )


@dataclass
class AnalysisPatch:
    """Analysis Prompt Patch。"""
    id: str
    target_section_id: str
    operation_type: Literal[
        "append_to_section",
        "insert_after",
        "insert_before",
        "replace_in_section",
        "replace_section",
        "add_after_section",
        "delete_section",
    ]
    content: str
    rationale: str
    source_sample_ids: list[str] = field(default_factory=list)
    status: Literal["draft", "merged", "candidate_safe", "accepted", "rejected"] = "draft"
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    target_text: str | None = None
    old_text: str | None = None
    new_text: str | None = None
    new_header: str | None = None

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
            "target_text": self.target_text,
            "old_text": self.old_text,
            "new_text": self.new_text,
            "new_header": self.new_header,
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
            target_text=data.get("target_text"),
            old_text=data.get("old_text"),
            new_text=data.get("new_text"),
            new_header=data.get("new_header"),
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
    strategy: str = "tree_merge"
    dropped_patch_count: int = 0
    input_patch_ids: list[str] = field(default_factory=list)
    merged_patch_ids: list[str] = field(default_factory=list)
    dropped_patch_ids: list[str] = field(default_factory=list)
    conflict_patch_ids: list[str] = field(default_factory=list)
    merge_reason: str = ""
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)

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
            "strategy": self.strategy,
            "dropped_patch_count": self.dropped_patch_count,
            "input_patch_ids": list(self.input_patch_ids),
            "merged_patch_ids": list(self.merged_patch_ids),
            "dropped_patch_ids": list(self.dropped_patch_ids),
            "conflict_patch_ids": list(self.conflict_patch_ids),
            "merge_reason": self.merge_reason,
            "fallback_used": self.fallback_used,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchMergeReport":
        """从字典格式创建。"""
        return cls(
            id=data["id"],
            input_patch_count=data["input_patch_count"],
            merged_patch_count=data["merged_patch_count"],
            conflict_count=data["conflict_count"],
            merged_patches=data.get("merged_patches", []),
            conflicts=data.get("conflicts", []),
            metadata=data.get("metadata", {}),
            strategy=data.get("strategy", "tree_merge"),
            dropped_patch_count=data.get("dropped_patch_count", 0),
            input_patch_ids=data.get("input_patch_ids", []),
            merged_patch_ids=data.get("merged_patch_ids", []),
            dropped_patch_ids=data.get("dropped_patch_ids", []),
            conflict_patch_ids=data.get("conflict_patch_ids", []),
            merge_reason=data.get("merge_reason", ""),
            fallback_used=data.get("fallback_used", False),
            warnings=data.get("warnings", []),
        )


@dataclass
class PatchTestRecord:
    """单个 patch 的测毒测试记录。

    记录 patch 在测毒过程中的状态、被测试的样本、
    broken / fixed 样本以及提前停止原因。
    """
    patch_id: str
    status: str  # "safe", "toxic", "skipped"
    tested_sample_ids: list[str] = field(default_factory=list)
    broken_sample_ids: list[str] = field(default_factory=list)
    fixed_sample_ids: list[str] = field(default_factory=list)
    stop_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "patch_id": self.patch_id,
            "status": self.status,
            "tested_sample_ids": list(self.tested_sample_ids),
            "broken_sample_ids": list(self.broken_sample_ids),
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PatchTestRecord":
        """从字典格式创建。"""
        return cls(
            patch_id=data["patch_id"],
            status=data["status"],
            tested_sample_ids=data.get("tested_sample_ids", []),
            broken_sample_ids=data.get("broken_sample_ids", []),
            fixed_sample_ids=data.get("fixed_sample_ids", []),
            stop_reason=data.get("stop_reason"),
        )


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
    mode: str = "extraction"  # "extraction" or "analysis"
    safe_patch_ids: list[str] = field(default_factory=list)  # alias for safe_patches
    toxic_patch_ids: list[str] = field(default_factory=list)  # alias for toxic_patches
    patch_test_records: list[dict[str, Any]] = field(default_factory=list)
    early_stop_enabled: bool = True

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
            "mode": self.mode,
            "safe_patch_ids": list(self.safe_patch_ids),
            "toxic_patch_ids": list(self.toxic_patch_ids),
            "patch_test_records": list(self.patch_test_records),
            "early_stop_enabled": self.early_stop_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToxicityReport":
        """从字典格式创建。"""
        return cls(
            id=data["id"],
            tested_patch_count=data["tested_patch_count"],
            toxic_patch_count=data["toxic_patch_count"],
            safe_patch_count=data["safe_patch_count"],
            toxic_patches=data.get("toxic_patches", []),
            safe_patches=data.get("safe_patches", []),
            toxic_sample_ids=data.get("toxic_sample_ids", []),
            metadata=data.get("metadata", {}),
            mode=data.get("mode", "extraction"),
            safe_patch_ids=data.get("safe_patch_ids", []),
            toxic_patch_ids=data.get("toxic_patch_ids", []),
            patch_test_records=data.get("patch_test_records", []),
            early_stop_enabled=data.get("early_stop_enabled", True),
        )


@dataclass
class CompressionReport:
    """压缩报告。"""
    id: str
    prompt_type: str  # "extraction" | "analysis"
    base_prompt_id: str
    compressed_prompt_id: str | None = None
    triggered: bool = False
    accepted: bool = False
    rejected_reason: str | None = None
    line_count_before: int = 0
    line_count_after: int = 0
    char_count_before: int = 0
    char_count_after: int = 0
    base_accuracy: float | None = None
    pre_compression_accuracy: float | None = None
    post_compression_accuracy: float | None = None
    broken_sample_ids: list[str] = field(default_factory=list)
    fixed_sample_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    still_over_limit: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式。"""
        return {
            "id": self.id,
            "prompt_type": self.prompt_type,
            "base_prompt_id": self.base_prompt_id,
            "compressed_prompt_id": self.compressed_prompt_id,
            "triggered": self.triggered,
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
            "line_count_before": self.line_count_before,
            "line_count_after": self.line_count_after,
            "char_count_before": self.char_count_before,
            "char_count_after": self.char_count_after,
            "base_accuracy": self.base_accuracy,
            "pre_compression_accuracy": self.pre_compression_accuracy,
            "post_compression_accuracy": self.post_compression_accuracy,
            "broken_sample_ids": list(self.broken_sample_ids),
            "fixed_sample_ids": list(self.fixed_sample_ids),
            "warnings": list(self.warnings),
            "still_over_limit": self.still_over_limit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompressionReport":
        """从字典创建。"""
        return cls(
            id=data["id"],
            prompt_type=data["prompt_type"],
            base_prompt_id=data["base_prompt_id"],
            compressed_prompt_id=data.get("compressed_prompt_id"),
            triggered=data.get("triggered", False),
            accepted=data.get("accepted", False),
            rejected_reason=data.get("rejected_reason"),
            line_count_before=data.get("line_count_before", 0),
            line_count_after=data.get("line_count_after", 0),
            char_count_before=data.get("char_count_before", 0),
            char_count_after=data.get("char_count_after", 0),
            base_accuracy=data.get("base_accuracy"),
            pre_compression_accuracy=data.get("pre_compression_accuracy"),
            post_compression_accuracy=data.get("post_compression_accuracy"),
            broken_sample_ids=data.get("broken_sample_ids", []),
            fixed_sample_ids=data.get("fixed_sample_ids", []),
            warnings=data.get("warnings", []),
            still_over_limit=data.get("still_over_limit", False),
        )