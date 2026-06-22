"""重构版 MMAP CLI 入口。

提供命令行接口来运行重构后的 MMAP 系统。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config
from .runner import MMAPRunner


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="MMAP 重构版 - Prompt 优化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 使用默认配置运行
  python -m mmap_optimizer.refactored.cli run

  # 使用自定义配置运行
  python -m mmap_optimizer.refactored.cli run --config configs/refactored_config.yaml

  # 指定 prompt 文件路径
  python -m mmap_optimizer.refactored.cli run \
    --extraction-prompt prompts/extraction.txt \
    --analysis-prompt prompts/analysis.txt
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="运行 MMAP 优化流程")
    run_parser.add_argument(
        "--config",
        type=str,
        default="configs/refactored_config.yaml",
        help="配置文件路径 (默认: configs/refactored_config.yaml)",
    )
    run_parser.add_argument(
        "--extraction-prompt",
        type=str,
        default="prompts/extraction.txt",
        help="Extraction prompt 文件路径 (默认: prompts/extraction.txt)",
    )
    run_parser.add_argument(
        "--analysis-prompt",
        type=str,
        default="prompts/analysis.txt",
        help="Analysis prompt 文件路径 (默认: prompts/analysis.txt)",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        help="输出目录 (覆盖配置文件中的设置)",
    )

    # validate 命令
    validate_parser = subparsers.add_parser("validate", help="验证配置文件")
    validate_parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="配置文件路径",
    )

    # info 命令
    info_parser = subparsers.add_parser("info", help="显示系统信息")
    info_parser.add_argument(
        "--config",
        type=str,
        help="配置文件路径",
    )

    args = parser.parse_args()

    if args.command == "run":
        run_command(args)
    elif args.command == "validate":
        validate_command(args)
    elif args.command == "info":
        info_command(args)
    else:
        parser.print_help()


def run_command(args: argparse.Namespace) -> None:
    """执行 run 命令。"""
    print("=" * 60)
    print("MMAP 重构版 - Prompt 优化系统")
    print("=" * 60)

    # 加载配置
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return

    print(f"\n加载配置: {config_path}")
    config = load_config(config_path)

    # 覆盖输出目录（如果指定）
    if args.output_dir:
        config.run.output_dir = args.output_dir

    # 检查 prompt 文件
    extraction_prompt_path = Path(args.extraction_prompt)
    analysis_prompt_path = Path(args.analysis_prompt)

    if not extraction_prompt_path.exists():
        print(f"错误: Extraction prompt 文件不存在: {extraction_prompt_path}")
        return

    if not analysis_prompt_path.exists():
        print(f"错误: Analysis prompt 文件不存在: {analysis_prompt_path}")
        return

    print(f"Extraction prompt: {extraction_prompt_path}")
    print(f"Analysis prompt: {analysis_prompt_path}")
    print(f"输出目录: {config.run.output_dir}")

    # 创建运行器
    print("\n初始化 MMAP Runner...")
    runner = MMAPRunner(
        config=config,
        extraction_prompt_path=extraction_prompt_path,
        analysis_prompt_path=analysis_prompt_path,
    )

    # 显示 Run Plan
    print("\nRun Plan:")
    for i, step in enumerate(runner.run_plan.steps):
        print(f"  {i + 1}. {step.id} ({step.phase})")

    # 执行运行
    print("\n开始执行...")
    print("-" * 60)

    summary = runner.run()

    # 显示结果
    print("-" * 60)
    print("\n运行完成!")
    print("\nRun Summary:")
    print(f"  状态: {summary.status}")
    print(f"  Prompt Structuring: {summary.prompt_structuring_completed}")
    print(f"  Prompt Optimization 轮数: {summary.prompt_optimization_rounds}")
    print(f"  Few-shot Optimization 轮数: {summary.fewshot_optimization_rounds}")
    print(f"  最终 Extraction Prompt ID: {summary.final_extraction_prompt_id}")
    print(f"  最终 Analysis Prompt ID: {summary.final_analysis_prompt_id}")
    print(f"  最终 Few-shot 示例数: {summary.final_fewshot_example_count}")
    print(f"  Extraction Patch 接受数: {summary.total_extraction_accepted_patches}")
    print(f"  Analysis Patch 接受数: {summary.total_analysis_accepted_patches}")

    if summary.extraction_accuracy_delta is not None:
        print(f"  Extraction 准确率变化: {summary.extraction_accuracy_delta:.4f}")

    if summary.analysis_accuracy_delta is not None:
        print(f"  Analysis 准确率变化: {summary.analysis_accuracy_delta:.4f}")

    if summary.fewshot_accuracy_delta is not None:
        print(f"  Few-shot 准确率变化: {summary.fewshot_accuracy_delta:.4f}")

    print(f"\n输出目录: {config.run.output_dir}")
    print("=" * 60)


def validate_command(args: argparse.Namespace) -> None:
    """执行 validate 命令。"""
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return

    print(f"验证配置文件: {config_path}")

    try:
        config = load_config(config_path)
        print("\n配置加载成功!")
        print("\n配置内容:")
        print(json.dumps(config.to_dict(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\n配置加载失败: {e}")


def info_command(args: argparse.Namespace) -> None:
    """执行 info 命令。"""
    print("=" * 60)
    print("MMAP 重构版 - 系统信息")
    print("=" * 60)

    print("\n模块结构:")
    print("  mmap_optimizer.refactored")
    print("    ├── sample.py          # Sample 三层设计")
    print("    ├── dataset_loader.py  # 数据集加载")
    print("    ├── sampler.py         # 抽样策略")
    print("    ├── batch_size_controller.py  # Batch Size 控制")
    print("    ├── structured_prompt.py  # 结构化 Prompt")
    print("    ├── prompt_structuring_phase.py  # Prompt Structuring Phase")
    print("    ├── patch.py           # Patch 模型")
    print("    ├── extraction_prompt_optimization_stage.py  # Extraction Stage")
    print("    ├── analysis_prompt_optimization_stage.py  # Analysis Stage")
    print("    ├── prompt_optimization_phase.py  # Prompt Optimization Phase")
    print("    ├── fewshot_optimization_phase.py  # Few-shot Optimization Phase")
    print("    ├── config.py          # 配置模块")
    print("    ├── runner.py          # 主运行器")
    print("    └── cli.py             # CLI 入口")

    print("\n三阶段流程:")
    print("  1. Prompt Structuring Phase")
    print("  2. Prompt Optimization Phase")
    print("     ├── Sampling Stage")
    print("     ├── Extraction Prompt Optimization Stage")
    print("     └── Analysis Prompt Optimization Stage")
    print("  3. Few-shot Optimization Phase")
    print("     ├── Sampling Stage")
    print("     └── Few-shot Optimization Stage")

    if args.config:
        config_path = Path(args.config)
        if config_path.exists():
            print(f"\n配置文件: {config_path}")
            config = load_config(config_path)
            print(f"  Prompt Optimization 轮数: {config.prompt_optimization.rounds}")
            print(f"  Few-shot Optimization 轮数: {config.fewshot_optimization.rounds}")
            print(f"  初始 Batch Size: {config.prompt_optimization.initial_batch_size}")
            print(f"  Few-shot 槽位数: {config.fewshot_optimization.slot_count}")

    print("=" * 60)


if __name__ == "__main__":
    main()