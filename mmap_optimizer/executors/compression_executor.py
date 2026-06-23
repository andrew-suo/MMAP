"""CompressionExecutor - Prompt 压缩执行器。

当 prompt 超过行数/字符限制时，对 mutable section 进行确定性压缩
（去重连续空行、去重重复行、去除行尾空白），并通过回归测试验证
压缩后准确率不下降。

压缩约束：
1. immutable section 内容不可修改
2. section ID 不可删除/变更
3. prompt_type 不可变更

接受规则：post_compression_accuracy >= pre_compression_accuracy
         且 broken_sample_ids 为空。
"""

from __future__ import annotations

import copy
from typing import Any

from ..patch.types import CompressionReport
from ..data.sample import SampleBatch, SampleSet
from ..prompt.structured_prompt import PromptSection, StructuredPrompt


class CompressionExecutor:
    """真实压缩执行器。"""

    def __init__(self, model_client: Any = None) -> None:
        self.model_client = model_client

    def compress_if_needed(
        self,
        prompt: StructuredPrompt,
        line_limit: int,
        char_limit: int,
        batch: SampleBatch,
        sample_set: SampleSet,
        mode: str = "extraction",
        extraction_executor: Any = None,
        evaluation_executor: Any = None,
        analysis_executor: Any = None,
        extraction_results: list | None = None,
        extraction_prompt: StructuredPrompt | None = None,
        pre_compression_eval_records: list | None = None,
        pre_compression_analysis_results: list | None = None,
    ) -> tuple[StructuredPrompt, CompressionReport]:
        """按需压缩 prompt。

        Args:
            prompt: 待压缩的 StructuredPrompt。
            line_limit: 行数上限。
            char_limit: 字符数上限。
            batch: 抽样批次。
            sample_set: 样本集合。
            mode: 压缩模式，"extraction" 或 "analysis"。
            extraction_executor: extraction 模式下的抽取执行器。
            evaluation_executor: extraction 模式下的评估执行器。
            analysis_executor: analysis 模式下的分析执行器。
            extraction_results: analysis 模式下复用的抽取结果。
            extraction_prompt: analysis 模式下复用的抽取 prompt。
            pre_compression_eval_records: 压缩前的评估记录（extraction 模式）。
            pre_compression_analysis_results: 压缩前的分析结果（analysis 模式）。

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

        # 3. 获取压缩前准确率
        if mode == "extraction" and pre_compression_eval_records is not None:
            correct = sum(1 for r in pre_compression_eval_records if r.status == "correct")
            total = len(pre_compression_eval_records)
            report.pre_compression_accuracy = correct / total if total > 0 else 0.0
        elif mode == "analysis" and pre_compression_analysis_results is not None:
            correct = sum(1 for r in pre_compression_analysis_results if r.analysis_correct)
            total = len(pre_compression_analysis_results)
            report.pre_compression_accuracy = correct / total if total > 0 else 0.0

        # 4. 创建压缩后的 prompt
        compressed = self._create_compressed_prompt(prompt)

        # 5. 验证约束
        warnings = self._verify_constraints(prompt, compressed)
        report.warnings = warnings
        if warnings:
            # 约束被违反，拒绝
            report.accepted = False
            report.rejected_reason = "CONSTRAINT_VIOLATION"
            report.compressed_prompt_id = compressed.id
            comp_md = compressed.to_markdown()
            report.line_count_after = len(comp_md.splitlines())
            report.char_count_after = len(comp_md)
            return prompt, report

        # 6. 统计压缩后大小
        comp_md = compressed.to_markdown()
        comp_lines = len(comp_md.splitlines())
        comp_chars = len(comp_md)
        report.line_count_after = comp_lines
        report.char_count_after = comp_chars
        report.compressed_prompt_id = compressed.id

        # 7. 运行回归测试
        if mode == "extraction":
            if extraction_executor is None or evaluation_executor is None:
                report.accepted = False
                report.rejected_reason = "NO_EXECUTORS"
                return prompt, report
            post_acc, broken, fixed, _ = self._run_extraction_regression(
                compressed, batch, sample_set, extraction_executor,
                evaluation_executor, pre_compression_eval_records or [],
            )
        else:  # analysis
            if analysis_executor is None:
                report.accepted = False
                report.rejected_reason = "NO_EXECUTORS"
                return prompt, report
            post_acc, broken, fixed, _ = self._run_analysis_regression(
                compressed, batch, sample_set, analysis_executor,
                extraction_prompt, extraction_results or [],
                pre_compression_analysis_results or [],
            )

        report.post_compression_accuracy = post_acc
        report.broken_sample_ids = broken
        report.fixed_sample_ids = fixed

        # 8. 接受/拒绝
        pre_acc = report.pre_compression_accuracy or 0.0
        if post_acc >= pre_acc and not broken:
            report.accepted = True
            # 检查是否仍超限
            if comp_lines > line_limit or comp_chars > char_limit:
                report.still_over_limit = True
            return compressed, report
        else:
            report.accepted = False
            if post_acc < pre_acc:
                report.rejected_reason = "ACCURACY_DROP"
            else:
                report.rejected_reason = "BROKEN_SAMPLES"
            return prompt, report

    # ------------------------------------------------------------------
    # 压缩策略
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
            # 跳过连续空行（只保留第一个）
            if is_empty and prev_was_empty:
                continue
            # 跳过与前一行完全相同的行
            if stripped == prev_line and not is_empty:
                continue
            result.append(stripped)
            prev_line = stripped
            prev_was_empty = is_empty
        # 去除首尾空行
        while result and result[0] == "":
            result.pop(0)
        while result and result[-1] == "":
            result.pop()
        return "\n".join(result)

    def _create_compressed_prompt(self, prompt: StructuredPrompt) -> StructuredPrompt:
        """创建压缩后的 prompt。"""
        # 深拷贝 sections
        new_sections = copy.deepcopy(prompt.sections)

        # 递归压缩所有 mutable section 的 content
        def _compress_section(section: PromptSection) -> None:
            if section.mutable and section.content:
                section.content = self._compress_content(section.content)
            # 压缩 bullets 中的重复项
            if section.bullets:
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
            raw_markdown="",  # placeholder
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
        # 检查 immutable section 内容未变
        orig_sections = {s.id: s for s in self._flatten_sections(original.sections)}
        comp_sections = {s.id: s for s in self._flatten_sections(compressed.sections)}
        for sid, orig_sec in orig_sections.items():
            comp_sec = comp_sections.get(sid)
            if comp_sec is None:
                warnings.append(f"section {sid} was deleted")
            elif not orig_sec.mutable and orig_sec.content != comp_sec.content:
                warnings.append(f"immutable section {sid} content was modified")
        return warnings

    # ------------------------------------------------------------------
    # 回归测试
    # ------------------------------------------------------------------

    def _run_extraction_regression(
        self,
        compressed_prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        extraction_executor: Any,
        evaluation_executor: Any,
        pre_eval_records: list,
    ) -> tuple[float, list[str], list[str], list]:
        """运行 extraction 回归测试。"""
        # 用压缩后的 prompt 重新抽取
        results = extraction_executor.execute(
            prompt=compressed_prompt, batch=batch, sample_set=sample_set,
        )
        # 评估
        eval_records = evaluation_executor.evaluate_batch(results, sample_set)

        # 与压缩前评估对比
        pre_eval_map = {r.sample_id: r for r in pre_eval_records}
        post_eval_map = {r.sample_id: r for r in eval_records}

        broken: list[str] = []
        fixed: list[str] = []
        for sample_id in batch.sample_ids:
            pre = pre_eval_map.get(sample_id)
            post = post_eval_map.get(sample_id)
            if pre is None or post is None:
                continue
            pre_correct = pre.status == "correct"
            post_correct = post.status == "correct"
            if pre_correct and not post_correct:
                broken.append(sample_id)
            elif not pre_correct and post_correct:
                fixed.append(sample_id)

        # 计算准确率
        pre_correct_count = sum(1 for r in pre_eval_records if r.status == "correct")
        post_correct_count = sum(1 for r in eval_records if r.status == "correct")
        total = len(eval_records)
        pre_acc = pre_correct_count / total if total > 0 else 0.0
        post_acc = post_correct_count / total if total > 0 else 0.0

        # 返回 post_acc 作为压缩后准确率，pre_acc 仅用于参考
        _ = pre_acc  # noqa: F841
        return post_acc, broken, fixed, eval_records

    def _run_analysis_regression(
        self,
        compressed_prompt: StructuredPrompt,
        batch: SampleBatch,
        sample_set: SampleSet,
        analysis_executor: Any,
        extraction_prompt: StructuredPrompt | None,
        extraction_results: list,
        pre_analysis_results: list,
    ) -> tuple[float, list[str], list[str], list]:
        """运行 analysis 回归测试。"""
        # 用压缩后的 prompt 重新分析
        results = analysis_executor.execute_batch(
            analysis_prompt=compressed_prompt,
            extraction_prompt=extraction_prompt,
            extraction_results=extraction_results,
            sample_set=sample_set,
        )

        # 对比
        pre_map = {r.sample_id: r for r in pre_analysis_results}
        post_map = {r.sample_id: r for r in results}

        broken: list[str] = []
        fixed: list[str] = []
        for sample_id in batch.sample_ids:
            pre = pre_map.get(sample_id)
            post = post_map.get(sample_id)
            if pre is None or post is None:
                continue
            if pre.analysis_correct and not post.analysis_correct:
                broken.append(sample_id)
            elif not pre.analysis_correct and post.analysis_correct:
                fixed.append(sample_id)

        pre_correct = sum(1 for r in pre_analysis_results if r.analysis_correct)
        post_correct = sum(1 for r in results if r.analysis_correct)
        total = len(results)
        pre_acc = pre_correct / total if total > 0 else 0.0
        post_acc = post_correct / total if total > 0 else 0.0

        _ = pre_acc  # noqa: F841
        return post_acc, broken, fixed, results
