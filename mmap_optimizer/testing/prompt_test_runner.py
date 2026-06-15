from __future__ import annotations

import json
from dataclasses import dataclass

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.model.client import ModelClient
from mmap_optimizer.orchestration.executor import map_ordered
from mmap_optimizer.orchestration.records import RunRecord
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.version import PromptVersion


@dataclass
class PromptTestRunResult:
    runs: list[RunRecord]
    evaluations: list[EvaluationRecord]


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
        def run_one(sample: Sample) -> tuple[RunRecord, EvaluationRecord]:
            messages = [
                {"role": "system", "content": rendered.text},
                {
                    "role": "user",
                    "content": {
                        "sample_id": sample.id,
                        "text_context": sample.text_context,
                        "structured_context": sample.structured_context,
                        "mock_output": sample.metadata.get("mock_output"),
                        "mock_prompt_outputs": sample.metadata.get("mock_prompt_outputs", []),
                    },
                },
            ]
            sample_assets = [assets[asset_id] for asset_id in sample.asset_ids if asset_id in assets]
            gt = ground_truths.get(sample.ground_truth_id)
            vote_mode = self.enable_voting and (gt is None or gt.primary_answer is None)
            raw_outputs: list[str] = []
            rounds = max(1, self.vote_rounds if vote_mode else 1)
            for vote_index in range(rounds):
                if vote_mode:
                    messages[-1]["content"]["vote_round"] = vote_index + 1
                response = self.model_client.complete_multimodal(
                    messages,
                    sample_assets,
                    model_config=self.model_config,
                )
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
            try:
                run.parsed_output = json.loads(raw_outputs[0])
            except Exception:
                run.parsed_output = None
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
            return run, evaluation

        for run, evaluation in map_ordered(samples, run_one, max_workers=self.max_workers):
            runs.append(run)
            evals.append(evaluation)
        return PromptTestRunResult(runs=runs, evaluations=evals)
