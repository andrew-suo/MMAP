from __future__ import annotations

from dataclasses import dataclass

from mmap_optimizer.core.hashing import sha256_text
from .ir import PromptIR, PromptSection


@dataclass
class RenderedPrompt:
    text: str
    text_hash: str
    line_count: int


class PromptRenderer:
    def render(self, prompt_ir: PromptIR) -> RenderedPrompt:
        by_id: dict[str, PromptSection] = {s.id: s for s in prompt_ir.sections}
        order = prompt_ir.rendering_order or [s.id for s in prompt_ir.sections]
        chunks: list[str] = []
        for section_id in order:
            section = by_id.get(section_id)
            if section is None or not section.rendering_enabled:
                continue
            if prompt_ir.include_section_markers:
                chunks.append(f'<SECTION id="{section.id}" type="{section.type}" priority="{section.priority}">')
                chunks.append(section.content.strip())
                chunks.append("</SECTION>")
            else:
                chunks.append(section.content.strip())
        text = "\n\n".join(chunk for chunk in chunks if chunk)
        return RenderedPrompt(text=text, text_hash=sha256_text(text), line_count=len(text.splitlines()))
