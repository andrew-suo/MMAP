"""重构版 MMAP CLI 入口。

提供命令行接口来运行重构后的 MMAP 系统。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..core.config import load_config
from ..core.fewshot_only import FewshotOnlyOptimizer
from ..core.latest_prompt_eval import LatestPromptEvaluator
from ..core.progress import ProgressReporter
from ..core.runner import MMAPRunner


def main() -> None:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="MMAP 重构版 - Prompt 优化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # 使用默认配置运行
  python -m mmap_optimizer.core.cli run

  # 使用自定义配置运行
  python -m mmap_optimizer.core.cli run --config configs/default_config.yaml

  # 指定 prompt 文件路径
  python -m mmap_optimizer.core.cli run \
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
        default=None,
        help="Extraction prompt 文件路径 (覆盖配置文件中的 prompts.extraction)",
    )
    run_parser.add_argument(
        "--analysis-prompt",
        type=str,
        default=None,
        help="Analysis prompt 文件路径 (覆盖配置文件中的 prompts.analysis)",
    )
    run_parser.add_argument(
        "--analysis-reflection-prompt",
        type=str,
        default=None,
        help="Analysis reflection 消息模板文件路径 (覆盖配置文件中的 prompts.analysis_reflection)",
    )
    run_parser.add_argument(
        "--prompt-standardization",
        type=str,
        default=None,
        help="Prompt 标准化模板文件路径 (覆盖配置文件中的 prompts.prompt_standardization)",
    )
    run_parser.add_argument(
        "--patch-generation-prompt",
        type=str,
        default=None,
        help="Patch 生成模板文件路径 (覆盖配置文件中的 prompts.patch_generation)",
    )
    run_parser.add_argument(
        "--patch-calibration-prompt",
        type=str,
        default=None,
        help="Patch 校准模板文件路径 (覆盖配置文件中的 prompts.patch_calibration)",
    )
    run_parser.add_argument(
        "--patch-merge-prompt",
        type=str,
        default=None,
        help="Patch 合并模板文件路径 (覆盖配置文件中的 prompts.patch_merge)",
    )
    run_parser.add_argument(
        "--patch-root-merge-prompt",
        type=str,
        default=None,
        help="Patch Root Merge 模板文件路径 (覆盖配置文件中的 prompts.patch_root_merge)",
    )
    run_parser.add_argument(
        "--patch-text-match-prompt",
        type=str,
        default=None,
        help="Patch 文本匹配模板文件路径 (覆盖配置文件中的 prompts.patch_text_match)",
    )
    run_parser.add_argument(
        "--output-dir",
        type=str,
        help="输出目录 (覆盖配置文件中的设置)",
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="从输出目录中的 checkpoint.json 继续运行",
    )
    run_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="忽略已有 checkpoint，从头开始运行",
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

    # eval-latest 命令
    eval_parser = subparsers.add_parser("eval-latest", help="用最新 extraction prompt 做全量抽取验证")
    eval_parser.add_argument(
        "--config",
        type=str,
        default="configs/default_config.yaml",
        help="配置文件路径 (默认: configs/default_config.yaml)",
    )
    eval_parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="运行目录，默认使用配置中的 run.output_dir",
    )
    eval_parser.add_argument(
        "--artifact-dir",
        type=str,
        default=None,
        help="评估产物输出目录，默认写到 <run-dir>/evaluations/eval_latest_<timestamp>",
    )
    eval_parser.add_argument(
        "--use-mock",
        action="store_true",
        default=None,
        help="强制使用 mock executor 做抽取验证",
    )
    eval_parser.add_argument(
        "--no-mock",
        action="store_true",
        default=None,
        help="强制使用真实 executor 做抽取验证",
    )

    fewshot_only_parser = subparsers.add_parser(
        "optimize-fewshot",
        help="针对已有 extraction prompt 单独优化 few-shot",
    )
    fewshot_only_parser.add_argument(
        "--config",
        type=str,
        default="configs/default_config.yaml",
        help="配置文件路径 (默认: configs/default_config.yaml)",
    )
    prompt_source_group = fewshot_only_parser.add_mutually_exclusive_group(required=True)
    prompt_source_group.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="已有 run 目录，从其中解析最新 extraction prompt",
    )
    prompt_source_group.add_argument(
        "--prompt-file",
        type=str,
        default=None,
        help="extraction prompt 文件路径，支持结构化 JSON 或原始文本/Markdown",
    )
    fewshot_only_parser.add_argument(
        "--initial-fewshot-file",
        type=str,
        default=None,
        help="初始 few-shot examples JSONL，优先级高于 run-dir 自带 few-shot",
    )
    fewshot_only_parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="few-shot-only 产物输出目录",
    )
    fewshot_only_parser.add_argument(
        "--use-mock",
        action="store_true",
        default=None,
        help="强制使用 mock executor",
    )
    fewshot_only_parser.add_argument(
        "--no-mock",
        action="store_true",
        default=None,
        help="强制使用真实 executor",
    )

    args = parser.parse_args()

    if args.command == "run":
        run_command(args)
    elif args.command == "eval-latest":
        eval_latest_command(args)
    elif args.command == "optimize-fewshot":
        optimize_fewshot_command(args)
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

    # 仅当命令行显式指定时才覆盖配置文件中的 prompt 路径
    # 未指定时使用 config 中的值（来自 YAML 或 dataclass 默认值）
    if args.extraction_prompt is not None:
        config.prompts.extraction = str(args.extraction_prompt)
    if args.analysis_prompt is not None:
        config.prompts.analysis = str(args.analysis_prompt)
    if args.analysis_reflection_prompt is not None:
        config.prompts.analysis_reflection = str(args.analysis_reflection_prompt)
    if args.prompt_standardization is not None:
        config.prompts.prompt_standardization = str(args.prompt_standardization)
    if args.patch_generation_prompt is not None:
        config.prompts.patch_generation = str(args.patch_generation_prompt)
    if args.patch_calibration_prompt is not None:
        config.prompts.patch_calibration = str(args.patch_calibration_prompt)
    if args.patch_merge_prompt is not None:
        config.prompts.patch_merge = str(args.patch_merge_prompt)
    if args.patch_root_merge_prompt is not None:
        config.prompts.patch_root_merge = str(args.patch_root_merge_prompt)
    if args.patch_text_match_prompt is not None:
        config.prompts.patch_text_match = str(args.patch_text_match_prompt)
    # standardization_prompt_path 同步自 prompts.prompt_standardization
    config.prompt_structuring.standardization_prompt_path = config.prompts.prompt_standardization

    # 检查 prompt 文件存在性（使用合并后的 config 路径）
    extraction_prompt_path = Path(config.prompts.extraction)
    analysis_prompt_path = Path(config.prompts.analysis)
    analysis_reflection_prompt_path = Path(config.prompts.analysis_reflection)
    prompt_standardization_path = Path(config.prompts.prompt_standardization)
    patch_generation_prompt_path = Path(config.prompts.patch_generation)
    patch_calibration_prompt_path = Path(config.prompts.patch_calibration)
    patch_merge_prompt_path = Path(config.prompts.patch_merge)
    patch_root_merge_prompt_path = Path(config.prompts.patch_root_merge)
    patch_text_match_prompt_path = Path(config.prompts.patch_text_match)

    if not extraction_prompt_path.exists():
        print(f"错误: Extraction prompt 文件不存在: {extraction_prompt_path}")
        return

    if not analysis_prompt_path.exists():
        print(f"错误: Analysis prompt 文件不存在: {analysis_prompt_path}")
        return

    if not analysis_reflection_prompt_path.exists():
        print(f"错误: Analysis reflection prompt 文件不存在: {analysis_reflection_prompt_path}")
        return

    if not prompt_standardization_path.exists():
        print(f"错误: Prompt standardization 文件不存在: {prompt_standardization_path}")
        return

    if not patch_generation_prompt_path.exists():
        print(f"错误: Patch generation prompt 文件不存在: {patch_generation_prompt_path}")
        return

    if not patch_calibration_prompt_path.exists():
        print(f"错误: Patch calibration prompt 文件不存在: {patch_calibration_prompt_path}")
        return

    if not patch_merge_prompt_path.exists():
        print(f"错误: Patch merge prompt 文件不存在: {patch_merge_prompt_path}")
        return

    if not patch_root_merge_prompt_path.exists():
        print(f"错误: Patch root merge prompt 文件不存在: {patch_root_merge_prompt_path}")
        return

    if not patch_text_match_prompt_path.exists():
        print(f"错误: Patch text match prompt 文件不存在: {patch_text_match_prompt_path}")
        return

    print(f"Extraction prompt: {extraction_prompt_path}")
    print(f"Analysis prompt: {analysis_prompt_path}")
    print(f"Analysis reflection prompt: {analysis_reflection_prompt_path}")
    print(f"Prompt standardization: {prompt_standardization_path}")
    print(f"Patch generation prompt: {patch_generation_prompt_path}")
    print(f"Patch calibration prompt: {patch_calibration_prompt_path}")
    print(f"Patch merge prompt: {patch_merge_prompt_path}")
    print(f"Patch root merge prompt: {patch_root_merge_prompt_path}")
    print(f"Patch text match prompt: {patch_text_match_prompt_path}")
    print(f"输出目录: {config.run.output_dir}")
    if args.resume and not args.no_resume:
        print("Resume: enabled")

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

    summary = runner.run(resume=bool(args.resume and not args.no_resume))

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


def eval_latest_command(args: argparse.Namespace) -> None:
    """执行 eval-latest 命令。"""
    print("=" * 60)
    print("MMAP - Latest Extraction Prompt Full Evaluation")
    print("=" * 60)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return

    print(f"\n加载配置: {config_path}")
    config = load_config(config_path)

    run_dir = Path(args.run_dir) if args.run_dir else Path(config.run.output_dir)
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else None

    use_mock: bool | None = None
    if args.use_mock:
        use_mock = True
    elif args.no_mock:
        use_mock = False

    print(f"Run 目录: {run_dir}")
    if artifact_dir is not None:
        print(f"评估输出目录: {artifact_dir}")
    if use_mock is True:
        print("Mode: mock")
    elif use_mock is False:
        print("Mode: real")

    evaluator = LatestPromptEvaluator(
        config,
        run_dir=run_dir,
        artifact_dir=artifact_dir,
        use_mock=use_mock,
        progress_reporter=ProgressReporter(enabled=config.run.progress_enabled),
    )
    try:
        result = evaluator.run()
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)

    summary = result.summary
    print("-" * 60)
    print("\n评估完成!")
    print(f"Prompt: {result.prompt_path}")
    print(f"Few-shot: {result.fewshot_path or '(none)'}")
    print(f"Total/Correct/Wrong/Invalid: {summary.total_count}/{summary.correct_count}/{summary.wrong_count}/{summary.invalid_count}")
    print(f"Exact-match Accuracy: {summary.exact_match_accuracy:.4f}")
    print(f"Artifacts: {result.artifact_dir}")
    print("=" * 60)


def optimize_fewshot_command(args: argparse.Namespace) -> None:
    """执行 optimize-fewshot 命令。"""
    print("=" * 60)
    print("MMAP - Standalone Few-shot Optimization")
    print("=" * 60)

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return

    print(f"\n加载配置: {config_path}")
    config = load_config(config_path)

    run_dir = Path(args.run_dir) if args.run_dir else None
    prompt_file = Path(args.prompt_file) if args.prompt_file else None
    initial_fewshot_file = (
        Path(args.initial_fewshot_file) if args.initial_fewshot_file else None
    )
    output_dir = Path(args.output_dir) if args.output_dir else None

    if prompt_file is not None and not prompt_file.exists():
        print(f"错误: prompt 文件不存在: {prompt_file}")
        return
    if run_dir is not None and not run_dir.exists():
        print(f"错误: run 目录不存在: {run_dir}")
        return
    if initial_fewshot_file is not None and not initial_fewshot_file.exists():
        print(f"错误: 初始 few-shot 文件不存在: {initial_fewshot_file}")
        return

    use_mock: bool | None = None
    if args.use_mock:
        use_mock = True
    elif args.no_mock:
        use_mock = False

    if run_dir is not None:
        print(f"Prompt 来源 run 目录: {run_dir}")
    if prompt_file is not None:
        print(f"Prompt 文件: {prompt_file}")
    if initial_fewshot_file is not None:
        print(f"初始 Few-shot 文件: {initial_fewshot_file}")
    if output_dir is not None:
        print(f"输出目录: {output_dir}")
    if use_mock is True:
        print("Mode: mock")
    elif use_mock is False:
        print("Mode: real")

    optimizer = FewshotOnlyOptimizer(
        config,
        run_dir=run_dir,
        prompt_file=prompt_file,
        initial_fewshot_file=initial_fewshot_file,
        artifact_dir=output_dir,
        use_mock=use_mock,
        progress_reporter=ProgressReporter(enabled=config.run.progress_enabled),
    )
    try:
        result = optimizer.run()
    except RuntimeError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"错误: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    summary = result.summary
    print("-" * 60)
    print("\n优化完成!")
    print(f"Prompt: {result.prompt_path}")
    print(f"Initial Few-shot: {result.initial_fewshot_path or '(none)'}")
    print(f"Iterations: {summary.iterations}")
    if summary.base_accuracy_first is not None:
        print(f"Base Accuracy: {summary.base_accuracy_first:.4f}")
    if summary.final_accuracy_last is not None:
        print(f"Final Accuracy: {summary.final_accuracy_last:.4f}")
    print(f"Accepted: {summary.accepted}")
    print(f"Initial/Final Few-shot Count: {summary.initial_fewshot_count}/{summary.final_fewshot_count}")
    print(f"Artifacts: {result.artifact_dir}")
    print("=" * 60)


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
