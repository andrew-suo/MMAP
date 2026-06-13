from __future__ import annotations

import json

from tests._compat import candidate_modules, find_symbol

SCENARIO_MODULES = candidate_modules(
    "mmap.scenario_loader",
    "mmap.scenarios.loader",
    "mmap.scenario",
    "mmap_engine.scenario_loader",
    "src.scenario_loader",
)


def test_scenario_loader_reads_scenario_and_normalizes_defaults(tmp_path) -> None:
    load_scenario = find_symbol(SCENARIO_MODULES, "load_scenario", "load_scenario_config")
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(
        json.dumps({"name": "basic", "dataset": "data/items.jsonl", "config": {"rounds": 3}}),
        encoding="utf-8",
    )

    scenario = load_scenario(scenario_file)

    assert scenario["name"] == "basic"
    assert scenario["dataset"].endswith("data/items.jsonl")
    assert scenario["config"]["rounds"] == 3
    assert scenario["config_hash"]


def test_config_hash_is_stable_for_key_order_and_changes_for_content() -> None:
    config_hash = find_symbol(SCENARIO_MODULES, "config_hash", "hash_config", "scenario_config_hash")

    left = config_hash({"rounds": 3, "flags": {"semantic": True, "repair": True}})
    right = config_hash({"flags": {"repair": True, "semantic": True}, "rounds": 3})
    changed = config_hash({"rounds": 4, "flags": {"semantic": True, "repair": True}})

    assert left == right
    assert left != changed
