from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from mmap_optimizer.analysis.parser import parse_analysis_output_with_repair
from mmap_optimizer.compression.report import CompressionReport
from mmap_optimizer.compression.semantic import SemanticCompressionEngine
from mmap_optimizer.core.enums import PromptVersionType, RunType
from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.patch.applier import PatchApplier
from mmap_optimizer.patch.schema import Patch
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptSection
from mmap_optimizer.prompt.version import PromptVersion
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.testing.prompt_test_runner import PromptTestRunner


class CompressionEngine:
    """Line-budget compression with strict behavior-preservation gates.

    The engine is intentionally conservative: it only rewrites one mutable,
    compressible section per attempt and accepts the compressed PromptVersion
    only when every behavior-suite sample keeps the same normalized prediction
    and schema/parse status as the baseline run.
    """

    EXCLUDED_SECTION_IDS = {"output_schema", "analysis_output_schema"}
    COMPRESSIBILITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}

    def __init__(
        self,
        *,
        model_client: ModelClient,
        evaluator: Evaluator,
        model_id: str = "mock-model",
        model_config: dict | None = None,
        enable_llm_compression: bool = False,
        enable_json_repair: bool = False,
        json_repair_max_attempts: int = 1,
    ):
        self.model_client = model_client
        self.evaluator = evaluator
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}
        self.enable_llm_compression = enable_llm_compression
        self.enable_json_repair = enable_json_repair
        self.json_repair_max_attempts = json_repair_max_attempts

    def compress_if_needed(
        self,
        *,
        round_id: str,
        prompt: PromptVersion,
        line_budget: int | None,
        samples: list[Sample],
        assets: dict[str, SampleAsset],
        ground_truths: dict[str, GroundTruth],
        contract: OutputSchemaContract,
        base_evaluations: list[EvaluationRecord],
        token_budget: int | None = None,
    ) -> tuple[PromptVersion, CompressionReport, list, list[EvaluationRecord]]:
        prompt_type_value = getattr(prompt.prompt_type, "value", str(prompt.prompt_type))
        rendered_text = prompt.render().text
        before_lines = self._line_count(rendered_text)
        before_tokens = self._token_count(rendered_text)
        line_exceeded = line_budget is not None and before_lines > line_budget
        token_exceeded = token_budget is not None and before_tokens > token_budget
        report = CompressionReport(
            id=f"compression_{round_id}_{prompt_type_value}",
            round_id=round_id,
            prompt_type=prompt_type_value,
            prompt_version_before_id=prompt.id,
            triggered=False,
            reason="LINE_BUDGET_NOT_CONFIGURED" if line_budget is None and token_budget is None else ("TOKEN_BUDGET_EXCEEDED" if token_exceeded else ("LINE_BUDGET_EXCEEDED" if line_exceeded else "WITHIN_BUDGET")),
            line_count_before=before_lines,
            line_budget=line_budget,
            token_count_before=before_tokens,
            token_budget=token_budget,
        )
        if not (line_exceeded or token_exceeded):
            return prompt, report, [], []

        report.triggered = True
        report.reason = "TOKEN_BUDGET_EXCEEDED" if token_exceeded else "LINE_BUDGET_EXCEEDED"
        candidates = self._candidate_sections(prompt)
        report.candidate_sections = [
            {
                "section_id": section.id,
                "line_count": self._line_count(section.content),
                "token_count": self._token_count(section.content),
                "compressibility": section.compressibility,
                "priority": section.priority,
            }
            for section in candidates
        ]
        if not candidates:
            report.failure_reason = "NO_COMPRESSIBLE_SECTION"
            return prompt, report, [], []

        baseline_by_sample = {evaluation.sample_id: evaluation for evaluation in base_evaluations}
        behavior_samples = [sample for sample in samples if sample.id in baseline_by_sample]
        if not behavior_samples:
            report.failure_reason = "NO_BEHAVIOR_SUITE"
            return prompt, report, [], []

        all_runs = []
        all_evaluations: list[EvaluationRecord] = []
        for section in candidates:
            compressed_content, semantic_failure = self._compression_candidate_content(section)
            if semantic_failure is not None:
                report.rejected_sections.append({"section_id": section.id, "reason": semantic_failure})
                continue
            if compressed_content.strip() == section.content.strip() or not compressed_content.strip():
                continue
            patch = self._build_patch(round_id, prompt, section, compressed_content, baseline_by_sample)
            candidate_prompt = PatchApplier().apply(
                prompt,
                patch,
                new_version=prompt.version + 1,
                version_type=PromptVersionType.COMPRESSION,
            )
            candidate_prompt.prompt_ir = replace(
                candidate_prompt.prompt_ir,
                compression_patch_ids=[*prompt.prompt_ir.compression_patch_ids, patch.id],
            )
            candidate_prompt.version_type = PromptVersionType.COMPRESSION
            run_result = PromptTestRunner(
                model_client=self.model_client,
                evaluator=self.evaluator,
                model_id=self.model_id,
                model_config=self.model_config,
            ).run(
                round_id=round_id,
                run_type=RunType.COMPRESSION_BEHAVIOR_TEST.value,
                prompt=candidate_prompt,
                samples=behavior_samples,
                assets=assets,
                ground_truths=ground_truths,
                contract=contract,
                run_id_suffix=section.id,
            )
            all_runs.extend(run_result.runs)
            all_evaluations.extend(run_result.evaluations)
            behavior_failure = self._behavior_failure(baseline_by_sample, run_result.evaluations)
            if behavior_failure is not None:
                report.rejected_sections.append({"section_id": section.id, "reason": behavior_failure})
                continue
            candidate_text = candidate_prompt.render().text
            after_lines = self._line_count(candidate_text)
            after_tokens = self._token_count(candidate_text)
            if after_lines >= before_lines:
                report.rejected_sections.append({"section_id": section.id, "reason": "NO_LINE_REDUCTION"})
                continue
            report.accepted = True
            report.compression_patch_id = patch.id
            report.prompt_version_after_id = candidate_prompt.id
            report.compressed_section_id = section.id
            report.line_count_after = after_lines
            report.semantic_check_passed = True
            report.behavior_check_passed = True
            report.line_reduction = before_lines - after_lines
            report.token_count_after = after_tokens
            report.token_reduction = before_tokens - after_tokens
            return candidate_prompt, report, all_runs, all_evaluations

        report.failure_reason = "NO_SAFE_COMPRESSION_CANDIDATE"
        return prompt, report, all_runs, all_evaluations


    def compress_analysis_if_needed(
        self,
        *,
        round_id: str,
        prompt: PromptVersion,
        line_budget: int | None,
        error_evaluations: list[EvaluationRecord],
        sample_metadata: dict[str, dict[str, Any]],
        base_runs: list[RunRecord],
        token_budget: int | None = None,
    ) -> tuple[PromptVersion, CompressionReport, list[RunRecord], list[EvaluationRecord]]:
        prompt_type_value = getattr(prompt.prompt_type, "value", str(prompt.prompt_type))
        rendered_text = prompt.render().text
        before_lines = self._line_count(rendered_text)
        before_tokens = self._token_count(rendered_text)
        line_exceeded = line_budget is not None and before_lines > line_budget
        token_exceeded = token_budget is not None and before_tokens > token_budget
        report = CompressionReport(
            id=f"compression_{round_id}_{prompt_type_value}",
            round_id=round_id,
            prompt_type=prompt_type_value,
            prompt_version_before_id=prompt.id,
            triggered=False,
            reason="LINE_BUDGET_NOT_CONFIGURED" if line_budget is None and token_budget is None else ("TOKEN_BUDGET_EXCEEDED" if token_exceeded else ("LINE_BUDGET_EXCEEDED" if line_exceeded else "WITHIN_BUDGET")),
            line_count_before=before_lines,
            line_budget=line_budget,
            token_count_before=before_tokens,
            token_budget=token_budget,
        )
        if not (line_exceeded or token_exceeded):
            return prompt, report, [], []

        report.triggered = True
        report.reason = "TOKEN_BUDGET_EXCEEDED" if token_exceeded else "LINE_BUDGET_EXCEEDED"
        candidates = self._candidate_sections(prompt)
        report.candidate_sections = [
            {
                "section_id": section.id,
                "line_count": self._line_count(section.content),
                "token_count": self._token_count(section.content),
                "compressibility": section.compressibility,
                "priority": section.priority,
            }
            for section in candidates
        ]
        if not candidates:
            report.failure_reason = "NO_COMPRESSIBLE_SECTION"
            return prompt, report, [], []

        baseline_by_sample = {run.sample_id: run for run in base_runs if run.sample_id}
        behavior_evaluations = [evaluation for evaluation in error_evaluations if evaluation.sample_id in baseline_by_sample]
        if not behavior_evaluations:
            report.failure_reason = "NO_BEHAVIOR_SUITE"
            return prompt, report, [], []

        all_runs: list[RunRecord] = []
        for section in candidates:
            compressed_content, semantic_failure = self._compression_candidate_content(section)
            if semantic_failure is not None:
                report.rejected_sections.append({"section_id": section.id, "reason": semantic_failure})
                continue
            if compressed_content.strip() == section.content.strip() or not compressed_content.strip():
                continue
            patch = self._build_patch(round_id, prompt, section, compressed_content, baseline_by_sample)
            candidate_prompt = PatchApplier().apply(
                prompt,
                patch,
                new_version=prompt.version + 1,
                version_type=PromptVersionType.COMPRESSION,
            )
            candidate_prompt.prompt_ir = replace(
                candidate_prompt.prompt_ir,
                compression_patch_ids=[*prompt.prompt_ir.compression_patch_ids, patch.id],
            )
            candidate_prompt.version_type = PromptVersionType.COMPRESSION
            candidate_runs = self._run_analysis_behavior_suite(
                round_id=round_id,
                prompt=candidate_prompt,
                evaluations=behavior_evaluations,
                sample_metadata=sample_metadata,
                run_id_suffix=section.id,
            )
            all_runs.extend(candidate_runs)
            behavior_failure = self._analysis_behavior_failure(baseline_by_sample, candidate_runs)
            if behavior_failure is not None:
                report.rejected_sections.append({"section_id": section.id, "reason": behavior_failure})
                continue
            candidate_text = candidate_prompt.render().text
            after_lines = self._line_count(candidate_text)
            after_tokens = self._token_count(candidate_text)
            if after_lines >= before_lines:
                report.rejected_sections.append({"section_id": section.id, "reason": "NO_LINE_REDUCTION"})
                continue
            report.accepted = True
            report.compression_patch_id = patch.id
            report.prompt_version_after_id = candidate_prompt.id
            report.compressed_section_id = section.id
            report.line_count_after = after_lines
            report.semantic_check_passed = True
            report.behavior_check_passed = True
            report.line_reduction = before_lines - after_lines
            report.token_count_after = after_tokens
            report.token_reduction = before_tokens - after_tokens
            return candidate_prompt, report, all_runs, []

        report.failure_reason = "NO_SAFE_COMPRESSION_CANDIDATE"
        return prompt, report, all_runs, []

    def _candidate_sections(self, prompt: PromptVersion) -> list[PromptSection]:
        sections = []
        for section in prompt.prompt_ir.sections:
            if section.id in self.EXCLUDED_SECTION_IDS:
                continue
            if section.mutability == "frozen" or section.compressibility == "none":
                continue
            if not section.rendering_enabled or not section.content.strip():
                continue
            sections.append(section)
        return sorted(sections, key=self._candidate_score, reverse=True)

    def _candidate_score(self, section: PromptSection) -> tuple[int, int]:
        return (self.COMPRESSIBILITY_WEIGHT.get(section.compressibility, 0), self._line_count(section.content))

    def _build_patch(
        self,
        round_id: str,
        prompt: PromptVersion,
        section: PromptSection,
        compressed_content: str,
        baseline_by_sample: dict[str, Any],
    ) -> Patch:
        prompt_type_value = getattr(prompt.prompt_type, "value", str(prompt.prompt_type))
        return Patch(
            id=f"patch_{round_id}_compression_{section.id}",
            type="compression_patch",
            status="candidate",
            target_prompt_type=prompt_type_value,
            base_version_id=prompt.id,
            section_id=section.id,
            operation_type="COMPRESS_SECTION",
            operation_mode="replace_section",
            intent_name=f"compress_{section.id}",
            intent_description="Reduce prompt lines while preserving baseline behavior.",
            patch_text=compressed_content,
            rationale="Line-budget compression selected this mutable compressible section.",
            source_sample_ids=list(baseline_by_sample),
        )

    def _compression_candidate_content(self, section: PromptSection) -> tuple[str, str | None]:
        deterministic = self._compress_content(section.content)
        if deterministic.strip() != section.content.strip() and deterministic.strip():
            return deterministic, None
        if not self.enable_llm_compression:
            return deterministic, None
        semantic = SemanticCompressionEngine(self.model_client, self.model_config).prune_section(
            section_header=section.name or section.id,
            section_content=section.content,
        )
        if not semantic.semantic_valid:
            return section.content, semantic.reason or "SEMANTIC_COMPRESSION_REJECTED"
        return semantic.content, None

    def _behavior_failure(self, baseline_by_sample: dict[str, EvaluationRecord], candidate_evaluations: list[EvaluationRecord]) -> str | None:
        for candidate in candidate_evaluations:
            baseline = baseline_by_sample.get(candidate.sample_id)
            if baseline is None:
                return f"MISSING_BASELINE:{candidate.sample_id}"
            if candidate.overall_status in {"parse_error", "schema_error"}:
                return f"FORMAT_REGRESSION:{candidate.sample_id}"
            if baseline.schema_valid and not candidate.schema_valid:
                return f"SCHEMA_REGRESSION:{candidate.sample_id}"
            if candidate.normalized_prediction != baseline.normalized_prediction:
                return f"PREDICTION_CHANGED:{candidate.sample_id}"
            if candidate.overall_status != baseline.overall_status:
                return f"STATUS_CHANGED:{candidate.sample_id}"
        return None


    def _run_analysis_behavior_suite(
        self,
        *,
        round_id: str,
        prompt: PromptVersion,
        evaluations: list[EvaluationRecord],
        sample_metadata: dict[str, dict[str, Any]],
        run_id_suffix: str,
    ) -> list[RunRecord]:
        rendered = prompt.render()
        runs: list[RunRecord] = []
        for evaluation in evaluations:
            metadata = sample_metadata.get(evaluation.sample_id, {})
            messages = [
                {"role": "system", "content": rendered.text},
                {
                    "role": "user",
                    "content": json.dumps({
                        "sample_id": evaluation.sample_id,
                        "evaluation": evaluation.__dict__,
                        "mock_output": metadata.get("mock_analysis_output"),
                    }, ensure_ascii=False),
                },
            ]
            response = self.model_client.complete(messages, model_config=self.model_config)
            analysis_run = RunRecord(
                id=f"run_{round_id}_analysis_compression_{run_id_suffix}_{evaluation.sample_id}",
                round_id=round_id,
                run_type="analysis_compression_behavior_test",
                sample_id=evaluation.sample_id,
                prompt_version_id=prompt.id,
                rendered_prompt_hash=rendered.text_hash,
                model_id=self.model_id,
                raw_output=response.raw_output,
            )
            parse_result = parse_analysis_output_with_repair(
                response.raw_output,
                repair_client=self.model_client,
                repair_model_config=self.model_config,
                enable_llm_repair=self.enable_json_repair,
                max_attempts=self.json_repair_max_attempts,
            )
            analysis_run.parsed_output = parse_result.parsed
            if not parse_result.parse_success:
                analysis_run.success = False
                analysis_run.error_type = "PARSE_ERROR"
            elif not parse_result.schema_valid:
                analysis_run.success = False
                analysis_run.error_type = "SCHEMA_ERROR"
            runs.append(analysis_run)
        return runs

    def _analysis_behavior_failure(self, baseline_by_sample: dict[str, RunRecord], candidate_runs: list[RunRecord]) -> str | None:
        for candidate in candidate_runs:
            baseline = baseline_by_sample.get(candidate.sample_id)
            if baseline is None:
                return f"MISSING_BASELINE:{candidate.sample_id}"
            if baseline.success and not candidate.success:
                return f"ANALYSIS_FORMAT_REGRESSION:{candidate.sample_id}"
            if candidate.parsed_output != baseline.parsed_output:
                return f"ANALYSIS_OUTPUT_CHANGED:{candidate.sample_id}"
        return None

    def _compress_content(self, content: str) -> str:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        seen = set()
        compressed: list[str] = []
        for line in lines:
            if line in seen:
                continue
            seen.add(line)
            compressed.append(line)
        return "\n".join(compressed)

    def _line_count(self, text: str) -> int:
        if not text:
            return 0
        return len(text.splitlines())

    def _token_count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)
