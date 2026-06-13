from __future__ import annotations

import argparse
import json
from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig, load_mapping, optimizer_config_from_mapping, validate_optimizer_config_mapping
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.core.scenario import (
    ScenarioValidationError,
    validate_scenario,
    list_scenarios,
    load_scenario,
    summaries_as_dicts,
    write_scenario_artifact_metadata,
)
from mmap_optimizer.dataset.loader import initial_sample_states, load_assets, load_ground_truths, load_samples
from mmap_optimizer.evaluation.evaluator import Evaluator
from mmap_optimizer.model.client import MockModelClient
from mmap_optimizer.model.factory import build_model_client
from mmap_optimizer.orchestration.optimizer_loop import OptimizerLoop
from mmap_optimizer.orchestration.round_runner import OptimizerState, RoundRunner
from mmap_optimizer.prompt.contract import OutputSchemaContract
from mmap_optimizer.prompt.health import check_prompt_health
from mmap_optimizer.prompt.initializer import initialize_prompt_from_file
from mmap_optimizer.prompt.snapshot import load_prompt_snapshot
from mmap_optimizer.storage.json_store import JsonStore


def _apply_scenario_args(args: argparse.Namespace) -> None:
    scenario_path = getattr(args, "scenario", None)
    if not scenario_path:
        return
    scenario = load_scenario(scenario_path)
    if getattr(args, "config", None) == "configs/optimizer.yaml":
        args.config = str(scenario.optimizer_config_path or scenario.root / "optimizer.yaml")
    if args.data_dir == "data":
        args.data_dir = str(scenario.data_dir)
    if args.extraction_prompt == "prompts/raw/extraction.txt":
        args.extraction_prompt = str(scenario.prompts_dir / "extraction.txt")
    if args.analysis_prompt == "prompts/raw/analysis.txt":
        args.analysis_prompt = str(scenario.prompts_dir / "analysis.txt")
    if args.extraction_schema == "schemas/extraction_output_schema.json":
        args.extraction_schema = str(scenario.schemas_dir / "extraction_output_schema.json")
    if args.analysis_schema == "schemas/analysis_output_schema.json":
        args.analysis_schema = str(scenario.schemas_dir / "analysis_output_schema.json")
    args.loaded_scenario_id = scenario.id


def _load_contract(path: Path, prompt_type: PromptType, contract_id: str) -> OutputSchemaContract:
    schema = json.loads(path.read_text(encoding="utf-8"))
    primary = schema.get("x-primary-answer-fields", ["result"])
    return OutputSchemaContract(id=contract_id, prompt_type=prompt_type, version=1, schema=schema, primary_answer_fields=primary)



def _build_state(args: argparse.Namespace) -> tuple[OptimizerState, OutputSchemaContract, OutputSchemaContract]:
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
    return state, extraction_contract, analysis_contract


def _print_run_result(metrics_records, summary) -> None:
    final_metrics = metrics_records[-1]
    print(json.dumps({
        "round_id": final_metrics.round_id,
        "completed_round_count": summary.completed_round_count,
        "batch_accuracy": final_metrics.batch_accuracy,
        "dynamic_validation_raw_accuracy": final_metrics.dynamic_validation_raw_accuracy,
        "final_extraction_prompt_version_id": summary.final_extraction_prompt_version_id,
    }, ensure_ascii=False))


def run_smoke(args: argparse.Namespace) -> None:
    _apply_scenario_args(args)
    state, _, _ = _build_state(args)
    config = OptimizerConfig(
        batch_size=args.batch_size,
        dynamic_validation_batch_size=args.dynamic_validation_batch_size,
        extraction_line_budget=args.extraction_line_budget,
        analysis_line_budget=args.analysis_line_budget,
        fewshot_enabled=args.fewshot_enabled,
        fewshot_max_rounds=args.fewshot_max_rounds,
        fewshot_max_slots=args.fewshot_max_slots,
        fewshot_min_accuracy_delta=args.fewshot_min_accuracy_delta,
    )
    store = JsonStore(args.run_dir)
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)
    _, metrics_records, summary = OptimizerLoop(runner=runner, store=store, config=config).run(state, max_rounds=args.rounds)
    _print_run_result(metrics_records, summary)


def run(args: argparse.Namespace) -> None:
    _apply_scenario_args(args)
    state, _, _ = _build_state(args)
    config = optimizer_config_from_mapping(load_mapping(args.config))
    if args.run_dir is not None:
        config.run_dir = args.run_dir
    if getattr(args, "loaded_scenario_id", None):
        config.scenario_id = args.loaded_scenario_id
    store = JsonStore(config.run_dir)
    extraction_client = build_model_client(config.extraction_model)
    optimizer_client = build_model_client(config.optimizer_model)
    runner = RoundRunner(
        extraction_client=extraction_client,
        optimizer_client=optimizer_client,
        evaluator=Evaluator(),
        store=store,
        config=config,
    )
    _, metrics_records, summary = OptimizerLoop(runner=runner, store=store, config=config).run(state, max_rounds=args.rounds)
    _print_run_result(metrics_records, summary)


def check_prompt(args: argparse.Namespace) -> None:
    _apply_scenario_args(args)
    extraction_contract = _load_contract(Path(args.extraction_schema), PromptType.EXTRACTION, "extraction_output_schema_v1")
    analysis_contract = _load_contract(Path(args.analysis_schema), PromptType.ANALYSIS, "analysis_output_schema_v1")
    prompts = {
        "extraction": initialize_prompt_from_file(args.extraction_prompt, PromptType.EXTRACTION, extraction_contract),
        "analysis": initialize_prompt_from_file(args.analysis_prompt, PromptType.ANALYSIS, analysis_contract),
    }
    reports = {name: check_prompt_health(prompt.prompt_ir) for name, prompt in prompts.items()}
    print(json.dumps(reports, default=lambda item: item.__dict__, ensure_ascii=False))
    if any(not report.ok for report in reports.values()):
        raise SystemExit(2)


def validate_config(args: argparse.Namespace) -> None:
    errors = validate_optimizer_config_mapping(load_mapping(args.config))
    payload = {"config": args.config, "valid": not errors, "errors": errors}
    print(json.dumps(payload, ensure_ascii=False))
    if errors:
        raise SystemExit(2)


def list_scenarios_command(args: argparse.Namespace) -> None:
    summaries = summaries_as_dicts(list_scenarios(args.scenarios_dir))
    if args.json:
        print(json.dumps(summaries, ensure_ascii=False))
        return
    for summary in summaries:
        print(f"{summary['id']}	{summary['task_type']}	{summary['path']}	{summary['description']}")


def validate_scenario_command(args: argparse.Namespace) -> None:
    try:
        validate_scenario(args.scenario, scenarios_dir=args.scenarios_dir)
        scenario = load_scenario(args.scenario, scenarios_dir=args.scenarios_dir, base_config_path=args.base_config)
    except (FileNotFoundError, ScenarioValidationError, ValueError) as exc:
        payload = {"valid": False, "scenario_id": args.scenario, "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False) if args.json else f"invalid: {exc}")
        raise SystemExit(2) from exc
    payload = {
        "valid": True,
        "scenario_id": scenario.id,
        "description": scenario.description,
        "task_type": scenario.task_type,
        "config_hash": scenario.config_hash,
        "config": scenario.config_mapping,
        "data_dir": str(scenario.data_dir),
        "prompts_dir": str(scenario.prompts_dir),
        "schemas_dir": str(scenario.schemas_dir),
        "artifact_metadata": scenario.artifact_metadata(),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True) if args.json else f"valid: {scenario.id}")


def write_scenario_metadata_command(args: argparse.Namespace) -> None:
    scenario = load_scenario(args.scenario, scenarios_dir=args.scenarios_dir, base_config_path=args.base_config)
    path = write_scenario_artifact_metadata(args.output_dir, scenario)
    print(json.dumps({"scenario_id": scenario.id, "artifact_path": str(path)}, ensure_ascii=False))


def active_prompt_path(run_dir: str | Path, prompt_name: str) -> Path:
    return Path(run_dir) / "active_prompts" / f"{prompt_name}.json"


def rollback_prompt(args: argparse.Namespace) -> None:
    store = JsonStore(args.run_dir)
    snapshot = load_prompt_snapshot(store, args.snapshot_id)
    prompt_name = args.prompt_name or snapshot.get("prompt_type") or snapshot.get("prompt_payload", {}).get("prompt_type", "prompt")
    destination = active_prompt_path(args.run_dir, str(prompt_name))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(snapshot.get("prompt_payload", snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rolled_back": True, "snapshot_id": args.snapshot_id, "active_prompt_path": str(destination)}, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="MMAP prompt optimizer MVP CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("run-smoke", help="Run a no-patch MVP round with mock model outputs from sample metadata.")
    smoke.add_argument("--scenario", default=None)
    smoke.add_argument("--data-dir", default="data")
    smoke.add_argument("--run-dir", default="runs")
    smoke.add_argument("--extraction-prompt", default="prompts/raw/extraction.txt")
    smoke.add_argument("--analysis-prompt", default="prompts/raw/analysis.txt")
    smoke.add_argument("--extraction-schema", default="schemas/extraction_output_schema.json")
    smoke.add_argument("--analysis-schema", default="schemas/analysis_output_schema.json")
    smoke.add_argument("--batch-size", type=int, default=24)
    smoke.add_argument("--dynamic-validation-batch-size", type=int, default=48)
    smoke.add_argument("--rounds", type=int, default=1)
    smoke.add_argument("--extraction-line-budget", type=int, default=None)
    smoke.add_argument("--analysis-line-budget", type=int, default=None)
    smoke.add_argument("--fewshot-enabled", action="store_true")
    smoke.add_argument("--fewshot-max-rounds", type=int, default=5)
    smoke.add_argument("--fewshot-max-slots", type=int, default=5)
    smoke.add_argument("--fewshot-min-accuracy-delta", type=float, default=0.0)
    smoke.set_defaults(func=run_smoke)

    run_parser = sub.add_parser("run", help="Run optimization with model clients from an optimizer config file.")
    run_parser.add_argument("--scenario", default=None)
    run_parser.add_argument("--config", default="configs/optimizer.yaml")
    run_parser.add_argument("--data-dir", default="data")
    run_parser.add_argument("--run-dir", default=None)
    run_parser.add_argument("--extraction-prompt", default="prompts/raw/extraction.txt")
    run_parser.add_argument("--analysis-prompt", default="prompts/raw/analysis.txt")
    run_parser.add_argument("--extraction-schema", default="schemas/extraction_output_schema.json")
    run_parser.add_argument("--analysis-schema", default="schemas/analysis_output_schema.json")
    run_parser.add_argument("--rounds", type=int, default=None)
    run_parser.set_defaults(func=run)

    check_parser = sub.add_parser("check-prompt", help="Validate prompt health before running optimization.")
    check_parser.add_argument("--scenario", default=None)
    check_parser.add_argument("--extraction-prompt", default="prompts/raw/extraction.txt")
    check_parser.add_argument("--analysis-prompt", default="prompts/raw/analysis.txt")
    check_parser.add_argument("--extraction-schema", default="schemas/extraction_output_schema.json")
    check_parser.add_argument("--analysis-schema", default="schemas/analysis_output_schema.json")
    check_parser.add_argument("--data-dir", default="data")
    check_parser.set_defaults(func=check_prompt)

    validate_parser = sub.add_parser("validate-config", help="Validate optimizer configuration without running optimization.")
    validate_parser.add_argument("--config", default="configs/optimizer.yaml")
    validate_parser.set_defaults(func=validate_config)

    list_scenarios_parser = sub.add_parser("list-scenarios", help="List valid scenario directories.")
    list_scenarios_parser.add_argument("--scenarios-dir", default="scenarios")
    list_scenarios_parser.add_argument("--json", action="store_true")
    list_scenarios_parser.set_defaults(func=list_scenarios_command)

    validate_scenario_parser = sub.add_parser("validate-scenario", help="Validate and load a scenario directory.")
    validate_scenario_parser.add_argument("scenario")
    validate_scenario_parser.add_argument("--scenarios-dir", default="scenarios")
    validate_scenario_parser.add_argument("--base-config", default="configs/optimizer.yaml")
    validate_scenario_parser.add_argument("--json", action="store_true")
    validate_scenario_parser.set_defaults(func=validate_scenario_command)

    scenario_metadata_parser = sub.add_parser("write-scenario-metadata", help="Write scenario artifact metadata for a scenario.")
    scenario_metadata_parser.add_argument("scenario")
    scenario_metadata_parser.add_argument("--scenarios-dir", default="scenarios")
    scenario_metadata_parser.add_argument("--base-config", default="configs/optimizer.yaml")
    scenario_metadata_parser.add_argument("--output-dir", required=True)
    scenario_metadata_parser.set_defaults(func=write_scenario_metadata_command)

    rollback_parser = sub.add_parser("rollback-prompt", help="Restore an active prompt from a saved snapshot.")
    rollback_parser.add_argument("--run-dir", default="runs")
    rollback_parser.add_argument("--snapshot-id", required=True)
    rollback_parser.add_argument("--prompt-name", default=None)
    rollback_parser.set_defaults(func=rollback_prompt)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
