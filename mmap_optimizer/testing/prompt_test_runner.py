from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.logging import get_logger, log_stage
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.orchestration.executor import map_ordered
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.ir import PromptIR
from mmap_optimizer.prompt.renderer import PromptRenderer
from mmap_optimizer.prompt.version import PromptVersion

logger = get_logger(__name__)


@dataclass
class PromptTestRunResult:
    runs: list[RunRecord]
    evaluations: list[EvaluationRecord]


FEWSHOT_SECTION_ID = "few_shot_examples"


def _asset_to_image_part(asset: SampleAsset) -> dict[str, Any]:
    """Convert a SampleAsset to an OpenAI-compatible image_url content part."""
    if asset.local_path:
        path = Path(asset.local_path)
        mime = asset.mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        url = f"data:{mime};base64,{encoded}"
    elif asset.uri:
        url = asset.uri
    else:
        raise ValueError(f"Image asset {asset.id!r} must provide local_path or uri")
    image_url: dict[str, Any] = {"url": url}
    if asset.metadata and asset.metadata.get("openai_image_detail"):
        image_url["detail"] = asset.metadata["openai_image_detail"]
    return {"type": "image_url", "image_url": image_url}


def _parse_fewshot_slots(content: str) -> list[dict[str, Any]]:
    """Parse few-shot slots from section content.

    Each slot has: slot_index, source_sample_id, reasoning_text, final_output.
    """
    slots: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    section: str | None = None
    section_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("FEW_SHOT_SLOT:"):
            if current is not None:
                if section is not None:
                    current[section] = "\n".join(section_lines).strip()
                slots.append(current)
            try:
                slot_index = int(line.split(":", 1)[1])
            except (ValueError, IndexError):
                current = None
                section = None
                section_lines = []
                continue
            current = {"slot_index": slot_index, "source_sample_id": None, "reasoning_text": "", "final_output": ""}
            section = None
            section_lines = []
        elif line.startswith("FEW_SHOT_SAMPLE:") and current is not None:
            current["source_sample_id"] = line.split(":", 1)[1]
        elif line == "FEW_SHOT_REASONING:" and current is not None:
            if section is not None:
                current[section] = "\n".join(section_lines).strip()
            section = "reasoning_text"
            section_lines = []
        elif line == "FEW_SHOT_OUTPUT:" and current is not None:
            if section is not None:
                current[section] = "\n".join(section_lines).strip()
            section = "final_output"
            section_lines = []
        elif section is not None:
            section_lines.append(line)
    if current is not None:
        if section is not None:
            current[section] = "\n".join(section_lines).strip()
        slots.append(current)
    return slots


def _render_system_without_fewshot(prompt: PromptVersion) -> str:
    """Render the prompt text excluding the few-shot section.

    This produces the system message content when few-shot examples are
    injected as multi-turn user/assistant messages instead.
    """
    ir = prompt.prompt_ir
    sections = [
        s.clone_with_content(s.content, rendering_enabled=False) if s.id == FEWSHOT_SECTION_ID else s
        for s in ir.sections
    ]
    modified_ir = PromptIR(
        id=ir.id,
        prompt_type=ir.prompt_type,
        version=ir.version,
        output_schema_contract_id=ir.output_schema_contract_id,
        sections=sections,
        rendering_order=ir.rendering_order,
        include_section_markers=ir.include_section_markers,
        global_constraints=ir.global_constraints,
        parent_prompt_ir_id=ir.parent_prompt_ir_id,
        applied_patch_ids=ir.applied_patch_ids,
        compression_patch_ids=ir.compression_patch_ids,
    )
    rendered = PromptRenderer().render(modified_ir)
    return rendered.text


def _build_fewshot_messages(
    slots: list[dict[str, Any]],
    samples: list[Sample],
    assets: dict[str, SampleAsset],
) -> list[dict[str, Any]]:
    """Build multi-turn user/assistant messages from few-shot slots.

    Each slot becomes a user message (text + image content parts) followed by
    an assistant message (the expected output JSON).
    """
    sample_by_id = {s.id: s for s in samples}
    messages: list[dict[str, Any]] = []
    for slot in slots:
        sample_id = slot.get("source_sample_id")
        sample = sample_by_id.get(sample_id) if sample_id else None

        content_parts: list[dict[str, Any]] = []
        reasoning = slot.get("reasoning_text", "")
        sample_label = f"FEW_SHOT_SAMPLE:{sample_id}" if sample_id else "FEW_SHOT_SAMPLE:unknown"
        if reasoning:
            content_parts.append({"type": "text", "text": f"{sample_label}\n{reasoning}"})
        else:
            content_parts.append({"type": "text", "text": f"{sample_label}\n请从下面图片中抽取字段。"})

        if sample is not None:
            for asset_id in sample.asset_ids:
                asset = assets.get(asset_id)
                if asset is not None:
                    content_parts.append(_asset_to_image_part(asset))

        messages.append({"role": "user", "content": content_parts})

        output = slot.get("final_output", "")
        if output:
            try:
                parsed = json.loads(output)
                output_text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            except (json.JSONDecodeError, TypeError):
                output_text = output
        else:
            output_text = "{}"
        messages.append({"role": "assistant", "content": output_text})

    return messages


class PromptTestRunner:
    """Runs a concrete PromptVersion on samples and evaluates the outputs.

    This is shared by optimization batch inference, dynamic validation, patch tests,
    compression behavior tests, and future few-shot tests. Tests can remain
    deterministic by using MockModelClient metadata rules while still exercising the
    actual temporary PromptVersion rendering path.
    """

    def __init__(self, *, model_client: ModelClient, evaluator: Evaluator, model_id: str = "mock-model", model_config: dict | None = None, max_workers: int = 1, vote_rounds: int = 3, enable_voting: bool = True):
        self.model_client = model_client
        self.evaluator = evaluator
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}
        self.max_workers = max_workers
        self.vote_rounds = vote_rounds
        self.enable_voting = enable_voting

    def run(
        self,
        *,
        round_id: str,
        run_type: str,
        prompt: PromptVersion,
        samples: list[Sample],
        assets: dict[str, SampleAsset],
        ground_truths: dict[str, GroundTruth],
        contract: OutputSchemaContract,
        run_id_suffix: str | None = None,
    ) -> PromptTestRunResult:
        rendered = prompt.render()
        runs: list[RunRecord] = []
        evals: list[EvaluationRecord] = []
        suffix = f"_{run_id_suffix}" if run_id_suffix else ""

        # 解析 few-shot slots，构造多轮 messages
        fewshot_section = prompt.prompt_ir.section_by_id(FEWSHOT_SECTION_ID) if hasattr(prompt, "prompt_ir") else None
        fewshot_slots: list[dict[str, Any]] = []
        if fewshot_section is not None and fewshot_section.content and fewshot_section.content.strip():
            fewshot_slots = _parse_fewshot_slots(fewshot_section.content)

        if fewshot_slots:
            system_text = _render_system_without_fewshot(prompt)
            fewshot_messages = _build_fewshot_messages(fewshot_slots, samples, assets)
            log_stage(logger, "fewshot_multiturn_enabled", "启用 fewshot 多轮对话", slot_count=len(fewshot_slots), message_pairs=len(fewshot_messages))
        else:
            system_text = rendered.text
            fewshot_messages = []
            log_stage(logger, "fewshot_assets_extracted", "无 fewshot 资源", fewshot_count=0, fewshot_asset_ids=[])

        total_samples = len(samples)

        def run_one(indexed_sample: tuple[int, Sample]) -> tuple[RunRecord, EvaluationRecord]:
            sample_index, sample = indexed_sample
            sample_start_time = time.perf_counter()
            log_stage(logger, "sample_start", "样本处理开始",
                      sample_id=sample.id, asset_count=len(sample.asset_ids),
                      fewshot_slot_count=len(fewshot_slots),
                      progress=f"{sample_index}/{total_samples}")
            user_payload = {
                "sample_id": sample.id,
                "text_context": sample.text_context,
                "structured_context": sample.structured_context,
                "mock_output": sample.metadata.get("mock_output"),
                "mock_prompt_outputs": sample.metadata.get("mock_prompt_outputs", []),
            }
            sample_assets = [assets[asset_id] for asset_id in sample.asset_ids if asset_id in assets]

            # 构造 messages：system + fewshot多轮 + 当前样本user
            base_messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_text},
            ]
            base_messages.extend(fewshot_messages)

            gt = ground_truths.get(sample.ground_truth_id)
            vote_mode = self.enable_voting and (gt is None or gt.primary_answer is None)
            raw_outputs: list[str] = []
            rounds = max(1, self.vote_rounds if vote_mode else 1)
            try:
                for vote_index in range(rounds):
                    payload = dict(user_payload)
                    if vote_mode:
                        payload["vote_round"] = vote_index + 1
                    messages = list(base_messages)
                    messages.append({"role": "user", "content": json.dumps(payload, ensure_ascii=False)})
                    log_stage(logger, "model_call_start", "模型调用开始",
                              sample_id=sample.id, vote_index=vote_index,
                              progress=f"{vote_index+1}/{rounds}",
                              message_count=len(messages))
                    call_start = time.perf_counter()
                    response = self.model_client.complete_multimodal(
                        messages,
                        sample_assets,
                        model_config=self.model_config,
                    )
                    call_duration_ms = int((time.perf_counter() - call_start) * 1000)
                    response_preview = (response.raw_output or "")[:120].replace("\n", "\\n") if response.raw_output else ""
                    log_stage(logger, "model_call_done", "模型调用完成",
                              sample_id=sample.id, vote_index=vote_index,
                              progress=f"{vote_index+1}/{rounds}",
                              duration_ms=call_duration_ms,
                              response_chars=len(response.raw_output) if response.raw_output else 0,
                              response_preview=response_preview)
                    raw_outputs.append(response.raw_output)
                run = RunRecord(
                    id=f"run_{round_id}_{run_type}{suffix}_{sample.id}",
                    round_id=round_id,
                    run_type=run_type,
                    sample_id=sample.id,
                    prompt_version_id=prompt.id,
                    rendered_prompt_hash=rendered.text_hash,
                    model_id=self.model_id,
                    raw_output=raw_outputs[0],
                )
                log_stage(logger, "parse_start", "解析开始", sample_id=sample.id)
                try:
                    run.parsed_output = json.loads(raw_outputs[0])
                    log_stage(logger, "parse_done", "解析完成", sample_id=sample.id, status="ok")
                except Exception as exc:
                    run.parsed_output = None
                    response_preview = (raw_outputs[0] or "")[:200].replace("\n", "\\n") if raw_outputs else ""
                    log_stage(logger, "parse_failed", "解析失败",
                              sample_id=sample.id,
                              error=f"{type(exc).__name__}: {exc}",
                              response_chars=len(raw_outputs[0]) if raw_outputs else 0,
                              response_preview=response_preview)
                    log_stage(logger, "parse_done", "解析完成", sample_id=sample.id, status="failed")
                log_stage(logger, "evaluate_start", "评估开始", sample_id=sample.id)
                if vote_mode:
                    evaluation = self.evaluator.evaluate_without_ground_truth(
                        round_id=round_id,
                        run_id=run.id,
                        sample_id=sample.id,
                        raw_outputs=raw_outputs,
                        contract=contract,
                    )
                else:
                    evaluation = self.evaluator.evaluate(
                        round_id=round_id,
                        run_id=run.id,
                        sample_id=sample.id,
                        raw_output=raw_outputs[0],
                        ground_truth=gt,
                        contract=contract,
                    )
                eval_extra = evaluation.extra or {}
                eval_kwargs = {"sample_id": sample.id, "decision": evaluation.overall_status}
                if eval_extra.get("no_ground_truth"):
                    eval_kwargs["vote_majority"] = eval_extra.get("vote_majority")
                    eval_kwargs["vote_confidence"] = eval_extra.get("vote_confidence")
                    eval_kwargs["parse_error_count"] = eval_extra.get("parse_errors", 0)
                log_stage(logger, "evaluate_done", "评估完成", **eval_kwargs)
                sample_duration_ms = int((time.perf_counter() - sample_start_time) * 1000)
                log_stage(logger, "sample_done", "样本处理完成",
                          sample_id=sample.id, duration_ms=sample_duration_ms,
                          decision=evaluation.overall_status,
                          progress=f"{sample_index}/{total_samples}")
                return run, evaluation
            except Exception as exc:
                sample_duration_ms = int((time.perf_counter() - sample_start_time) * 1000)
                log_stage(logger, "sample_failed", "样本处理失败",
                          sample_id=sample.id, duration_ms=sample_duration_ms,
                          error=type(exc).__name__,
                          progress=f"{sample_index}/{total_samples}")
                logger.exception(f"[stage=sample_failed] sample_id={sample.id} duration_ms={sample_duration_ms} error={type(exc).__name__}: {exc}")
                # Return a failed RunRecord + EvaluationRecord instead of raising
                run = RunRecord(
                    id=f"run_{round_id}_{run_type}{suffix}_{sample.id}",
                    round_id=round_id,
                    run_type=run_type,
                    sample_id=sample.id,
                    prompt_version_id=prompt.id,
                    rendered_prompt_hash=rendered.text_hash,
                    model_id=self.model_id,
                    raw_output=None,
                )
                evaluation = self.evaluator.evaluate_without_ground_truth(
                    round_id=round_id,
                    run_id=run.id,
                    sample_id=sample.id,
                    raw_outputs=[str(exc)],
                    contract=contract,
                )
                evaluation.overall_status = "ERROR"
                return run, evaluation

        batch_start_time = time.perf_counter()
        for run, evaluation in map_ordered(list(enumerate(samples, 1)), run_one, max_workers=self.max_workers):
            runs.append(run)
            evals.append(evaluation)
        batch_duration_ms = int((time.perf_counter() - batch_start_time) * 1000)
        log_stage(logger, "batch_done", "批次处理完成",
                  total_samples=len(samples), duration_ms=batch_duration_ms)
        return PromptTestRunResult(runs=runs, evaluations=evals)
