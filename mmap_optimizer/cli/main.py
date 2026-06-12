from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.dataset.loader import initial_sample_states, load_assets, load_ground_truths, load_samples
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.orchestration.round_runner import OptimizerState, RoundRunner
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.initializer import initialize_prompt_from_file
from mmap_optimizer.storage.json_store import JsonStore


def _load_contract(path: Path, prompt_type: PromptType, contract_id: str) -> OutputSchemaContract:
    schema = json.loads(path.read_text(encoding="utf-8"))
    primary = schema.get("x-primary-answer-fields", ["result"])
    return OutputSchemaContract(id=contract_id, prompt_type=prompt_type, version=1, schema=schema, primary_answer_fields=primary)


def run_smoke(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    extraction_contract = _load_contract(Path(args.extraction_schema), PromptType.EXTRACTION, "extraction_output_schema_v1")
    analysis_contract = _load_contract(Path(args.analysis_schema), PromptType.ANALYSIS, "analysis_output_schema_v1")
    extraction_prompt = initialize_prompt_from_file(args.extraction_prompt, PromptType.EXTRACTION, extraction_contract)
    analysis_prompt = initialize_prompt_from_file(args.analysis_prompt, PromptType.ANALYSIS, analysis_contract)
    samples = load_samples(data_dir / "samples.jsonl")
    ground_truths = load_ground_truths(data_dir / "ground_truth.jsonl")
    assets = load_assets(data_dir / "assets.jsonl") if (data_dir / "assets.jsonl").exists() else {}
    state = OptimizerState(
        samples=samples, assets=assets, ground_truths=ground_truths, sample_states=initial_sample_states(samples),
        active_extraction_prompt=extraction_prompt, active_analysis_prompt=analysis_prompt,
        extraction_output_schema_contract=extraction_contract, analysis_output_schema_contract=analysis_contract,
    )
    config = OptimizerConfig(
        batch_size=args.batch_size,
        dynamic_validation_batch_size=args.dynamic_validation_batch_size,
        extraction_line_budget=args.extraction_line_budget,
        fewshot_enabled=args.fewshot_enabled,
        fewshot_max_rounds=args.fewshot_max_rounds,
        fewshot_max_slots=args.fewshot_max_slots,
        fewshot_min_accuracy_delta=args.fewshot_min_accuracy_delta,
    )
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=JsonStore(args.run_dir), config=config)
    _, metrics = runner.run_round(state, round_index=1)
    print(json.dumps({"round_id": metrics.round_id, "batch_accuracy": metrics.batch_accuracy, "dynamic_validation_raw_accuracy": metrics.dynamic_validation_raw_accuracy}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="MMAP prompt optimizer MVP CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("run-smoke", help="Run a no-patch MVP round with mock model outputs from sample metadata.")
    smoke.add_argument("--data-dir", default="data")
    smoke.add_argument("--run-dir", default="runs")
    smoke.add_argument("--extraction-prompt", default="prompts/raw/extraction.txt")
    smoke.add_argument("--analysis-prompt", default="prompts/raw/analysis.txt")
    smoke.add_argument("--extraction-schema", default="schemas/extraction_output_schema.json")
    smoke.add_argument("--analysis-schema", default="schemas/analysis_output_schema.json")
    smoke.add_argument("--batch-size", type=int, default=24)
    smoke.add_argument("--dynamic-validation-batch-size", type=int, default=48)
    smoke.add_argument("--extraction-line-budget", type=int, default=None)
    smoke.add_argument("--fewshot-enabled", action="store_true")
    smoke.add_argument("--fewshot-max-rounds", type=int, default=5)
    smoke.add_argument("--fewshot-max-slots", type=int, default=5)
    smoke.add_argument("--fewshot-min-accuracy-delta", type=float, default=0.0)
    smoke.set_defaults(func=run_smoke)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
