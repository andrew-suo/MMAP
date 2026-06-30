"""PromptManager - Prompt 统一管理模块。

负责加载和管理所有 prompt 文件，提供模板渲染功能。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PromptManager:
    """Prompt 管理器。

    统一加载和管理所有 prompt 文件，支持模板渲染。
    """

    def __init__(self) -> None:
        self._cached_prompts: dict[str, str] = {}
        self._placeholder_pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

    def load_prompt(self, path: str | Path) -> str:
        """加载单个 prompt 文件。

        Args:
            path: prompt 文件路径，支持绝对路径和相对路径。

        Returns:
            prompt 文件内容字符串。

        Raises:
            FileNotFoundError: 如果文件不存在。
        """
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Prompt 文件不存在: {p}")

        content = p.read_text(encoding="utf-8")
        self._cached_prompts[str(p)] = content
        return content

    def render_prompt(self, template_path: str | Path, **kwargs: Any) -> str:
        """渲染带变量的模板。

        Args:
            template_path: 模板文件路径。
            **kwargs: 模板变量键值对。

        Returns:
            渲染后的文本。
        """
        template = self.load_prompt(template_path)
        kwargs.setdefault(
            "sample_optimization_trajectory",
            "No prior trajectory for this sample.",
        )
        missing_keys = sorted({
            key for key in self._placeholder_pattern.findall(template)
            if key not in kwargs
        })
        if missing_keys:
            raise KeyError(
                f"Prompt template missing variables for {template_path}: "
                + ", ".join(missing_keys)
            )

        def replace_placeholder(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(kwargs[key])

        return self._placeholder_pattern.sub(replace_placeholder, template)

    def clear_cache(self) -> None:
        """清除缓存。"""
        self._cached_prompts.clear()


_prompt_manager = PromptManager()


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例。"""
    return _prompt_manager


def load_prompt(path: str | Path) -> str:
    """加载单个 prompt 文件（便捷函数）。"""
    return _prompt_manager.load_prompt(path)


def render_prompt(template_path: str | Path, **kwargs: Any) -> str:
    """渲染模板（便捷函数）。"""
    return _prompt_manager.render_prompt(template_path, **kwargs)


__all__ = ["PromptManager", "get_prompt_manager", "load_prompt", "render_prompt"]
