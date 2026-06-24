"""Prompt 模块。

包含结构化 Prompt 定义、渲染器和 Prompt 管理器。
"""

from .structured_prompt import (
    PromptSection,
    StructuredPrompt,
    StructuredPromptRenderer,
)
from .prompt_manager import (
    PromptManager,
    get_prompt_manager,
    load_prompt,
    render_prompt,
)

__all__ = [
    "PromptSection",
    "StructuredPrompt",
    "StructuredPromptRenderer",
    "PromptManager",
    "get_prompt_manager",
    "load_prompt",
    "render_prompt",
]