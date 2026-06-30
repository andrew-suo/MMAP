"""CompressionExecutor - Prompt 压缩执行器。

混合压缩策略：
1. 确定性预压缩（去重连续空行、去重重复行、去除行尾空白）
2. Section 级 LLM 压缩（低贡献 section 优先）
3. Prompt 级 LLM 压缩（兜底）

验证方式：LLM 语义验证（替代回归测试）。

压缩约束：
1. immutable section 内容不可修改
2. section ID 不可删除/变更
3. prompt_type 不可变更
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from ..patch.types import CompressionReport
from ..data.sample import SampleBatch, SampleSet
from ..prompt.output_repair import parse_model_json_output
from ..prompt.structured_prompt import PromptSection, StructuredPrompt
from ..prompt.section_contribution import SectionContributionTracker

logger = logging.getLogger(__name__)


class CompressionExecutor:
    """混合 LLM 压缩执行器。"""

    def __init__(
        self,
        model_client: Any = None,
        model_config: dict[str, Any] | None = None,
        compression_prompt_path: str = "prompts/prompt_compression.txt",
        validation_prompt_path: str = "prompts/prompt_compression_validation.txt",
        ema_alpha: float = 0.3,
    ) -> None:
        self.model_client = model_client
        self.model_config = model_config
        self.compression_prompt_path = compression_prompt_path
        self.validation_prompt_path = validation_prompt_path
        self.ema_alpha = ema_alpha

    def compress_if_needed(
        self,
        prompt: StructuredPrompt,
        line_limit: int,
        char_limit: int,
        batch: SampleBatch | None = None,
        sample_set: SampleSet | None = None,
        mode: str = "extraction",
        contribution_tracker: SectionContributionTracker | None = None,
    ) -> tuple[StructuredPrompt, CompressionReport]:
        """按需压缩 prompt。

        流程：
        1. 统计行数和字符数，检查是否需要压缩。
        2. 确定性预压缩（去重空行/重复行）。
        3. Section 级 LLM 压缩（低贡献 section 优先）。
        4. Prompt 级 LLM 压缩（仍超限时的兜底）。
        5. LLM 语义验证。

        Args:
            prompt: 待压缩的 StructuredPrompt。
            line_limit: 行数上限。
            char_limit: 字符数上限。
            batch: 抽样批次（保留接口兼容，当前未使用）。
            sample_set: 样本集合（保留接口兼容，当前未使用）。
            mode: 压缩模式，"extraction" 或 "analysis"。
            contribution_tracker: section 贡献度追踪器。

        Returns:
            (prompt, report) 元组。若接受压缩则返回压缩后的 prompt，
            否则返回原 prompt。
        """
        # 1. 统计行数和字符数
        markdown = prompt.to_markdown()
        line_count = len(markdown.splitlines())
        char_count = len(markdown)

        report = CompressionReport(
            id=f"compression_{prompt.prompt_type}_{prompt.id}",
            prompt_type=prompt.prompt_type,
            base_prompt_id=prompt.id,
            line_count_before=line_count,
            char_count_before=char_count,
        )

        # 2. 检查是否需要压缩
        if line_count <= line_limit and char_count <= char_limit:
            report.triggered = False
            report.rejected_reason = "NOT_NEEDED"
            report.line_count_after = line_count
            report.char_count_after = char_count
            return prompt, report

        report.triggered = True
        logger.info(
            "[Compression] %s prompt 超限: %d lines (limit=%d), %d chars (limit=%d)",
            mode, line_count, line_limit, char_count, char_limit,
        )

        # 3. 确定性预压缩
        compressed = self._create_compressed_prompt(prompt)
        warnings = self._verify_constraints(prompt, compressed)
        report.warnings = warnings
        if warnings:
            report.accepted = False
            report.rejected_reason = "CONSTRAINT_VIOLATION"
            report.compressed_prompt_id = compressed.id
            comp_md = compressed.to_markdown()
            report.line_count_after = len(comp_md.splitlines())
            report.char_count_after = len(comp_md)
            return prompt, report

        comp_md = compressed.to_markdown()
        comp_lines = len(comp_md.splitlines())
        comp_chars = len(comp_md)
        report.line_count_after = comp_lines
        report.char_count_after = comp_chars
        report.compressed_prompt_id = compressed.id

        # 检查确定性压缩是否已降至限内
        if comp_lines <= line_limit and comp_chars <= char_limit:
            report.accepted = True
            report.validation_passed = True
            report.validation_reasons = ["deterministic compression sufficient"]
            logger.info("[Compression] 确定性压缩已降至限内")
            return compressed, report

        # 4. Section 级 LLM 压缩（低贡献优先）
        if self.model_client is not None:
            compressed, comp_lines, comp_chars, section_changes = self._llm_compress_sections(
                compressed, line_limit, char_limit, contribution_tracker,
            )
            report.compressed_sections = section_changes
            comp_md = compressed.to_markdown()
            comp_lines = len(comp_md.splitlines())
            comp_chars = len(comp_md)
            report.line_count_after = comp_lines
            report.char_count_after = comp_chars

            if comp_lines <= line_limit and comp_chars <= char_limit:
                # Section 级压缩已降至限内，验证
                valid, reasons = self._llm_validate_prompt(prompt, compressed)
                if valid:
                    report.accepted = True
                    report.validation_passed = True
                    report.validation_reasons = reasons or ["section-level LLM compression validated"]
                    logger.info("[Compression] Section 级 LLM 压缩成功，已降至限内")
                    return compressed, report
                else:
                    report.accepted = False
                    report.rejected_reason = "VALIDATION_FAILED"
                    report.validation_reasons = reasons or ["section-level compression failed validation"]
                    return prompt, report

            # 5. Prompt 级 LLM 压缩（兜底）
            compressed, comp_lines, comp_chars = self._llm_compress_prompt(
                compressed, line_limit, char_limit,
            )
            comp_md = compressed.to_markdown()
            comp_lines = len(comp_md.splitlines())
            comp_chars = len(comp_md)
            report.line_count_after = comp_lines
            report.char_count_after = comp_chars

            warnings = self._verify_constraints(prompt, compressed)
            report.warnings = warnings
            if warnings:
                report.accepted = False
                report.rejected_reason = "CONSTRAINT_VIOLATION"
                report.validation_reasons = ["prompt-level compression violated structure constraints"]
                return prompt, report

            valid, reasons = self._llm_validate_prompt(prompt, compressed)
            if valid:
                report.accepted = True
                report.validation_passed = True
                report.validation_reasons = reasons or ["prompt-level LLM compression validated"]
                logger.info("[Compression] Prompt 级 LLM 压缩成功")
                if comp_lines > line_limit or comp_chars > char_limit:
                    report.still_over_limit = True
                return compressed, report
            else:
                report.accepted = False
                report.rejected_reason = "VALIDATION_FAILED"
                report.validation_reasons = reasons or ["prompt-level compression failed validation"]
                return prompt, report

        # 无 model_client，仅确定性压缩
        report.accepted = True
        report.validation_passed = True
        report.validation_reasons = ["deterministic only (no model_client)"]
        if comp_lines > line_limit or comp_chars > char_limit:
            report.still_over_limit = True
        logger.info("[Compression] 无 model_client，仅确定性压缩")
        return compressed, report

    # ------------------------------------------------------------------
    # 确定性压缩
    # ------------------------------------------------------------------

    def _compress_content(self, content: str) -> str:
        """确定性压缩：去重连续空行和重复行。"""
        lines = content.split("\n")
        result: list[str] = []
        prev_line: str | None = None
        prev_was_empty = False
        for line in lines:
            stripped = line.rstrip()
            is_empty = stripped == ""
            if is_empty and prev_was_empty:
                continue
            if stripped == prev_line and not is_empty:
                continue
            result.append(stripped)
            prev_line = stripped
            prev_was_empty = is_empty
        while result and result[0] == "":
            result.pop(0)
        while result and result[-1] == "":
            result.pop()
        return "\n".join(result)

    def _create_compressed_prompt(self, prompt: StructuredPrompt) -> StructuredPrompt:
        """创建确定性压缩后的 prompt。"""
        new_sections = copy.deepcopy(prompt.sections)

        def _compress_section(section: PromptSection) -> None:
            if section.mutable and section.content:
                section.content = self._compress_content(section.content)
            if section.mutable and section.bullets:
                seen: set[str] = set()
                unique_bullets: list[str] = []
                for b in section.bullets:
                    if b not in seen:
                        seen.add(b)
                        unique_bullets.append(b)
                section.bullets = unique_bullets
            for child in section.children:
                _compress_section(child)

        for section in new_sections:
            _compress_section(section)

        compressed = StructuredPrompt(
            id=f"{prompt.id}_compressed",
            prompt_type=prompt.prompt_type,
            sections=new_sections,
            raw_markdown="",
            version=prompt.version + 1,
        )
        compressed.raw_markdown = compressed.to_markdown()
        return compressed

    # ------------------------------------------------------------------
    # 约束验证
    # ------------------------------------------------------------------

    def _flatten_sections(self, sections: list[PromptSection]) -> list[PromptSection]:
        """递归展平 sections。"""
        result: list[PromptSection] = []
        for s in sections:
            result.append(s)
            result.extend(self._flatten_sections(s.children))
        return result

    def _verify_constraints(
        self,
        original: StructuredPrompt,
        compressed: StructuredPrompt,
    ) -> list[str]:
        """验证压缩约束，返回 warnings 列表。"""
        warnings: list[str] = []
        if original.prompt_type != compressed.prompt_type:
            warnings.append("prompt_type changed during compression")
        orig_sections = {s.id: s for s in self._flatten_sections(original.sections)}
        comp_sections = {s.id: s for s in self._flatten_sections(compressed.sections)}
        for sid, orig_sec in orig_sections.items():
            comp_sec = comp_sections.get(sid)
            if comp_sec is None:
                warnings.append(f"section {sid} was deleted")
            elif not orig_sec.mutable:
                if orig_sec.content != comp_sec.content:
                    warnings.append(f"immutable section {sid} content was modified")
                if list(orig_sec.bullets) != list(comp_sec.bullets):
                    warnings.append(f"immutable section {sid} bullets were modified")
        return warnings

    # ------------------------------------------------------------------
    # LLM 压缩
    # ------------------------------------------------------------------

    def _llm_compress_sections(
        self,
        prompt: StructuredPrompt,
        line_limit: int,
        char_limit: int,
        contribution_tracker: SectionContributionTracker | None,
    ) -> tuple[StructuredPrompt, int, int, list[str]]:
        """Section 级 LLM 压缩（低贡献优先）。

        Returns:
            (compressed_prompt, line_count, char_count, compressed_section_ids)
        """
        # 获取所有 mutable section，按贡献度升序排列
        all_sections = self._flatten_sections(prompt.sections)
        mutable_sections = [s for s in all_sections if s.mutable and s.content.strip()]

        if contribution_tracker is not None:
            priority_order = contribution_tracker.get_priority_order(
                [s.id for s in mutable_sections]
            )
            # 按优先级排序 sections
            section_map = {s.id: s for s in mutable_sections}
            ordered_sections = [section_map[sid] for sid in priority_order if sid in section_map]
        else:
            ordered_sections = mutable_sections

        compressed_section_ids: list[str] = []

        for section in ordered_sections:
            # 检查是否已降至限内
            current_md = prompt.to_markdown()
            current_lines = len(current_md.splitlines())
            current_chars = len(current_md)
            if current_lines <= line_limit and current_chars <= char_limit:
                break

            # 压缩单个 section
            section_lines = len(section.content.splitlines())
            if section_lines <= 2:
                continue  # 太短不压缩

            target_min = max(1, int(section_lines * 0.5))
            target_max = max(target_min + 1, int(section_lines * 0.8))

            compressed_content = self._llm_compress_section(
                section, target_min, target_max,
            )
            if compressed_content is not None and compressed_content != section.content:
                # LLM 验证
                valid, _ = self._llm_validate_compression(section.content, compressed_content)
                if valid:
                    section.content = compressed_content
                    compressed_section_ids.append(section.id)
                    logger.info(
                        "[Compression] Section '%s' 压缩: %d → %d 行",
                        section.id, section_lines, len(compressed_content.splitlines()),
                    )

        # 更新 raw_markdown
        prompt.raw_markdown = prompt.to_markdown()
        final_md = prompt.raw_markdown
        return prompt, len(final_md.splitlines()), len(final_md), compressed_section_ids

    def _llm_compress_section(
        self,
        section: PromptSection,
        target_min: int,
        target_max: int,
    ) -> str | None:
        """调用 LLM 压缩单个 section。

        Args:
            section: 待压缩的 section
            target_min: 目标最小行数
            target_max: 目标最大行数

        Returns:
            压缩后的内容，或 None 表示失败
        """
        try:
            prompt_template = Path(self.compression_prompt_path).read_text(encoding="utf-8")
        except Exception:
            logger.warning("[Compression] 无法加载压缩 prompt: %s", self.compression_prompt_path)
            return None

        current_lines = len(section.content.splitlines())
        input_content = f"## Section: {section.title}\n\n{section.content}"

        # 填充模板
        system_content = prompt_template.format(
            mode="section",
            current_lines=current_lines,
            min_target_lines=target_min,
            max_target_lines=target_max,
            input_content=input_content,
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "请压缩上述 Section 内容。"},
        ]

        try:
            response = self.model_client.complete(messages, model_config=self.model_config)
            result = response.raw_output.strip()
            # 移除可能的 markdown 包裹
            result = self._strip_markdown(result)
            if result:
                return result
        except Exception as e:
            logger.warning("[Compression] Section LLM 压缩失败: %s", e)

        return None

    def _llm_compress_prompt(
        self,
        prompt: StructuredPrompt,
        line_limit: int,
        char_limit: int,
    ) -> tuple[StructuredPrompt, int, int]:
        """Prompt 级 LLM 压缩（兜底）。

        Returns:
            (compressed_prompt, line_count, char_count)
        """
        try:
            prompt_template = Path(self.compression_prompt_path).read_text(encoding="utf-8")
        except Exception:
            logger.warning("[Compression] 无法加载压缩 prompt: %s", self.compression_prompt_path)
            return prompt, len(prompt.to_markdown().splitlines()), len(prompt.to_markdown())

        current_md = prompt.to_markdown()
        current_lines = len(current_md.splitlines())
        target_min = max(1, int(line_limit * 0.85))
        target_max = line_limit

        system_content = prompt_template.format(
            mode="prompt",
            current_lines=current_lines,
            min_target_lines=target_min,
            max_target_lines=target_max,
            input_content=current_md,
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "请压缩上述 Prompt 全文。"},
        ]

        try:
            response = self.model_client.complete(messages, model_config=self.model_config)
            result = response.raw_output.strip()
            result = self._strip_markdown(result)
            if result and len(result.splitlines()) < current_lines:
                # 用 LLM 压缩结果重建 prompt
                from ..phases.prompt_structuring import MarkdownParser
                try:
                    parser = MarkdownParser()
                    new_prompt = parser.parse(
                        result, prompt_type=prompt.prompt_type, prompt_id=f"{prompt.id}_llm_compressed",
                    )
                    new_prompt.version = prompt.version + 1
                    new_md = new_prompt.to_markdown()
                    logger.info(
                        "[Compression] Prompt 级 LLM 压缩: %d → %d 行",
                        current_lines, len(new_md.splitlines()),
                    )
                    return new_prompt, len(new_md.splitlines()), len(new_md)
                except Exception as e:
                    logger.warning("[Compression] Prompt 级压缩结果解析失败: %s", e)
        except Exception as e:
            logger.warning("[Compression] Prompt 级 LLM 压缩失败: %s", e)

        return prompt, current_lines, len(current_md)

    # ------------------------------------------------------------------
    # LLM 验证
    # ------------------------------------------------------------------

    def _llm_validate_compression(self, original: str, compressed: str) -> tuple[bool, str]:
        """调用 LLM 验证压缩后的语义等价性。

        Args:
            original: 原始文本
            compressed: 压缩后文本

        Returns:
            (验证是否通过, 原因)
        """
        if not original.strip() or not compressed.strip():
            return True, "empty_content_skipped"

        if self.model_client is None:
            return True, "no_model_client"

        try:
            prompt_template = Path(self.validation_prompt_path).read_text(encoding="utf-8")
        except Exception:
            logger.warning("[Compression] 无法加载验证 prompt: %s", self.validation_prompt_path)
            return False, "validation_prompt_load_failed"

        system_content = prompt_template.format(
            original_section=original,
            pruned_section=compressed,
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": "请验证上述压缩是否合格。"},
        ]

        try:
            response = self.model_client.complete(messages, model_config=self.model_config)
            result = response.raw_output.strip()
            # 解析 JSON 验证结果
            parsed = self._parse_validation_result(result)
            if parsed is not None:
                valid, reason = parsed
                if not valid:
                    logger.info("[Compression] 验证失败: %s", reason)
                return valid, reason or "validation_result_returned_false"
            return False, "validation_parse_failed"
        except Exception as e:
            logger.warning("[Compression] LLM 验证调用失败: %s", e)
            return False, "validation_call_failed"

    def _llm_validate_prompt(
        self,
        original: StructuredPrompt,
        compressed: StructuredPrompt,
    ) -> tuple[bool, list[str]]:
        """验证整个 prompt 压缩的语义等价性。

        逐 section 验证 mutable section，immutable section 跳过（已有约束检查）。
        """
        orig_sections = {s.id: s for s in self._flatten_sections(original.sections)}
        comp_sections = {s.id: s for s in self._flatten_sections(compressed.sections)}
        reasons: list[str] = []

        for sid, orig_sec in orig_sections.items():
            comp_sec = comp_sections.get(sid)
            if comp_sec is None:
                continue
            if not orig_sec.mutable:
                continue
            if orig_sec.content == comp_sec.content:
                continue
            valid, reason = self._llm_validate_compression(orig_sec.content, comp_sec.content)
            if not valid:
                reasons.append(f"{sid}:{reason}")
                return False, reasons

        return True, reasons or ["prompt_compression_validated"]

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _strip_markdown(self, text: str) -> str:
        """移除 markdown 代码块标记。"""
        text = re.sub(r"^```json\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"^```\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        return text.strip()

    def _parse_validation_result(self, text: str) -> tuple[bool, str] | None:
        """解析 LLM 验证结果 JSON。

        Returns:
            (valid, reason) 元组，或 None 表示解析失败
        """
        parse_result = parse_model_json_output(
            text,
            expected_schema={"valid": bool, "reason": str},
            model_client=self.model_client,
            model_config=self.model_config,
        )
        parsed = parse_result.parsed
        if isinstance(parsed, dict) and "valid" in parsed:
            return bool(parsed["valid"]), str(parsed.get("reason", ""))

        return None
