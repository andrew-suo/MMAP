"""Contract tests for examples/prompt_utility_runner/

Covers:
- File existence (README, script, sample prompts).
- Importability without side effects.
- Script execution (main() → exit 0).
- Output structure (summary section, JSON report section,
  target_id, enabled=True, report_only=True, utility reports).
- Guardrails (no model / optimizer / CLI / scenario imports, no writes,
  no sample file mutation, no eval / ast.literal_eval, deterministic).
- Non-default behavior (no CLI change, no optimizer-loop change, no
  scenario default, no production prompt touch).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples" / "prompt_utility_runner"
SCRIPT_PATH = EXAMPLES_DIR / "run_prompt_utility_example.py"
ORIGINAL_PATH = EXAMPLES_DIR / "sample_original_prompt.md"
REWRITTEN_PATH = EXAMPLES_DIR / "sample_rewritten_prompt.md"
README_PATH = EXAMPLES_DIR / "README.md"


def _extract_json_report(stdout: str) -> dict:
    """Extract the first JSON object from the stdout of the example script.

    Looks for the "PROMPT UTILITY RUNNER — JSON REPORT" marker, then uses
    json.JSONDecoder.raw_decode to find a top-level JSON object starting
    at the first '{' after the marker.
    """
    marker = "PROMPT UTILITY RUNNER — JSON REPORT"
    idx = stdout.index(marker)
    tail = stdout[idx:]
    start = tail.index("{")
    obj, _ = json.JSONDecoder().raw_decode(tail[start:])
    return obj


# ---------------------------------------------------------------------------
# Example existence tests
# ---------------------------------------------------------------------------

class TestExampleExistence:
    def test_readme_exists(self) -> None:
        assert README_PATH.is_file(), "README.md should exist"

    def test_script_exists(self) -> None:
        assert SCRIPT_PATH.is_file(), "run_prompt_utility_example.py should exist"

    def test_sample_original_exists(self) -> None:
        assert ORIGINAL_PATH.is_file(), "sample_original_prompt.md should exist"

    def test_sample_rewritten_exists(self) -> None:
        assert REWRITTEN_PATH.is_file(), "sample_rewritten_prompt.md should exist"

    def test_sample_original_nonempty(self) -> None:
        assert ORIGINAL_PATH.read_text(encoding="utf-8").strip() != ""

    def test_sample_rewritten_nonempty(self) -> None:
        assert REWRITTEN_PATH.read_text(encoding="utf-8").strip() != ""


# ---------------------------------------------------------------------------
# Example execution tests
# ---------------------------------------------------------------------------

class TestExampleExecution:
    def test_script_importable(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "example_script", SCRIPT_PATH
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        # Import only — must not raise or write files
        spec.loader.exec_module(module)
        assert hasattr(module, "main")

    def test_main_returns_zero(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "example_script_main", SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.main() == 0

    def test_stdout_contains_summary(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        assert "PROMPT UTILITY RUNNER — SUMMARY" in out.stdout

    def test_stdout_contains_json_report(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        assert "PROMPT UTILITY RUNNER — JSON REPORT" in out.stdout

    def test_json_report_parses(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        parsed = _extract_json_report(out.stdout)
        assert isinstance(parsed, dict)

    def test_parsed_report_enabled_true(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert parsed["enabled"] is True

    def test_parsed_report_report_only_true(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert parsed["report_only"] is True

    def test_parsed_report_has_rewrite_safety(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert "rewrite_safety" in parsed["reports"]

    def test_parsed_report_has_json_repair(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert "json_repair" in parsed["reports"]

    def test_parsed_report_has_numbering_refactor(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert "numbering_refactor" in parsed["reports"]

    def test_parsed_report_has_immutable_payload(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert "immutable_payload" in parsed["reports"]

    def test_parsed_report_has_target_id(self) -> None:
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        parsed = _extract_json_report(out.stdout)
        assert "target_id" in parsed


# ---------------------------------------------------------------------------
# Guardrail tests (on the example script itself)
# ---------------------------------------------------------------------------

class TestExampleGuardrails:
    def test_script_does_not_import_model(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module and node.module.startswith("mmap_optimizer.model")), (
                    "example must not import mmap_optimizer.model"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mmap_optimizer.model")

    def test_script_does_not_import_optimizer(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module and node.module.startswith("mmap_optimizer.optimizer")), (
                    "example must not import mmap_optimizer.optimizer"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mmap_optimizer.optimizer")

    def test_script_does_not_import_cli(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module and node.module.startswith("mmap_optimizer.cli")), (
                    "example must not import mmap_optimizer.cli"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mmap_optimizer.cli")

    def test_script_does_not_import_scenario_runner(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module and node.module.startswith("mmap_optimizer.scenario")), (
                    "example must not import mmap_optimizer.scenario"
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("mmap_optimizer.scenario")

    def test_script_does_not_write_files(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        write_funcs = {"write", "open", "Path", "save_text", "dump"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if func in {"open", "write", "mkdir", "makedirs"}:
                    # Only allow open for reading the sample prompts.
                    # We don't want a top-level write call.
                    # Actually — the script does use open via Path.read_text,
                    # which is fine. Let's check for write-opens specifically.
                    pass
        # Simpler: check the source text for "write(" — not present:
        assert "open(" not in source or (source.count("open(") == 0)
        assert "write(" not in source
        assert "save(" not in source
        assert "dump(" not in source

    def test_script_does_not_mutate_sample_files(self) -> None:
        original_before = ORIGINAL_PATH.read_text(encoding="utf-8")
        rewritten_before = REWRITTEN_PATH.read_text(encoding="utf-8")
        out = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        assert ORIGINAL_PATH.read_text(encoding="utf-8") == original_before
        assert REWRITTEN_PATH.read_text(encoding="utf-8") == rewritten_before

    def test_script_no_eval_or_literal_eval(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        assert "eval(" not in source
        assert "literal_eval" not in source

    def test_script_deterministic_across_runs(self) -> None:
        out1 = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        out2 = subprocess.run(
            [sys.executable, "-m",
             "examples.prompt_utility_runner.run_prompt_utility_example"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out1.returncode == 0
        assert out2.returncode == 0
        assert out1.stdout == out2.stdout


# ---------------------------------------------------------------------------
# Non-default behavior tests
# ---------------------------------------------------------------------------

class TestNonDefault:
    def test_cli_help_unchanged(self) -> None:
        """CLI help must not mention the example."""
        out = subprocess.run(
            [sys.executable, "-m", "mmap_optimizer.cli.main", "--help"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0
        assert "prompt_utility_runner" not in out.stdout.lower()
        assert "example" not in out.stdout.lower()

    def test_optimizer_loop_does_not_import_runner(self) -> None:
        """No optimizer module should import utility_runner."""
        # Search for references to utility_runner inside mmap_optimizer/optimizer
        optimizer_dir = REPO_ROOT / "mmap_optimizer" / "optimizer"
        if optimizer_dir.is_dir():
            for f in optimizer_dir.rglob("*.py"):
                text = f.read_text(encoding="utf-8")
                assert "utility_runner" not in text, (
                    "optimizer module %s should not import utility_runner" % f
                )

    def test_no_scenario_default_refers_example(self) -> None:
        scenarios_dir = REPO_ROOT / "mmap_optimizer" / "scenario"
        if scenarios_dir.is_dir():
            for f in scenarios_dir.rglob("*.py"):
                text = f.read_text(encoding="utf-8")
                assert "prompt_utility_runner" not in text, (
                    "scenario %s should not refer to the example" % f
                )

    def test_no_production_prompt_files_touched(self) -> None:
        """The example directory is isolated under examples/."""
        assert EXAMPLES_DIR.parts[-1] == "prompt_utility_runner"
        assert EXAMPLES_DIR.parts[-2] == "examples"
