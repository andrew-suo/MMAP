from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mmap_optimizer.core.config import OptimizerConfig, load_mapping, optimizer_config_from_mapping, validate_optimizer_config_mapping
from mmap_optimizer.core.enums import PromptType
from mmap_optimizer.logging import get_logger, log_stage

logger = get_logger(__name__)
from mmap_optimizer.core.scenario import (
    DEFAULT_SCENARIOS_DIR,
    list_scenarios,
    load_scenario,
    run_artifact_metadata,
    validate_scenario,
    write_run_artifacts,
    ScenarioValidationError,
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
from mmap_optimizer.prompt.hint_generator import auto_generate_hints
from mmap_optimizer.prompt.snapshot import load_prompt_snapshot
from mmap_optimizer.storage.json_store import JsonStore


def _apply_scenario_args(args: argparse.Namespace) -> None:
    scenario_path = getattr(args, "scenario", None)
    if not scenario_path:
        return
    scenario = load_scenario(scenario_path)
    if getattr(args, "config", None) == "configs/optimizer.yaml":
        args.config = str(scenario.root / "optimizer.yaml")
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
    args.section_id_hints = scenario.section_id_hints
    args.loaded_scenario_id = scenario.id


def _load_contract(path: Path, prompt_type: PromptType, contract_id: str) -> OutputSchemaContract:
    schema = json.loads(path.read_text(encoding="utf-8"))
    primary = schema.get("x-primary-answer-fields", ["result"])
    return OutputSchemaContract(id=contract_id, prompt_type=prompt_type, version=1, schema=schema, primary_answer_fields=primary)



def _build_state(args: argparse.Namespace) -> tuple[OptimizerState, OutputSchemaContract, OutputSchemaContract]:
    data_dir = Path(args.data_dir)
    hints = getattr(args, "section_id_hints", {}) or {}
    extraction_contract = _load_contract(Path(args.extraction_schema), PromptType.EXTRACTION, "extraction_output_schema_v1")
    analysis_contract = _load_contract(Path(args.analysis_schema), PromptType.ANALYSIS, "analysis_output_schema_v1")
    extraction_prompt = initialize_prompt_from_file(args.extraction_prompt, PromptType.EXTRACTION, extraction_contract, section_id_hints=hints)
    analysis_prompt = initialize_prompt_from_file(args.analysis_prompt, PromptType.ANALYSIS, analysis_contract, section_id_hints=hints)
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
    log_stage(logger, "optimizer_start", "优化器启动（smoke 模式）",
              config_path=getattr(args, 'config', 'N/A'), sample_count=len(state.samples),
              planned_rounds=args.rounds, output_dir=args.run_dir,
              log_level=os.environ.get('MMAP_LOG_LEVEL', 'INFO'))
    runner = RoundRunner(model_client=MockModelClient(), evaluator=Evaluator(), store=store, config=config)
    _, metrics_records, summary = OptimizerLoop(runner=runner, store=store, config=config, resume=getattr(args, "resume", False)).run(state, max_rounds=args.rounds)
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
    log_stage(logger, "optimizer_start", "优化器启动（生产模式）",
              config_path=args.config, extraction_model=config.extraction_model.model,
              extraction_provider=config.extraction_model.provider,
              optimizer_model=config.optimizer_model.model, optimizer_provider=config.optimizer_model.provider,
              max_workers=config.execution_max_workers, sample_count=len(state.samples),
              planned_rounds=args.rounds, output_dir=config.run_dir,
              log_level=os.environ.get('MMAP_LOG_LEVEL', 'INFO'))
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
    hints = getattr(args, "section_id_hints", {}) or {}
    extraction_contract = _load_contract(Path(args.extraction_schema), PromptType.EXTRACTION, "extraction_output_schema_v1")
    analysis_contract = _load_contract(Path(args.analysis_schema), PromptType.ANALYSIS, "analysis_output_schema_v1")
    prompts = {
        "extraction": initialize_prompt_from_file(args.extraction_prompt, PromptType.EXTRACTION, extraction_contract, section_id_hints=hints),
        "analysis": initialize_prompt_from_file(args.analysis_prompt, PromptType.ANALYSIS, analysis_contract, section_id_hints=hints),
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


def scenario_list(args: argparse.Namespace) -> None:
    scenarios_dir = getattr(args, "scenarios_dir", DEFAULT_SCENARIOS_DIR)
    scenarios = list_scenarios(scenarios_dir)
    if getattr(args, "json", False):
        print(json.dumps({"scenarios": scenarios, "count": len(scenarios)}, ensure_ascii=False))
    else:
        if not scenarios:
            print(f"No valid scenarios found in {scenarios_dir}")
        else:
            print(f"Valid scenarios in {scenarios_dir}:")
            for s in scenarios:
                print(f"  - {s['id']}")


def scenario_validate(args: argparse.Namespace) -> None:
    scenarios_dir = getattr(args, "scenarios_dir", DEFAULT_SCENARIOS_DIR)
    scenario_id = args.scenario_id
    try:
        config = validate_scenario(scenario_id, scenarios_dir=scenarios_dir)
        result = {
            "valid": True,
            "scenario_id": config.id,
            "root": str(config.root),
            "data_dir": str(config.data_dir),
            "prompts_dir": str(config.prompts_dir),
            "schemas_dir": str(config.schemas_dir),
        }
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Scenario '{config.id}' is valid")
            print(f"  Root: {config.root}")
            print(f"  Data: {config.data_dir}")
            print(f"  Prompts: {config.prompts_dir}")
            print(f"  Schemas: {config.schemas_dir}")
    except ScenarioValidationError as e:
        result = {"valid": False, "scenario_id": scenario_id, "error": str(e)}
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"Scenario '{scenario_id}' is invalid: {e}")
        raise SystemExit(2)


def scenario_info(args: argparse.Namespace) -> None:
    scenarios_dir = getattr(args, "scenarios_dir", DEFAULT_SCENARIOS_DIR)
    scenario_id = args.scenario_id
    config = load_scenario(Path(scenarios_dir) / scenario_id)
    metadata = run_artifact_metadata(config)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def scenario_write_artifacts(args: argparse.Namespace) -> None:
    scenarios_dir = getattr(args, "scenarios_dir", DEFAULT_SCENARIOS_DIR)
    scenario_id = args.scenario_id
    artifact_dir = args.artifact_dir
    config = load_scenario(Path(scenarios_dir) / scenario_id)
    artifacts = write_run_artifacts(artifact_dir, config)
    result = {name: str(path) for name, path in artifacts.items()}
    print(json.dumps(result, ensure_ascii=False))


def generate_hints(args: argparse.Namespace) -> None:
    """Auto-generate section_id_hints for a scenario using LLM and persist to scenario.yaml."""
    from mmap_optimizer.model.factory import build_model_client

    scenario_path = args.scenario
    scenario = load_scenario(scenario_path)
    existing_hints = scenario.section_id_hints

    # Read extraction prompt for heading analysis
    extraction_prompt_path = scenario.prompts_dir / "extraction.txt"
    if not extraction_prompt_path.exists():
        # Try .md extension
        extraction_prompt_path = scenario.prompts_dir / "extraction.md"
    if not extraction_prompt_path.exists():
        # Try system.md as fallback
        extraction_prompt_path = scenario.prompts_dir / "system.md"
    if not extraction_prompt_path.exists():
        print(json.dumps({"error": f"No prompt file found in {scenario.prompts_dir}", "generated_hints": {}}, ensure_ascii=False))
        raise SystemExit(1)

    raw_prompt = extraction_prompt_path.read_text(encoding="utf-8")

    # Build model client from optimizer config
    config = scenario.optimizer_config
    model_client = build_model_client(config.optimizer_model)

    result = auto_generate_hints(raw_prompt, model_client)
    generated = result.hints

    # Merge: existing manual hints take priority
    merged = {**generated, **existing_hints}

    output = {
        "scenario": scenario.id,
        "existing_hints": existing_hints,
        "generated_hints": generated,
        "merged_hints": merged,
        "uncovered_titles": result.uncovered_titles,
        "is_complete": result.is_complete,
        "written": False,
    }

    if args.write and generated:
        # Persist to scenario.yaml
        manifest_path = scenario.root / "scenario.yaml"
        manifest = load_mapping(manifest_path)
        manifest["section_id_hints"] = merged
        # Write back preserving YAML structure
        _write_yaml_hints(manifest_path, manifest, merged)
        output["written"] = True
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


def _write_yaml_hints(manifest_path: Path, manifest: dict, hints: dict[str, str]) -> None:
    """Write section_id_hints back to scenario.yaml, preserving other content."""
    import yaml
    try:
        content = manifest_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except ImportError:
        # Fallback: simple string replacement if pyyaml not available
        data = manifest
    if data is None:
        data = {}
    data["section_id_hints"] = hints
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="MMAP prompt optimizer MVP CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # Scenario subcommand group
    scenario_parser = sub.add_parser("scenario", help="Scenario management commands")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_command", required=True)

    list_parser = scenario_sub.add_parser("list", help="List all valid scenarios")
    list_parser.add_argument("--scenarios-dir", default=DEFAULT_SCENARIOS_DIR)
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=scenario_list)

    validate_parser = scenario_sub.add_parser("validate", help="Validate a scenario")
    validate_parser.add_argument("scenario_id")
    validate_parser.add_argument("--scenarios-dir", default=DEFAULT_SCENARIOS_DIR)
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=scenario_validate)

    info_parser = scenario_sub.add_parser("info", help="Show scenario info and metadata")
    info_parser.add_argument("scenario_id")
    info_parser.add_argument("--scenarios-dir", default=DEFAULT_SCENARIOS_DIR)
    info_parser.set_defaults(func=scenario_info)

    write_parser = scenario_sub.add_parser("write-artifacts", help="Write scenario artifacts to a directory")
    write_parser.add_argument("scenario_id")
    write_parser.add_argument("artifact_dir")
    write_parser.add_argument("--scenarios-dir", default=DEFAULT_SCENARIOS_DIR)
    write_parser.set_defaults(func=scenario_write_artifacts)

    gen_hints_parser = sub.add_parser("generate-hints", help="Auto-generate section_id_hints for a scenario using LLM.")
    gen_hints_parser.add_argument("--scenario", required=True, help="Path to scenario directory")
    gen_hints_parser.add_argument("--write", action="store_true", help="Persist generated hints to scenario.yaml")
    gen_hints_parser.set_defaults(func=generate_hints)

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
    smoke.add_argument("--resume", action="store_true", help="Resume from existing checkpoint.json in run-dir")
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

    rollback_parser = sub.add_parser("rollback-prompt", help="Restore an active prompt from a saved snapshot.")
    rollback_parser.add_argument("--run-dir", default="runs")
    rollback_parser.add_argument("--snapshot-id", required=True)
    rollback_parser.add_argument("--prompt-name", default=None)
    rollback_parser.set_defaults(func=rollback_prompt)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
