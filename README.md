# MMAP Optimizer

MMAP Optimizer 是一个面向多模态信息抽取任务的 Prompt 自动优化框架。它通过结构化 Prompt、错误分析、语义 Patch 生成、Patch 校验与合并、回归测毒、Prompt 压缩和 Few-shot 示例选择，持续改进 extraction prompt 与 analysis prompt。

项目当前处于 MVP / 实验性阶段，适合用于研究和验证自动 Prompt 优化流程。

## 目录

- [核心能力](#核心能力)
- [工作流概览](#工作流概览)
- [安装](#安装)
- [快速开始](#快速开始)
- [真实模型配置](#真实模型配置)
- [数据格式](#数据格式)
- [配置说明](#配置说明)
- [输出产物](#输出产物)
- [项目结构](#项目结构)
- [测试](#测试)
- [开发说明](#开发说明)
- [Correctness 审计](#correctness-审计)

## 核心能力

- **三阶段优化流程**：Prompt Structuring → Prompt Optimization → Few-shot Optimization。
- **结构化 Prompt IR**：将 Markdown prompt 转为 `StructuredPrompt`，支持 section 级可变 / 保护标记、版本追踪和渲染。
- **盲评分析与反思**：analysis executor 在不看 ground truth 的情况下判断 extraction 输出，再对分析错误样本执行带 ground truth 的反思。
- **语义 Patch 中间层**：支持 semantic patch draft → strict patch translation，降低模型一次性生成严格 JSON Patch 的难度。
- **Patch 校验与自动修复**：`PatchValidator` 会校验 section、operation、定位文本、样本来源，并对可修复定位错误执行一次 calibration。
- **并行 Patch 合并**：按 section 分组，使用确定性 guardrail 与 LLM tree-reduce merge，最后执行 root merge。
- **Patch 应用与文本匹配**：支持 exact match、difflib fuzzy match 和 LLM semantic match 三级定位。
- **Trace2Skill 风格采样**：支持 `balanced_trace`，优先覆盖错误样本、成功样本和低频样本。
- **Sample 级 Patch 经验记忆**：记录每个样本历史 patch 的方向、内容、有效性和毒性，后续同一样本生成 patch 时自动参考。
- **测毒与回归保护**：逐 patch 检查是否破坏原本正确样本，拒绝 toxic / ineffective patch。
- **Prompt 压缩**：按行数和字符数阈值触发压缩，并用 LLM 验证压缩是否保留语义。
- **Few-shot 优化**：维护候选示例池，按 slot 选择更优 few-shot 示例。
- **可追踪产物**：每轮输出 sample trajectory、sample traces、merge report、toxicity report、compression report 等 artifact。

## 工作流概览

```text
Phase 1: Prompt Structuring
  Markdown Prompt
    -> StructuredPrompt
    -> section metadata / mutable flags / version

Phase 2: Prompt Optimization
  Sampling
    -> Extraction Prompt Optimization
      -> extract -> evaluate -> analyze -> generate semantic patches
      -> translate -> validate/calibrate -> merge -> apply
      -> candidate selection -> toxicity test -> compression
    -> Analysis Prompt Optimization
      -> blind analysis quality check -> reflection
      -> generate/validate/merge/apply analysis patches
      -> candidate selection -> toxicity test -> compression

Phase 3: Few-shot Optimization
  Candidate examples
    -> slot evaluation
    -> final few-shot examples
```

## 安装

要求 Python 3.10+。

```bash
git clone <your-repo-url>
cd MMAP

python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,yaml]"
```

如果只运行 smoke/mock 流程，项目没有强制外部模型依赖。真实模型调用需要配置 OpenAI-compatible 服务。

## 快速开始

使用 mock executor 运行 smoke 配置：

```bash
python -m mmap_optimizer.core.cli run \
  --config configs/smoke.yaml \
  --output-dir runs/smoke \
  --use-mock
```

验证配置文件：

```bash
python -m mmap_optimizer.core.cli validate --config configs/smoke.yaml
```

查看系统信息：

```bash
python -m mmap_optimizer.core.cli info --config configs/smoke.yaml
```

也可以使用安装后的命令：

```bash
mmap-optimizer run --config configs/smoke.yaml --use-mock
```

如果你要接入自己的数据，建议先复制 `configs/custom_data.example.yaml`，再把数据路径、图片根目录和模型配置替换成你的环境。

## 真实模型配置

真实 executor 通过 `models.extraction` 和 `models.optimizer` 构建模型客户端。当前支持：

- `provider: mock`
- `provider: openai_compatible`

示例：

```yaml
run:
  seed: 42
  output_dir: runs/real_run
  use_mock: false

models:
  extraction:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    verify_ssl: true
  optimizer:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4o
    api_key_env: OPENAI_API_KEY
    verify_ssl: true
```

运行真实 executor：

```bash
export OPENAI_API_KEY=...
python -m mmap_optimizer.core.cli run \
  --config configs/custom_data.example.yaml \
  --output-dir runs/real_run \
  --no-mock
```

上面的命令要求你已经把 `configs/custom_data.example.yaml` 里的 `models.extraction` 和 `models.optimizer` 补好；如果还没配模型，先保持 `use_mock: true`，用 `--use-mock` 验证数据格式。

`--no-mock` 会强制使用真实 executor；如果配置中没有有效模型客户端，程序会直接报错，避免静默退回 mock。

## 数据格式

默认数据集使用 JSONL，每行一个样本。推荐先参考 `data/custom_samples.example.jsonl`，它覆盖了纯文本、单图和多图三种输入形态。

### 样本示例

```json
{
  "id": "sample_multi_001",
  "input": {"text": "同一产品的正反面与局部细节"},
  "ground_truth": {"result": "NG", "defect": "scratch"},
  "assets": [
    {
      "id": "asset_001",
      "type": "image",
      "local_path": "images/sample_multi_001_front.png",
      "mime_type": "image/png"
    },
    {
      "id": "asset_002",
      "type": "image",
      "local_path": "images/sample_multi_001_back.png",
      "mime_type": "image/png"
    },
    {
      "id": "asset_003",
      "type": "image",
      "local_path": "images/sample_multi_001_detail.png",
      "mime_type": "image/png"
    }
  ],
  "tags": ["correct", "fewshot_candidate"],
  "metadata": {"source": "demo"}
}
```

`assets` 是样本级图片集合：单图样本可直接放 1 张图，多图样本则按数组顺序提供同一样本的多张图片，模型需要综合全部图片后输出一个最终标签。`assets` 缺省时表示纯文本样本。

### 自定义接入方式

推荐把自己的数据拆成下面 3 个文件：

- `dataset.path` 指向样本 JSONL，例如 `data/custom_samples.jsonl`
- `dataset.image_root` 指向图片目录根，例如 `data/custom_images`
- `dataset.ground_truth_path` 指向独立标签文件，例如 `data/custom_ground_truth.jsonl`

如果你的 ground truth 已经内嵌在样本里，可以把 `ground_truth_path` 留空。`DatasetLoader` 也兼容旧字段：

- `input` 是推荐的样本输入字段，历史数据里如果写成 `data` 也能读
- `ground_truth` 是推荐的标签字段，历史数据里如果写成 `gt` 也能读
- `assets[*].local_path` 会在读取时按 `image_root` 逐个补全

`data/custom_samples.example.jsonl` 和 `data/custom_ground_truth.example.jsonl` 已经给出可复制的模板。

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 样本唯一 ID |
| `input` | 是 | 推荐的文本或结构化输入字段；兼容旧字段 `data` |
| `ground_truth` | 是 | 推荐的评估标签字段；若使用外部标签文件则可留空并由 `ground_truth_path` 合并 |
| `assets` | 否 | 样本级图片等多模态资产，支持 0/1/N 张图 |
| `tags` | 否 | 样本标签，可用于分析或扩展采样 |
| `metadata` | 否 | 额外元数据 |

参考样例见 `data/smoke_samples.jsonl`（smoke 回归数据）和 `data/custom_samples.example.jsonl`（自定义接入模板）。

## 配置说明

项目配置分为以下顶层块：

| 配置块 | 说明 |
| --- | --- |
| `run` | seed、输出目录、是否使用 mock、日志级别、进度显示 |
| `dataset` | 数据路径、格式、图片根目录、外部 ground truth 路径 |
| `prompts` | 各类 prompt 模板路径 |
| `prompt_structuring` | Prompt 结构化配置 |
| `sampling` | 全局采样配置 |
| `prompt_optimization` | Prompt 优化轮数、batch size、patch、压缩、采样策略 |
| `fewshot_optimization` | Few-shot 轮数、batch size、slot 数 |
| `models` | 真实模型客户端配置 |

### Prompt Optimization 采样

默认 sampler 是 `difficulty_frequency`。可选类型：

- `random`
- `difficulty`
- `frequency`
- `difficulty_frequency`
- `balanced_trace`

`balanced_trace` 示例：

```yaml
prompt_optimization:
  sampler:
    type: balanced_trace
    difficulty_weight: 0.7
    frequency_weight: 0.3
    error_ratio: 0.6
    success_ratio: 0.25
    low_frequency_ratio: 0.15
    fallback_to_difficulty_frequency: true
```

完整示例见 `configs/default_config.yaml` 和 `configs/smoke.yaml`。
如果你要接自己的数据，建议优先从 `configs/custom_data.example.yaml` 复制一份。

## 运行输出与日志

- 终端输出用于观察当前执行进度：phase、stage、step、样本处理进度和阶段指标。
- 调试日志默认写入 `run.output_dir/logs/mmap.log`，用于排查模型调用、patch、merge、压缩和 checkpoint 问题。
- 模型连续失败和重试明细保留在 `model_call_failures.jsonl`。
- 可通过 `run.log_level` 调整日志级别，通过 `run.progress_enabled` 或环境变量 `MMAP_DISABLE_PROGRESS=1` 关闭进度输出。

## 输出产物

每次运行会在 `run.output_dir` 下生成可审计产物，常见文件包括：

```text
runs/<run_id>/
├── run_summary.json
├── run_plan.json
├── run_config.yaml
├── run_config.json
├── structured_extraction_prompt.json
├── structured_analysis_prompt.json
├── final_extraction_prompt.json
├── final_analysis_prompt.json
├── final_fewshot_examples.jsonl
├── sample_states.json
├── model_call_failures.jsonl
├── logs/
│   └── mmap.log
└── prompt_optimization/
    └── iteration_1/
        ├── sample_batch.json
        ├── sampling_plan.json
        ├── sample_traces.jsonl
        ├── sample_optimization_trajectory.jsonl
        ├── extraction/
        │   ├── base_results.jsonl
        │   ├── analysis_results.jsonl
        │   ├── semantic_patch_drafts.jsonl
        │   ├── translated_patches.jsonl
        │   ├── draft_patches.jsonl
        │   ├── validated_patches.jsonl
        │   ├── rejected_patches.jsonl
        │   ├── toxicity_report.json
        │   ├── compression_report.json
        │   └── metrics.json
        └── analysis/
            └── ...
```

重点 artifact：

| 文件 | 说明 |
| --- | --- |
| `sample_traces.jsonl` | 每个样本在本轮中的选择、分析、patch、transition 记录 |
| `sample_optimization_trajectory.jsonl` | 以 sample 为中心的优化轨迹，包含分析、反思、patch 尝试、回归和测毒结果 |
| `logs/mmap.log` | 运行调试日志，用于排查功能问题 |
| `model_call_failures.jsonl` | 模型调用失败和重试记录 |
| `semantic_patch_drafts.jsonl` | LLM 生成的语义 patch 草稿 |
| `translated_patches.jsonl` | semantic patch 翻译后的严格 patch |
| `model_output_repairs.jsonl` | LLM 输出解析修复记录 |
| `toxicity_report.json` | patch 测毒结果 |
| `compression_report.json` | Prompt 压缩触发、验证和接受情况 |

## 项目结构

```text
mmap_optimizer/
├── core/                 # 配置、CLI、Runner
├── data/                 # SampleSpec / SampleState / SampleBatch / sampler
├── executors/            # 抽取、分析、patch 生成、应用、合并、测毒、压缩、few-shot
├── model/                # Mock 与 OpenAI-compatible 模型客户端
├── patch/                # Patch 类型、合并、冲突检测、文本匹配
├── phases/               # 三阶段流程编排
├── prompt/               # StructuredPrompt、prompt manager、输出修复
└── stages/               # Prompt optimization 内部 stage

configs/                  # 默认配置和 smoke 配置
data/                     # 示例数据
prompts/                  # 所有 LLM prompt 模板
tests/                    # 单元测试、集成测试、smoke 测试
```

## 测试

运行全部测试：

```bash
.venv/bin/python -m pytest -q
```

常用定向测试：

```bash
.venv/bin/python -m pytest tests/test_pr4_smoke.py -q
.venv/bin/python -m pytest tests/test_trace2skill_improvements.py -q
.venv/bin/python -m pytest tests/test_trace2skill_sampling.py -q
```

检查 diff 空白问题：

```bash
git diff --check
```

## 开发说明

## Correctness 审计

项目把 correctness 检查聚焦到“状态真相如何产生、如何落盘、如何被下一轮消费”这条主链。
更完整的字段分层、writer ownership 与 mock/real 对齐检查可见
`docs/correctness_audit.md`。

- 默认配置优先保持 mock 可运行，方便本地验证流程和 artifact。
- 真实模型调用通过 `models.*` 配置控制，`--no-mock` 会显式禁止 mock fallback。
- 新增 LLM prompt 时，应同步更新 `PromptsConfig`、`prompts/README.md` 和相关测试。
- 新增 artifact 时，应优先使用统一 artifact writer，保证 JSON 可序列化且不落无意义空字段。
- 新增采样策略时，应确保 `SampleBatch.metadata` 写明来源和 fallback 行为，便于复现实验。

## License

当前仓库未声明许可证。正式发布前请补充 LICENSE 文件。
