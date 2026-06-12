from __future__ import annotations

import json
from dataclasses import dataclass

from mmap_optimizer.dataset.sample import GroundTruth, Sample, SampleAsset
from mmap_optimizer.evaluation.evaluator import EvaluationRecord, Evaluator
from mmap_optimizer.model.client import ModelClient
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

    def __init__(self, *, model_client: ModelClient, evaluator: Evaluator, model_id: str = "mock-model", model_config: dict | None = None):
        self.model_client = model_client
        self.evaluator = evaluator
        self.model_id = model_id
        self.model_config = model_config or {"model": model_id}

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
        for sample in samples:
            messages = [
                {"role": "system", "content": rendered.text},
                {
                    "role": "user",
                    "content": {
                        "sample_id": sample.id,
                        "text_context": sample.text_context,
                        "mock_output": sample.metadata.get("mock_output"),
                        "mock_prompt_outputs": sample.metadata.get("mock_prompt_outputs", []),
                    },
                },
            ]
            response = self.model_client.complete_multimodal(
                messages,
                [assets[asset_id] for asset_id in sample.asset_ids if asset_id in assets],
                model_config=self.model_config,
            )
            run = RunRecord(
                id=f"run_{round_id}_{run_type}{suffix}_{sample.id}",
                round_id=round_id,
                run_type=run_type,
                sample_id=sample.id,
                prompt_version_id=prompt.id,
                rendered_prompt_hash=rendered.text_hash,
                model_id=self.model_id,
                raw_output=response.raw_output,
            )
            try:
                run.parsed_output = json.loads(response.raw_output)
            except Exception:
                run.parsed_output = None
            gt = ground_truths[sample.ground_truth_id]
            evaluation = self.evaluator.evaluate(
                round_id=round_id,
                run_id=run.id,
                sample_id=sample.id,
                raw_output=response.raw_output,
                ground_truth=gt,
                contract=contract,
            )
            runs.append(run)
            evals.append(evaluation)
        return PromptTestRunResult(runs=runs, evaluations=evals)
