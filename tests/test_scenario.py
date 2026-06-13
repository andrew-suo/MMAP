import json
import os
import tempfile
from pathlib import Path

import pytest

from mmap_optimizer.core.scenario import (
    ScenarioConfig,
    ScenarioValidationError,
    STANDARD_SCENARIO_FILES,
    STANDARD_SCENARIO_DIRS,
    DEFAULT_SCENARIOS_DIR,
    deep_merge,
    stable_hash,
    file_hash,
    directory_file_hashes,
    run_artifact_metadata,
    write_run_artifacts,
    validate_scenario,
    list_scenarios,
    load_scenario,
)


@pytest.fixture
def valid_scenario_path(tmp_path):
    """Create a valid scenario directory with all required files and directories."""
    scenario_path = tmp_path / "test_scenario"
    scenario_path.mkdir()
    
    # Create standard files
    (scenario_path / "scenario.yaml").write_text("name: Test Scenario\noptimizer_config: optimizer.yaml\n", encoding="utf-8")
    (scenario_path / "optimizer.yaml").write_text("run_dir: runs\nbatch_size: 24\n", encoding="utf-8")
    (scenario_path / "README.md").write_text("# Test Scenario\n", encoding="utf-8")
    
    # Create standard directories
    for dirname in STANDARD_SCENARIO_DIRS:
        (scenario_path / dirname).mkdir()
    
    # Create some content in data dir
    (scenario_path / "data" / "example.json").write_text('{"test": true}', encoding="utf-8")
    
    return scenario_path


@pytest.fixture
def invalid_scenario_path(tmp_path):
    """Create an invalid scenario directory with missing files."""
    scenario_path = tmp_path / "invalid_scenario"
    scenario_path.mkdir()
    (scenario_path / "README.md").write_text("# Missing files\n", encoding="utf-8")
    return scenario_path


class TestValidateScenario:
    def test_validate_scenario_with_missing_directory_raises_error(self, tmp_path):
        with pytest.raises(ScenarioValidationError, match="does not exist"):
            validate_scenario(tmp_path / "nonexistent")

    def test_validate_scenario_with_missing_file_raises_error(self, invalid_scenario_path):
        with pytest.raises(ScenarioValidationError, match="Missing standard scenario file"):
            validate_scenario(invalid_scenario_path)

    def test_validate_scenario_with_missing_dir_raises_error(self, tmp_path):
        scenario_path = tmp_path / "missing_dir_scenario"
        scenario_path.mkdir()
        (scenario_path / "scenario.yaml").write_text("", encoding="utf-8")
        (scenario_path / "optimizer.yaml").write_text("", encoding="utf-8")
        (scenario_path / "README.md").write_text("", encoding="utf-8")
        
        with pytest.raises(ScenarioValidationError, match="Missing standard scenario directory"):
            validate_scenario(scenario_path)

    def test_validate_scenario_returns_scenario_config(self, valid_scenario_path):
        config = validate_scenario(valid_scenario_path)
        assert isinstance(config, ScenarioConfig)
        assert config.id == "test_scenario"
        assert config.root == valid_scenario_path
        assert config.data_dir == valid_scenario_path / "data"
        assert config.prompts_dir == valid_scenario_path / "prompts"
        assert config.schemas_dir == valid_scenario_path / "schemas"

    def test_validate_scenario_with_scenarios_dir(self, tmp_path):
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        scenario_path = scenarios_dir / "my_scenario"
        scenario_path.mkdir()
        
        for filename in STANDARD_SCENARIO_FILES:
            (scenario_path / filename).write_text("", encoding="utf-8")
        for dirname in STANDARD_SCENARIO_DIRS:
            (scenario_path / dirname).mkdir()
        
        config = validate_scenario("my_scenario", scenarios_dir=scenarios_dir)
        assert config.id == "my_scenario"


class TestListScenarios:
    def test_list_scenarios_returns_empty_for_nonexistent_dir(self):
        scenarios = list_scenarios("/nonexistent/path")
        assert scenarios == []

    def test_list_scenarios_skips_invalid_children(self, tmp_path):
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        # Create valid scenario
        valid = scenarios_dir / "valid"
        valid.mkdir()
        for filename in STANDARD_SCENARIO_FILES:
            (valid / filename).write_text("", encoding="utf-8")
        for dirname in STANDARD_SCENARIO_DIRS:
            (valid / dirname).mkdir()
        
        # Create invalid scenario
        invalid = scenarios_dir / "invalid"
        invalid.mkdir()
        (invalid / "README.md").write_text("", encoding="utf-8")
        
        scenarios = list_scenarios(scenarios_dir)
        assert len(scenarios) == 1
        assert scenarios[0]["id"] == "valid"

    def test_list_scenarios_returns_valid_summaries(self, valid_scenario_path, tmp_path):
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        # Copy valid scenario to scenarios dir
        import shutil
        dest = scenarios_dir / "test"
        shutil.copytree(valid_scenario_path, dest)
        
        scenarios = list_scenarios(scenarios_dir)
        assert len(scenarios) == 1
        assert scenarios[0]["id"] == "test"
        assert "root" in scenarios[0]
        assert "data_dir" in scenarios[0]


class TestDeepMerge:
    def test_deep_merge_override_values(self):
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}, "e": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}

    def test_deep_merge_override_non_dict(self):
        base = {"a": 1, "b": {"c": 2}}
        override = {"a": 10}
        result = deep_merge(base, override)
        assert result == {"a": 10, "b": {"c": 2}}

    def test_deep_merge_nested_dicts(self):
        base = {"a": {"b": {"c": 1}}}
        override = {"a": {"b": {"d": 2}}}
        result = deep_merge(base, override)
        assert result == {"a": {"b": {"c": 1, "d": 2}}}


class TestStableHash:
    def test_stable_hash_same_input_same_output(self):
        data = {"key": "value", "number": 42}
        hash1 = stable_hash(data)
        hash2 = stable_hash(data)
        assert hash1 == hash2

    def test_stable_hash_different_input_different_output(self):
        hash1 = stable_hash({"key": "value1"})
        hash2 = stable_hash({"key": "value2"})
        assert hash1 != hash2

    def test_stable_hash_order_independent(self):
        hash1 = stable_hash({"a": 1, "b": 2})
        hash2 = stable_hash({"b": 2, "a": 1})
        assert hash1 == hash2


class TestFileHash:
    def test_file_hash_computes_hash(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("hello world", encoding="utf-8")
        hash_result = file_hash(file_path)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64  # SHA256 hex length


class TestDirectoryFileHashes:
    def test_directory_file_hashes_returns_dict(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1", encoding="utf-8")
        file2.write_text("content2", encoding="utf-8")
        
        hashes = directory_file_hashes(tmp_path)
        assert isinstance(hashes, dict)
        assert "file1.txt" in hashes
        assert "file2.txt" in hashes
        assert len(hashes["file1.txt"]) == 64

    def test_directory_file_hashes_empty_dir(self, tmp_path):
        hashes = directory_file_hashes(tmp_path)
        assert hashes == {}


class TestRunArtifactMetadata:
    def test_run_artifact_metadata_returns_dict(self, valid_scenario_path):
        config = load_scenario(valid_scenario_path)
        metadata = run_artifact_metadata(config)
        assert isinstance(metadata, dict)
        assert "scenario_id" in metadata
        assert "scenario_root" in metadata
        assert "config_hash" in metadata
        assert "directory_hashes" in metadata
        assert "stable_hash" in metadata


class TestWriteRunArtifacts:
    def test_write_run_artifacts_creates_files(self, valid_scenario_path, tmp_path):
        config = load_scenario(valid_scenario_path)
        artifact_dir = tmp_path / "artifacts"
        
        artifacts = write_run_artifacts(artifact_dir, config)
        
        assert "metadata" in artifacts
        assert artifact_dir / "metadata.json" in artifacts["metadata"].parent.iterdir()
        assert artifacts["metadata"].exists()
        
        # Check metadata content
        metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))
        assert metadata["scenario_id"] == config.id


class TestCLI:
    def test_scenario_list_command(self, tmp_path):
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        valid = scenarios_dir / "valid"
        valid.mkdir()
        for filename in STANDARD_SCENARIO_FILES:
            (valid / filename).write_text("", encoding="utf-8")
        for dirname in STANDARD_SCENARIO_DIRS:
            (valid / dirname).mkdir()
        
        from mmap_optimizer.cli.main import scenario_list
        import argparse
        args = argparse.Namespace(scenarios_dir=str(scenarios_dir), json=False)
        scenario_list(args)

    def test_scenario_validate_command(self, valid_scenario_path):
        from mmap_optimizer.cli.main import scenario_validate
        import argparse
        args = argparse.Namespace(scenario_id=valid_scenario_path.name, scenarios_dir=str(valid_scenario_path.parent), json=False)
        scenario_validate(args)

    def test_scenario_info_command(self, valid_scenario_path):
        from mmap_optimizer.cli.main import scenario_info
        import argparse
        args = argparse.Namespace(scenario_id=valid_scenario_path.name, scenarios_dir=str(valid_scenario_path.parent))
        scenario_info(args)

    def test_scenario_write_artifacts_command(self, valid_scenario_path, tmp_path):
        from mmap_optimizer.cli.main import scenario_write_artifacts
        import argparse
        artifact_dir = tmp_path / "artifacts"
        args = argparse.Namespace(scenario_id=valid_scenario_path.name, scenarios_dir=str(valid_scenario_path.parent), artifact_dir=str(artifact_dir))
        scenario_write_artifacts(args)


class TestBackwardCompatibility:
    def test_load_scenario_still_works(self, valid_scenario_path):
        config = load_scenario(valid_scenario_path)
        assert isinstance(config, ScenarioConfig)
        assert config.id == valid_scenario_path.name
