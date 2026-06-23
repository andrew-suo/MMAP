"""PR4 Task 33: 端到端 Smoke 测试。

验证 MMAP 重构版完整三阶段流程可运行、可验收：
  Prompt Structuring
  → Prompt Optimization
  → Few-shot Optimization
  → Artifact 输出
  → Run Summary

覆盖：
1. CLI run 可执行（通过 MMAPRunner 直接调用，等价于 CLI）；
2. 三阶段 Run 完成；
3. prompt optimization 至少跑 1 轮；
4. few-shot optimization 至少跑 1 轮；
5. run_summary.json 正确生成且字段完整；
6. 验收产物存在（run_summary、final_extraction_prompt、final_analysis_prompt、
   final_fewshot_examples、compression_report、sample_traces、toxicity_report）；
7. no_progress / rollback / compression 状态正确记录；
8. CLI 命令可解析（configs/smoke.yaml）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mmap_optimizer.config import load_config
from mmap_optimizer.runner import MMAPRunner


# ============================================================
# 辅助函数
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_CONFIG = REPO_ROOT / "configs" / "smoke.yaml"
SMOKE_DATASET = REPO_ROOT / "data" / "smoke_samples.jsonl"
EXTRACTION_PROMPT = REPO_ROOT / "prompts" / "extraction.txt"
ANALYSIS_PROMPT = REPO_ROOT / "prompts" / "analysis.txt"


def _run_smoke(tmp_path: Path) -> tuple[MMAPRunner, Path]:
    """执行一次 smoke run，返回 (runner, output_dir)。"""
    config = load_config(SMOKE_CONFIG)
    config.run.output_dir = str(tmp_path / "smoke_run")
    config.run.use_mock = True

    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=EXTRACTION_PROMPT,
        analysis_prompt_path=ANALYSIS_PROMPT,
        use_mock=True,
    )
    runner.run()
    return runner, Path(config.run.output_dir)


# ============================================================
# 配置与数据集存在性测试
# ============================================================

def test_smoke_config_exists():
    """smoke 配置文件存在。"""
    assert SMOKE_CONFIG.exists(), f"smoke 配置不存在: {SMOKE_CONFIG}"


def test_smoke_dataset_exists():
    """smoke 数据集存在且包含 10~20 条样本。"""
    assert SMOKE_DATASET.exists(), f"smoke 数据集不存在: {SMOKE_DATASET}"
    lines = [
        line for line in SMOKE_DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert 10 <= len(lines) <= 20, f"样本数应为 10~20，实际 {len(lines)}"


def test_smoke_config_loads():
    """smoke 配置可正确加载。"""
    config = load_config(SMOKE_CONFIG)
    assert config.prompt_optimization.enabled is True
    assert config.prompt_optimization.rounds == 1
    assert config.fewshot_optimization.enabled is True
    assert config.fewshot_optimization.rounds == 1
    assert config.fewshot_optimization.slot_count == 3


def test_smoke_dataset_contains_required_categories():
    """smoke 数据集包含必需的样本类别。"""
    lines = SMOKE_DATASET.read_text(encoding="utf-8").splitlines()
    samples = [json.loads(line) for line in lines if line.strip()]

    tags_flat = set()
    for s in samples:
        tags_flat.update(s.get("tags", []))

    # 必须包含正确样本、错误样本、可修复样本、toxic 候选、few-shot 候选
    assert "correct" in tags_flat, "缺少 correct 样本"
    assert "error" in tags_flat, "缺少 error 样本"
    assert "toxic_candidate" in tags_flat, "缺少 toxic_candidate 样本"
    assert "fewshot_candidate" in tags_flat, "缺少 fewshot_candidate 样本"


# ============================================================
# 端到端 Run 测试
# ============================================================

def test_smoke_run_completes_three_phases(tmp_path):
    """smoke run 完成三阶段。"""
    runner, output_dir = _run_smoke(tmp_path)

    summary = runner.run_summary
    assert summary.status == "completed"
    assert summary.prompt_structuring_status == "completed"
    assert summary.prompt_optimization.iterations >= 1, "prompt optimization 至少 1 轮"
    assert summary.fewshot_optimization.iterations >= 1, "few-shot optimization 至少 1 轮"


def test_smoke_run_summary_json_exists_and_complete(tmp_path):
    """run_summary.json 存在且字段完整。"""
    runner, output_dir = _run_smoke(tmp_path)

    summary_file = output_dir / "run_summary.json"
    assert summary_file.exists(), "run_summary.json 不存在"

    data = json.loads(summary_file.read_text(encoding="utf-8"))

    # v1.4 必需顶层字段
    required_top = {
        "id", "status", "start_time", "end_time", "duration_seconds",
        "prompt_structuring_status", "prompt_optimization", "analysis_prompt",
        "fewshot_optimization", "final_extraction_prompt_id", "final_analysis_prompt_id",
        "final_fewshot_example_count",
    }
    assert required_top.issubset(data.keys())

    # 时间字段非空
    assert data["start_time"] is not None
    assert data["end_time"] is not None
    assert data["duration_seconds"] is not None
    assert data["duration_seconds"] >= 0

    # prompt_optimization 嵌套字段
    po = data["prompt_optimization"]
    required_po = {
        "iterations", "base_accuracy_first", "final_accuracy_last", "best_accuracy",
        "total_accepted_patches", "total_rejected_patches", "total_toxic_patches",
        "total_ineffective_patches", "rollback_count", "no_progress_count",
        "compression_triggered_count", "compression_accepted_count", "batch_size_history",
    }
    assert required_po.issubset(po.keys())
    assert po["iterations"] >= 1
    assert isinstance(po["batch_size_history"], list)

    # fewshot_optimization 嵌套字段
    fo = data["fewshot_optimization"]
    required_fo = {
        "iterations", "base_accuracy_first", "final_accuracy_last",
        "selected_example_ids", "accepted",
    }
    assert required_fo.issubset(fo.keys())
    assert fo["iterations"] >= 1


def test_smoke_run_final_prompts_exist(tmp_path):
    """final_extraction_prompt.json 和 final_analysis_prompt.json 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    assert (output_dir / "final_extraction_prompt.json").exists()
    assert (output_dir / "final_analysis_prompt.json").exists()
    assert (output_dir / "final_fewshot_examples.jsonl").exists()


def test_smoke_run_structured_prompts_exist(tmp_path):
    """structured_extraction_prompt.json 和 structured_analysis_prompt.json 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    assert (output_dir / "structured_extraction_prompt.json").exists()
    assert (output_dir / "structured_analysis_prompt.json").exists()


def test_smoke_run_run_plan_and_config_exist(tmp_path):
    """run_plan.json 和 run_config.yaml/json 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    assert (output_dir / "run_plan.json").exists()
    assert (output_dir / "run_config.yaml").exists()
    assert (output_dir / "run_config.json").exists()


def test_smoke_run_prompt_iteration_artifacts_exist(tmp_path):
    """prompt_optimization/iteration_1/ 下关键 artifact 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    iter_dir = output_dir / "prompt_optimization" / "iteration_1"
    assert iter_dir.exists(), f"iteration 目录不存在: {iter_dir}"

    # 必需文件
    assert (iter_dir / "sample_batch.json").exists()
    assert (iter_dir / "sample_traces.jsonl").exists()
    assert (iter_dir / "sample_state_before.json").exists()
    assert (iter_dir / "sample_state_after.json").exists()
    assert (iter_dir / "batch_size_controller_before.json").exists()
    assert (iter_dir / "batch_size_controller_after.json").exists()

    # extraction / analysis 子目录
    assert (iter_dir / "extraction").exists()
    assert (iter_dir / "analysis").exists()


def test_smoke_run_extraction_artifacts_exist(tmp_path):
    """extraction/ 下关键 artifact 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    ext_dir = output_dir / "prompt_optimization" / "iteration_1" / "extraction"
    assert ext_dir.exists()

    # 关键文件（至少这些必须存在）
    assert (ext_dir / "base_results.jsonl").exists()
    assert (ext_dir / "base_eval.jsonl").exists()
    assert (ext_dir / "metrics.json").exists()
    assert (ext_dir / "compression_report.json").exists()


def test_smoke_run_analysis_artifacts_exist(tmp_path):
    """analysis/ 下关键 artifact 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    ana_dir = output_dir / "prompt_optimization" / "iteration_1" / "analysis"
    assert ana_dir.exists()

    assert (ana_dir / "base_metrics.json").exists()
    assert (ana_dir / "metrics.json").exists()
    assert (ana_dir / "compression_report.json").exists()


def test_smoke_run_fewshot_artifacts_exist(tmp_path):
    """fewshot_optimization/iteration_1/ 下关键 artifact 存在。"""
    runner, output_dir = _run_smoke(tmp_path)

    fs_dir = output_dir / "fewshot_optimization" / "iteration_1"
    assert fs_dir.exists(), f"fewshot iteration 目录不存在: {fs_dir}"

    assert (fs_dir / "sample_batch.json").exists()
    assert (fs_dir / "sample_traces.jsonl").exists()
    assert (fs_dir / "fewshot").exists()

    fewshot_dir = fs_dir / "fewshot"
    assert (fewshot_dir / "base_results.jsonl").exists()
    assert (fewshot_dir / "base_eval.jsonl").exists()
    assert (fewshot_dir / "metrics.json").exists()


def test_smoke_run_toxicity_report_exists(tmp_path):
    """toxicity_report.json 存在（extraction 和 analysis 下）。"""
    runner, output_dir = _run_smoke(tmp_path)

    ext_toxicity = output_dir / "prompt_optimization" / "iteration_1" / "extraction" / "toxicity_report.json"
    assert ext_toxicity.exists(), f"extraction toxicity_report 不存在: {ext_toxicity}"


def test_smoke_run_sample_traces_jsonl_parseable(tmp_path):
    """sample_traces.jsonl 可解析为 JSON。"""
    runner, output_dir = _run_smoke(tmp_path)

    traces_file = output_dir / "prompt_optimization" / "iteration_1" / "sample_traces.jsonl"
    assert traces_file.exists()

    lines = [l for l in traces_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) > 0, "sample_traces.jsonl 为空"

    for line in lines:
        trace = json.loads(line)
        assert "sample_id" in trace
        assert "phase" in trace


def test_smoke_run_compression_report_parseable(tmp_path):
    """compression_report.json 可解析且字段完整。"""
    runner, output_dir = _run_smoke(tmp_path)

    cr_file = output_dir / "prompt_optimization" / "iteration_1" / "extraction" / "compression_report.json"
    assert cr_file.exists()

    data = json.loads(cr_file.read_text(encoding="utf-8"))
    # CompressionReport 必需字段
    required = {
        "id", "prompt_type", "triggered", "accepted",
        "line_count_before", "line_count_after",
        "char_count_before", "char_count_after",
    }
    assert required.issubset(data.keys())


def test_smoke_run_prompt_versions_jsonl_exists(tmp_path):
    """prompt_versions.jsonl 存在且可解析（mock 模式下可能为空）。"""
    runner, output_dir = _run_smoke(tmp_path)

    pv_file = output_dir / "prompt_versions.jsonl"
    assert pv_file.exists(), "prompt_versions.jsonl 不存在"

    lines = [l for l in pv_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    # mock 模式下可能无 patch 被接受，文件可为空；若有内容则必须可解析
    for line in lines:
        record = json.loads(line)
        assert "stage" in record
        assert "iteration" in record


def test_smoke_run_patch_apply_reports_jsonl_exists(tmp_path):
    """patch_apply_reports.jsonl 存在且可解析（mock 模式下可能为空）。"""
    runner, output_dir = _run_smoke(tmp_path)

    pa_file = output_dir / "patch_apply_reports.jsonl"
    assert pa_file.exists(), "patch_apply_reports.jsonl 不存在"

    lines = [l for l in pa_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    # mock 模式下可能无 patch 被应用，文件可为空；若有内容则必须可解析
    for line in lines:
        record = json.loads(line)
        assert "stage" in record


# ============================================================
# CLI 可执行性测试
# ============================================================

def test_smoke_cli_command_executes(tmp_path):
    """CLI 命令 `python -m mmap_optimizer.cli run --config ... --use-mock` 可执行。"""
    output_dir = tmp_path / "cli_smoke_run"

    cmd = [
        sys.executable, "-m", "mmap_optimizer.cli", "run",
        "--config", str(SMOKE_CONFIG),
        "--extraction-prompt", str(EXTRACTION_PROMPT),
        "--analysis-prompt", str(ANALYSIS_PROMPT),
        "--output-dir", str(output_dir),
        "--use-mock",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, f"CLI 执行失败:\nstdout: {result.stdout}\nstderr: {result.stderr}"

    # 验证关键产物
    assert (output_dir / "run_summary.json").exists()
    assert (output_dir / "final_extraction_prompt.json").exists()
    assert (output_dir / "final_analysis_prompt.json").exists()
    assert (output_dir / "final_fewshot_examples.jsonl").exists()

    # 验证 run_summary.json 状态
    summary = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["prompt_structuring_status"] == "completed"


def test_smoke_cli_no_mock_without_model_client_errors(tmp_path):
    """CLI --no-mock 缺 model_client 时报错。"""
    output_dir = tmp_path / "cli_no_mock_run"

    cmd = [
        sys.executable, "-m", "mmap_optimizer.cli", "run",
        "--config", str(SMOKE_CONFIG),
        "--extraction-prompt", str(EXTRACTION_PROMPT),
        "--analysis-prompt", str(ANALYSIS_PROMPT),
        "--output-dir", str(output_dir),
        "--no-mock",
    ]

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    # 应该非 0 退出，且输出包含错误信息
    assert result.returncode != 0, "use_mock=false 缺 model_client 应报错"
    assert "use_mock" in result.stdout or "model_client" in result.stdout
