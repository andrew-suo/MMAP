"""Prompt Structuring Phase。

根据设计文档，Prompt Structuring Phase 负责将初始 Markdown prompt
转换为结构化 prompt。该阶段只在 Run 开始时执行一次。

当 prompt 结构质量较差时，会调用模型进行标准化，标准化后重新解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..prompt.structured_prompt import PromptSection, StructuredPrompt


@dataclass
class PromptStructuringConfig:
    """Prompt Structuring 配置。"""
    enabled: bool = True
    use_model_when_structure_poor: bool = True
    standardization_prompt_path: str | Path | None = None
    max_standardization_iterations: int = 1


class MarkdownParser:
    """Markdown 解析器，将 Markdown 转换为结构化 prompt。"""

    def parse(self, markdown: str, prompt_type: str, prompt_id: str) -> StructuredPrompt:
        """解析 Markdown 文本。"""
        sections = self._parse_sections(markdown)
        return StructuredPrompt(
            id=prompt_id,
            prompt_type=prompt_type,
            sections=sections,
            raw_markdown=markdown,
        )

    def _parse_sections(self, markdown: str) -> list[PromptSection]:
        """解析章节。"""
        lines = markdown.split("\n")
        sections: list[PromptSection] = []
        section_stack: list[tuple[int, PromptSection]] = []  # (level, section)

        current_content: list[str] = []
        current_bullets: list[str] = []
        in_code_block = False
        code_block_content: list[str] = []

        section_counter = 0

        for line in lines:
            # 处理代码块
            if line.strip().startswith("```"):
                if in_code_block:
                    # 结束代码块
                    in_code_block = False
                    current_content.append("\n".join(code_block_content))
                    code_block_content = []
                else:
                    # 开始代码块
                    in_code_block = True
                    current_content.append(line)
                continue

            if in_code_block:
                code_block_content.append(line)
                continue

            # 处理标题
            header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if header_match:
                # 保存当前内容到栈顶章节
                self._save_content_to_stack(section_stack, current_content, current_bullets)
                current_content = []
                current_bullets = []

                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                section_counter += 1
                section_id = f"section_{section_counter}"

                # 检查是否是输出 schema（标记为不可修改）
                mutable = not self._is_output_schema(title, level)

                new_section = PromptSection(
                    id=section_id,
                    title=title,
                    level=level,
                    content="",
                    bullets=[],
                    children=[],
                    mutable=mutable,
                )

                # 根据层级构建树结构
                if not section_stack:
                    sections.append(new_section)
                    section_stack.append((level, new_section))
                else:
                    # 找到合适的父节点
                    while section_stack and section_stack[-1][0] >= level:
                        section_stack.pop()

                    if section_stack:
                        parent = section_stack[-1][1]
                        parent.children.append(new_section)
                    else:
                        sections.append(new_section)

                    section_stack.append((level, new_section))
                continue

            # 处理 bullet
            bullet_match = re.match(r"^[-*]\s+(.+)$", line)
            if bullet_match:
                current_bullets.append(bullet_match.group(1).strip())
                continue

            # 普通内容
            if line.strip():
                current_content.append(line)

        # 保存最后的内容
        self._save_content_to_stack(section_stack, current_content, current_bullets)

        return sections

    def _save_content_to_stack(
        self,
        section_stack: list[tuple[int, PromptSection]],
        content: list[str],
        bullets: list[str],
    ) -> None:
        """保存内容到栈顶章节。"""
        if section_stack and (content or bullets):
            section = section_stack[-1][1]
            if content:
                section.content = "\n".join(content).strip()
            if bullets:
                section.bullets = bullets

    def _is_output_schema(self, title: str, level: int) -> bool:
        """判断是否是输出 schema 章节。"""
        schema_keywords = ["output", "schema", "format", "json", "response", "输出", "格式"]
        title_lower = title.lower()
        return any(keyword in title_lower for keyword in schema_keywords)


class PromptStructuringPhase:
    """Prompt Structuring Phase。"""

    def __init__(
        self,
        config: PromptStructuringConfig,
        model_client: Any | None = None,
        model_config: dict[str, Any] | None = None,
    ):
        """初始化 Prompt Structuring Phase。

        Args:
            config: 配置对象
            model_client: 可选的模型客户端，用于结构质量较差时进行标准化
        """
        self.config = config
        self.parser = MarkdownParser()
        self.model_client = model_client
        self.model_config = model_config

    def run(
        self,
        extraction_prompt_path: str | Path,
        analysis_prompt_path: str | Path,
    ) -> tuple[StructuredPrompt, StructuredPrompt]:
        """执行 Prompt Structuring Phase。

        Args:
            extraction_prompt_path: extraction prompt Markdown 文件路径
            analysis_prompt_path: analysis prompt Markdown 文件路径

        Returns:
            (structured_extraction_prompt, structured_analysis_prompt)
        """
        print(f"\n--- Phase 1: Prompt 结构化 ---")

        # 读取原始 Markdown
        extraction_markdown = Path(extraction_prompt_path).read_text(encoding="utf-8")
        analysis_markdown = Path(analysis_prompt_path).read_text(encoding="utf-8")

        # 解析并可能标准化
        structured_extraction = self._parse_and_standardize(
            extraction_markdown,
            prompt_type="extraction",
            prompt_id="structured_extraction_prompt",
        )
        print(f"Extraction 结构化完成，共 {len(structured_extraction.sections)} 个 section")

        structured_analysis = self._parse_and_standardize(
            analysis_markdown,
            prompt_type="analysis",
            prompt_id="structured_analysis_prompt",
        )
        print(f"Analysis 结构化完成，共 {len(structured_analysis.sections)} 个 section")

        return structured_extraction, structured_analysis

    def _parse_and_standardize(
        self,
        markdown: str,
        prompt_type: str,
        prompt_id: str,
    ) -> StructuredPrompt:
        """解析 Markdown 并在结构质量较差时进行标准化。

        Args:
            markdown: 原始 Markdown 文本
            prompt_type: prompt 类型（extraction/analysis）
            prompt_id: prompt 唯一 ID

        Returns:
            结构化后的 Prompt
        """
        # 初步解析
        structured = self.parser.parse(markdown, prompt_type, prompt_id)

        # 检查结构质量
        quality = self._evaluate_structure_quality(structured)
        print(f"结构化质量: {quality}")
        structured.metadata["structure_quality"] = quality
        structured.metadata["standardized"] = False

        # 如果结构质量较差且配置允许，使用模型进行标准化
        if (
            self.config.use_model_when_structure_poor
            and quality != "good"
            and self.model_client is not None
            and self.config.standardization_prompt_path is not None
        ):
            print("调用模型进行 Prompt 标准化...")
            standardized_markdown = self._standardize_with_model(markdown)
            if standardized_markdown:
                # 重新解析标准化后的文本
                new_structured = self.parser.parse(
                    standardized_markdown,
                    prompt_type,
                    f"{prompt_id}_standardized",
                )
                new_quality = self._evaluate_structure_quality(new_structured)

                # 质量回退检查：标准化结果不应比原结果更差
                if len(new_structured.sections) == 0:
                    print(f"⚠️ 标准化后 0 sections，保留原结果（原 section 数: {len(structured.sections)}）")
                    structured.metadata["standardized"] = False
                    structured.metadata["standardization_skipped"] = True
                    structured.metadata["standardization_reason"] = "0 sections after standardization"
                elif len(new_structured.sections) < len(structured.sections):
                    print(f"⚠️ 标准化后 section 数减少 ({len(structured.sections)} → {len(new_structured.sections)})，保留原结果")
                    structured.metadata["standardized"] = False
                    structured.metadata["standardization_skipped"] = True
                    structured.metadata["standardization_reason"] = "section count decreased"
                else:
                    structured = new_structured
                    quality = new_quality
                    print(f"标准化后结构化质量: {quality}")
                    structured.metadata["structure_quality"] = quality
                    structured.metadata["standardized"] = True
                    structured.metadata["original_markdown"] = markdown

        return structured

    def _standardize_with_model(self, markdown: str) -> str | None:
        """使用模型对 prompt 进行标准化。

        Args:
            markdown: 原始 Markdown 文本

        Returns:
            标准化后的 Markdown 文本，失败返回 None
        """
        try:
            # 读取标准化 prompt
            standardization_prompt = Path(
                self.config.standardization_prompt_path
            ).read_text(encoding="utf-8")

            # 将原始 prompt 注入到 system prompt 的占位符中
            standardization_prompt = standardization_prompt.replace(
                "{original_prompt}", markdown
            )

            # 构建消息
            messages = [
                {"role": "system", "content": standardization_prompt},
                {"role": "user", "content": "请开始标准化处理。"},
            ]

            # 调用模型
            response = self.model_client.complete(
                messages=messages,
                model_config=self.model_config,
            )

            return response.raw_output.strip()

        except Exception as exc:
            # 标准化失败，返回 None，使用原始解析结果
            return None

    def _evaluate_structure_quality(self, prompt: StructuredPrompt) -> str:
        """评估结构质量。"""
        if not prompt.sections:
            return "poor"

        # 检查是否有清晰的层级结构
        has_top_level = any(s.level == 1 for s in prompt.sections)
        has_nested = any(s.children for s in prompt.sections)

        if has_top_level and has_nested:
            return "good"
        elif has_top_level:
            return "medium"
        else:
            return "poor"

    def validate(self, prompt: StructuredPrompt) -> list[str]:
        """验证结构化 prompt。"""
        issues: list[str] = []

        # 检查是否有章节
        if not prompt.sections:
            issues.append("No sections found in structured prompt")

        # 检查每个章节是否有 ID
        for section in prompt.sections:
            if not section.id:
                issues.append(f"Section '{section.title}' has no ID")

            # 检查子章节
            for child in section.children:
                if not child.id:
                    issues.append(f"Child section '{child.title}' has no ID")

        # 检查是否有输出 schema（标记为不可修改）
        has_schema = any(not s.mutable for s in prompt.sections)
        if not has_schema:
            # 尝试在内容中查找 schema 相关内容
            schema_keywords = ["output", "schema", "json", "format"]
            for section in prompt.sections:
                content_lower = section.content.lower()
                if any(keyword in content_lower for keyword in schema_keywords):
                    issues.append(f"Section '{section.title}' may contain output schema but is marked as mutable")

        return issues
