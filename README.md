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

## 核心能力

- **三阶段优化流程**：Prompt Structuring → Prompt Optimization → Few-shot Optimization。
- **结构化 Prompt IR**：将 Markdown prompt 转为 `StructuredPrompt`，支持 section 级可变 / 保护标记、版本追踪和渲染。
- **盲评分析与反思**：analysis executor 在不看 ground truth 的情况下判断 extraction 输出，再对分析错误样本执行带 ground truth 的反思。
- **语义 Patch 中间层**：支持 semantic patch draft → strict patch translation，降低模型一次性生成严格 JSON Patch 的难度。
- **Patch 校验与自动修复**：`PatchValidator` 会校验 section、operation、定位文本、样本来源，并对可修复定位错误执行一次 calibration。
- **并行 Patch 合并**：按 section 分组，使用确定性 guardrail 与 LLM tree-reduce merge，最后执行 root merge。
- **Patch 应用与文本匹配**：支持 exact match、difflib fuzzy match 和 LLM semantic match 三级定位。
- **候选 Patch 验证选择**：支持 candidate patch set 打分，选择固定 / 破坏样本权衡更优的候选。
- **Trace2Skill 风格采样**：支持 `balanced_trace`、validation pool 和 multi-seed candidate batch。
- **测毒与回归保护**：逐 patch 检查是否破坏原本正确样本，拒绝 toxic / ineffective patch。
- **Prompt 压缩**：按行数和字符数阈值触发压缩，并用 LLM 验证压缩是否保留语义。
- **Few-shot 优化**：维护候选示例池，按 slot 选择更优 few-shot 示例。
- **可追踪产物**：每轮输出 sample traces、patch lifecycle、candidate report、merge report、compression report 等 artifact。

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
  --config configs/default_config.yaml \
  --output-dir runs/real_run \
  --no-mock
```

`--no-mock` 会强制使用真实 executor；如果配置中没有有效模型客户端，程序会直接报错，避免静默退回 mock。

## 数据格式

默认数据集使用 JSONL，每行一个样本。示例：

```json
{
  "id": "sample_001",
  "input": {"text": "需要处理的输入"},
  "ground_truth": {"result": "期望答案"},
  "assets": [
    {
      "id": "asset_001",
      "type": "image",
      "local_path": "images/sample_001.png",
      "mime_type": "image/png"
    }
  ],
  "tags": ["correct", "fewshot_candidate"],
  "metadata": {"source": "demo"}
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 样本唯一 ID |
| `input` | 是 | 文本或结构化输入 |
| `ground_truth` | 是 | 评估用标准答案 |
| `assets` | 否 | 图片等多模态资产 |
| `tags` | 否 | 样本标签，可用于分析或扩展采样 |
| `metadata` | 否 | 额外元数据 |

参考样例见 `data/smoke_samples.jsonl`。

## 配置说明

项目配置分为以下顶层块：

| 配置块 | 说明 |
| --- | --- |
| `run` | seed、输出目录、是否使用 mock |
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

### Candidate Selection 与 Multi-seed

```yaml
prompt_optimization:
  patch:
    candidate_selection:
      enabled: true
      candidate_count: 3
      validation_split_ratio: 0.3
      min_gain: 0.0
      reject_on_any_broken: true
      validation_pool_enabled: true
      validation_batch_size: null
      validation_exclude_optimization_batch: true

  multi_seed:
    enabled: false
    seed_count: 3
    candidate_batch_size: null
    merge_candidates_before_selection: true
```

说明：

- `candidate_selection.enabled` 默认关闭，开启后会对多个 patch set 打分选择。
- `validation_pool_enabled` 开启时，会从 optimization batch 之外抽 validation batch。
- `multi_seed.enabled` 默认关闭，因为真实模型调用成本会随 seed 数增加。

完整示例见 `configs/default_config.yaml` 和 `configs/smoke.yaml`。

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
└── prompt_optimization/
    └── iteration_1/
        ├── sample_batch.json
        ├── validation_batch.json
        ├── candidate_batches.jsonl
        ├── sampling_plan.json
        ├── sample_traces.jsonl
        ├── extraction/
        │   ├── base_results.jsonl
        │   ├── analysis_results.jsonl
        │   ├── semantic_patch_drafts.jsonl
        │   ├── translated_patches.jsonl
        │   ├── draft_patches.jsonl
        │   ├── validated_patches.jsonl
        │   ├── rejected_patches.jsonl
        │   ├── candidate_validation_report.json
        │   ├── patch_lifecycle.jsonl
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
| `semantic_patch_drafts.jsonl` | LLM 生成的语义 patch 草稿 |
| `translated_patches.jsonl` | semantic patch 翻译后的严格 patch |
| `patch_lifecycle.jsonl` | patch 从生成、校验、合并、测毒到最终接受/拒绝的生命周期 |
| `candidate_validation_report.json` | candidate patch set 的验证打分和选择结果 |
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

- 默认配置优先保持 mock 可运行，方便本地验证流程和 artifact。
- 真实模型调用通过 `models.*` 配置控制，`--no-mock` 会显式禁止 mock fallback。
- 新增 LLM prompt 时，应同步更新 `PromptsConfig`、`prompts/README.md` 和相关测试。
- 新增 artifact 时，应优先使用 `to_dict()` 保持 JSON 可序列化。
- 新增采样策略时，应确保 `SampleBatch.metadata` 写明来源和 fallback 行为，便于复现实验。

## License

当前仓库未声明许可证。正式发布前请补充 LICENSE 文件。
