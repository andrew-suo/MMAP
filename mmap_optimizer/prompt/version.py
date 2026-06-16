from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from mmap_optimizer.core.enums import PromptType, PromptVersionType
from .ir import PromptIR
from .renderer import PromptRenderer, RenderedPrompt


@dataclass
class PromptVersion:
    id: str
    prompt_type: PromptType | str
    version: int
    prompt_ir: PromptIR
    output_schema_contract_id: str
    version_type: PromptVersionType | str = PromptVersionType.INITIAL
    parent_version_id: str | None = None
    applied_patch_ids: list[str] = field(default_factory=list)
    compression_patch_ids: list[str] = field(default_factory=list)
    status: str = "active"
    rendered_prompt: RenderedPrompt | None = None
    created_by_run_id: str | None = None
    created_by_round_id: str | None = None
    # 保留 from_dict 时未识别的字段，避免静默数据丢失
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def render(self) -> RenderedPrompt:
        self.rendered_prompt = PromptRenderer().render(self.prompt_ir)
        return self.rendered_prompt

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PromptVersion":
        data = dict(data)
        prompt_ir_data = data.get("prompt_ir")
        if isinstance(prompt_ir_data, dict):
            data["prompt_ir"] = PromptIR.from_dict(prompt_ir_data)
        known = set(cls.__dataclass_fields__.keys())
        fields = {k: data[k] for k in known & data.keys()}
        extra = {k: v for k, v in data.items() if k not in known}
        obj = cls(**fields)
        if extra:
            obj._extra = extra
        # 仅在无已渲染结果时重新渲染，避免重复计算
        if obj.rendered_prompt is None:
            obj.render()
        return obj
