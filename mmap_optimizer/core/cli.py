"""重构版 MMAP CLI 入口。

提供命令行接口来运行重构后的 MMAP 系统。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.config import load_config
from ..core.runner import MMAPRunner


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="MMAP 重构版 - Prompt 优化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 使用默认配置运行
  python -m mmap_optimizer.cli run

  # 使用自定义配置运行
  python -m mmap_optimizer.cli run --config configs/default_config.yaml

  # 指定 prompt 文件路径
  python -m mmap_optimizer.cli run \
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
        default="configs/default_config.yaml",
        help="配置文件路径 (默认: configs/default_config.yaml)",
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
    run_parser.add_argument(
        "--use-mock",
        action="store_true",
        default=None,
        help="强制使用 mock executor（用于本地开发 / 无 model_client 环境）",
    )
    run_parser.add_argument(
        "--no-mock",
        action="store_true",
        default=None,
        help="强制使用真实 executor（缺 model_client 时报错）",
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

    # PR4: 解析 use_mock 标志
    use_mock: bool | None = None
    if args.use_mock:
        use_mock = True
    elif args.no_mock:
        use_mock = False

    # 创建运行器
    print("\n初始化 MMAP Runner...")
    try:
        runner = MMAPRunner(
            config=config,
            extraction_prompt_path=extraction_prompt_path,
            analysis_prompt_path=analysis_prompt_path,
            use_mock=use_mock,
        )
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)

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
    if summary.start_time:
        print(f"  开始时间: {summary.start_time}")
    if summary.end_time:
        print(f"  结束时间: {summary.end_time}")
    if summary.duration_seconds is not None:
        print(f"  耗时: {summary.duration_seconds:.3f}s")
    print(f"  Prompt Structuring: {summary.prompt_structuring_status}")

    po = summary.prompt_optimization
    print(f"\n  [Prompt Optimization]")
    print(f"    迭代轮数: {po.iterations}")
    if po.base_accuracy_first is not None:
        print(f"    首轮 base accuracy: {po.base_accuracy_first:.4f}")
    if po.final_accuracy_last is not None:
        print(f"    末轮 final accuracy: {po.final_accuracy_last:.4f}")
    if po.best_accuracy is not None:
        print(f"    最佳 accuracy: {po.best_accuracy:.4f}")
    print(f"    接受/拒绝/测毒 patches: {po.total_accepted_patches}/{po.total_rejected_patches}/{po.total_toxic_patches}")
    print(f"    rollback/no_progress: {po.rollback_count}/{po.no_progress_count}")
    print(f"    compression 触发/接受: {po.compression_triggered_count}/{po.compression_accepted_count}")

    ap = summary.analysis_prompt
    print(f"\n  [Analysis Prompt]")
    if ap.base_accuracy_first is not None:
        print(f"    首轮 base accuracy: {ap.base_accuracy_first:.4f}")
    if ap.final_accuracy_last is not None:
        print(f"    末轮 final accuracy: {ap.final_accuracy_last:.4f}")
    print(f"    接受 patches: {ap.total_accepted_patches}")
    print(f"    rollback/no_progress: {ap.rollback_count}/{ap.no_progress_count}")
    print(f"    compression 触发/接受: {ap.compression_triggered_count}/{ap.compression_accepted_count}")

    fo = summary.fewshot_optimization
    print(f"\n  [Few-shot Optimization]")
    print(f"    迭代轮数: {fo.iterations}")
    if fo.base_accuracy_first is not None:
        print(f"    首轮 base accuracy: {fo.base_accuracy_first:.4f}")
    if fo.final_accuracy_last is not None:
        print(f"    末轮 final accuracy: {fo.final_accuracy_last:.4f}")
    print(f"    accepted: {fo.accepted}")
    print(f"    选中示例数: {len(fo.selected_example_ids)}")

    print(f"\n  最终 Extraction Prompt ID: {summary.final_extraction_prompt_id}")
    print(f"  最终 Analysis Prompt ID: {summary.final_analysis_prompt_id}")
    print(f"  最终 Few-shot 示例数: {summary.final_fewshot_example_count}")

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
    print("  mmap_optimizer")
    print("    ├── core/              # 核心组件")
    print("    │   ├── config.py      # 配置模块")
    print("    │   ├── runner.py      # 主运行器")
    print("    │   ├── logging.py     # 日志配置")
    print("    │   └── cli.py         # CLI 入口")
    print("    ├── data/              # 数据模块")
    print("    │   ├── sample.py      # Sample 三层设计")
    print("    │   ├── dataset_loader.py  # 数据集加载")
    print("    │   └── sampler.py     # 抽样策略")
    print("    ├── phases/            # Phase 定义")
    print("    │   ├── prompt_structuring.py  # Prompt Structuring Phase")
    print("    │   ├── prompt_optimization.py  # Prompt Optimization Phase")
    print("    │   └── fewshot_optimization.py  # Few-shot Optimization Phase")
    print("    ├── stages/            # Stage 定义")
    print("    │   ├── batch_size_controller.py  # Batch Size 控制")
    print("    │   ├── extraction_prompt_optimization.py  # Extraction Stage")
    print("    │   └── analysis_prompt_optimization.py  # Analysis Stage")
    print("    ├── prompt/            # Prompt 模块")
    print("    │   └── structured_prompt.py  # 结构化 Prompt")
    print("    ├── patch/             # Patch 模块")
    print("    │   ├── types.py       # Patch 数据类型")
    print("    │   ├── tree_reduce.py # Tree Merge 算法")
    print("    │   └── ...")
    print("    ├── executors/         # 执行器")
    print("    └── model/             # 模型客户端")

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
