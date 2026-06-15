from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.logging import get_logger, log_stage
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.orchestration.executor import map_ordered
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.version import PromptVersion

logger = get_logger(__name__)


@dataclass
class PromptTestRunResult:
    runs: list[RunRecord]
    evaluations: list[EvaluationRecord]


FEWSHOT_SECTION_ID = "few_shot_examples"


def _extract_fewshot_asset_ids(prompt: PromptVersion, samples: list[Sample]) -> list[str]:
    """Extract few-shot example asset_ids from prompt conservatively.

    This function looks for few-shot asset_ids in:
    1. prompt.prompt_ir.global_constraints["fewshot_asset_ids"]
    2. prompt.prompt_ir.global_constraints["asset_ids"]
    3. section.constraints["fewshot_asset_ids"] for few-shot sections
    4. section.constraints["asset_ids"] for few-shot sections
    5. Parsed from few-shot section content (FEW_SHOT_SAMPLE:{sample_id} format)

    Returns a deduplicated list of asset_ids while preserving order.
    """
    asset_ids: list[str] = []
    seen: set[str] = set()
    sample_by_id = {s.id: s for s in samples}

    ir = getattr(prompt, "prompt_ir", None)
    if ir is not None:
        global_constraints = getattr(ir, "global_constraints", {}) or {}
        for key in ("fewshot_asset_ids", "asset_ids"):
            ids = global_constraints.get(key, [])
            if isinstance(ids, list):
                for asset_id in ids:
                    if asset_id not in seen:
                        seen.add(asset_id)
                        asset_ids.append(asset_id)

    if ir is not None:
        for section in getattr(ir, "sections", []) or []:
            if section.id == FEWSHOT_SECTION_ID:
                section_constraints = getattr(section, "constraints", {}) or {}
                for key in ("fewshot_asset_ids", "asset_ids"):
                    ids = section_constraints.get(key, [])
                    if isinstance(ids, list):
                        for asset_id in ids:
                            if asset_id not in seen:
                                seen.add(asset_id)
                                asset_ids.append(asset_id)

    fewshot_section = None
    if ir is not None:
        fewshot_section = ir.section_by_id(FEWSHOT_SECTION_ID)

    if fewshot_section is not None:
        content = fewshot_section.content or ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("FEW_SHOT_SAMPLE:"):
                sample_id = stripped.split(":", 1)[1].strip()
                if sample_id in sample_by_id:
                    sample = sample_by_id[sample_id]
                    for asset_id in sample.asset_ids:
                        if asset_id not in seen:
                            seen.add(asset_id)
                            asset_ids.append(asset_id)

    return asset_ids


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
        fewshot_asset_ids = _extract_fewshot_asset_ids(prompt, samples)
        fewshot_assets = [assets[asset_id] for asset_id in fewshot_asset_ids if asset_id in assets]

        def run_one(sample: Sample) -> tuple[RunRecord, EvaluationRecord]:
            sample_start_time = time.perf_counter()
            log_stage(logger, "sample_start", sample_id=sample.id, asset_count=len(sample.asset_ids), fewshot_asset_count=len(fewshot_asset_ids))
            user_payload = {
                "sample_id": sample.id,
                "text_context": sample.text_context,
                "structured_context": sample.structured_context,
                "mock_output": sample.metadata.get("mock_output"),
                "mock_prompt_outputs": sample.metadata.get("mock_prompt_outputs", []),
            }
            messages = [
                {"role": "system", "content": rendered.text},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
            sample_assets = [assets[asset_id] for asset_id in sample.asset_ids if asset_id in assets]
            all_assets = fewshot_assets + sample_assets
            gt = ground_truths.get(sample.ground_truth_id)
            vote_mode = self.enable_voting and (gt is None or gt.primary_answer is None)
            raw_outputs: list[str] = []
            rounds = max(1, self.vote_rounds if vote_mode else 1)
            try:
                for vote_index in range(rounds):
                    payload = dict(user_payload)
                    if vote_mode:
                        payload["vote_round"] = vote_index + 1
                    messages[-1]["content"] = json.dumps(payload, ensure_ascii=False)
                    log_stage(logger, "model_call_start", sample_id=sample.id, vote_index=vote_index)
                    call_start = time.perf_counter()
                    response = self.model_client.complete_multimodal(
                        messages,
                        all_assets,
                        model_config=self.model_config,
                    )
                    call_duration_ms = int((time.perf_counter() - call_start) * 1000)
                    log_stage(logger, "model_call_done", sample_id=sample.id, vote_index=vote_index, duration_ms=call_duration_ms, response_chars=len(response.raw_output) if response.raw_output else 0)
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
                log_stage(logger, "parse_start", sample_id=sample.id)
                try:
                    run.parsed_output = json.loads(raw_outputs[0])
                    log_stage(logger, "parse_done", sample_id=sample.id, status="ok")
                except Exception as exc:
                    run.parsed_output = None
                    logger.warning(f"[stage=parse_failed] sample_id={sample.id} error={type(exc).__name__}: {exc}")
                    log_stage(logger, "parse_done", sample_id=sample.id, status="failed")
                log_stage(logger, "evaluate_start", sample_id=sample.id)
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
                log_stage(logger, "evaluate_done", sample_id=sample.id, decision=evaluation.overall_status)
                sample_duration_ms = int((time.perf_counter() - sample_start_time) * 1000)
                log_stage(logger, "sample_done", sample_id=sample.id, duration_ms=sample_duration_ms, decision=evaluation.overall_status)
                return run, evaluation
            except Exception as exc:
                sample_duration_ms = int((time.perf_counter() - sample_start_time) * 1000)
                logger.exception(f"[stage=sample_failed] sample_id={sample.id} duration_ms={sample_duration_ms} error={type(exc).__name__}: {exc}")
                log_stage(logger, "sample_failed", sample_id=sample.id, duration_ms=sample_duration_ms, error=type(exc).__name__)
                raise

        for run, evaluation in map_ordered(samples, run_one, max_workers=self.max_workers):
            runs.append(run)
            evals.append(evaluation)
        return PromptTestRunResult(runs=runs, evaluations=evals)
