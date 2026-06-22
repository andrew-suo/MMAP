# 统一数据集与抽样器底座 Spec

## Why

当前 `mmap_optimizer/dataset/` 与 `mmap_optimizer/sampling/` 是分散的函数式实现：

- [dataset/sample.py](file:///workspace/mmap_optimizer/dataset/sample.py) 中 `Sample` 没有 `input` / `ground_truth` / `tags` 字段，`ground_truth` 是独立对象而非 sample 内嵌字段，`SampleState` 缺少 `selected_count` / `last_status` / `difficulty_score`。
- [dataset/loader.py](file:///workspace/mmap_optimizer/dataset/loader.py) 只提供 `load_samples` / `load_ground_truths` / `load_assets` 三个扁平函数，没有 `SampleSet` 聚合、没有 `DatasetLoader` 协议、没有 `DatasetSource` 描述。
- [sampling/optimization_sampler.py](file:///workspace/mmap_optimizer/sampling/optimization_sampler.py) 与 [sampling/dynamic_validation_sampler.py](file:///workspace/mmap_optimizer/sampling/dynamic_validation_sampler.py) 各自返回 `list[Sample]` 或 `DynamicValidationBatch`，没有统一的 `Sampler` 协议、`SampleRequest` / `SamplingContext` / `SampleBatch` 抽象，prompt 优化与 few-shot 优化无法用同一接口拿样本。

重构目标：建立统一数据底座，将原始数据集加载为标准 `SampleSet`，提供通用 `Sampler` 能力，使 prompt optimization 与 few-shot optimization 都只依赖抽样结果，不直接关心原始数据格式。该底座是 `refactor-split-prompt-fewshot-phases` spec 中两个 phase runner 的共同依赖。

## What Changes

- **NEW** 新增 `SampleSet` 聚合，统一维护 `samples` / `states` / `metadata`，提供 `active_samples()` / `get()` / `update_state()` / `composition()` 方法。
- **NEW** 新增 `DatasetSource` dataclass（`path` / `format` / `image_root` / `schema` / `metadata`）与 `DatasetLoader` Protocol，内置 `JsonlDatasetLoader` / `JsonDatasetLoader` / `FolderDatasetLoader`。
- **NEW** 新增 `Sampler` Protocol、`SampleRequest`、`SamplingContext`、`SampleBatch` 抽象。
- **NEW** 新增内置 sampler：`FullSampler` / `RandomSampler` / `HardCaseSampler` / `RegressionGuardSampler` / `StratifiedSampler` / `CompositeSampler`。
- **MODIFIED** `Sample` dataclass 字段重构为 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags` / `active`，将 `ground_truth` 与 `assets` 内嵌到 sample 内。**BREAKING**：移除 `ground_truth_id` / `asset_ids` / `text_context` / `structured_context` 字段。
- **MODIFIED** `SampleState` 新增 `selected_count` / `last_status` / `difficulty_score` 字段，保留 `difficulty_ema` 作为别名（向后兼容）。**BREAKING**：`selected_count_recent_window` 改名为 `selected_count`（保留旧字段作为别名一段时间）。
- **MODIFIED** `SampleAsset` 的 `type` 字段改为 `Literal["image", "pdf", "text", "json"]`。
- **REMOVED** `GroundTruth` 独立 dataclass，其内容合并进 `Sample.ground_truth` dict。**BREAKING**：`load_ground_truths` 函数移除，由 `DatasetLoader.load` 统一产出 `SampleSet`。
- **REMOVED** `select_optimization_batch` 与 `select_dynamic_validation_batch` 自由函数，由 `Sampler.sample()` 取代。**BREAKING**：调用方改用 `Sampler` 接口。
- **MODIFIED** `data/samples.jsonl` 与 `data/ground_truth.jsonl` 合并为单一 `data/samples.jsonl`，每行包含 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags`。**BREAKING**：旧格式不再支持（提供一次性迁移脚本）。

### 设计约束

1. 该模块不调用模型、不执行 prompt、不评估正确性、不生成 patch、不选择 few-shot 示例。
2. prompt 优化和 few-shot 优化都依赖 `SampleSet`，不允许各流程自己维护独立 sample 状态。
3. 所有 sample batch 都保存 `sample_ids`（不复制 sample 内容），可追溯回 `SampleSet`。
4. batch 必须保存 `composition`（label / difficulty / tags 分布）与 `warnings`。
5. 第一阶段不实现复杂 dynamic validation，只实现 7 个核心 sampler。

## Impact

- Affected specs: `refactor-split-prompt-fewshot-phases`（两个 phase runner 依赖此底座）、数据格式 schema、抽样接口。
- Affected code:
  - [mmap_optimizer/dataset/sample.py](file:///workspace/mmap_optimizer/dataset/sample.py) — 重构 `Sample` / `SampleAsset` / `SampleState`，移除 `GroundTruth`。
  - [mmap_optimizer/dataset/loader.py](file:///workspace/mmap_optimizer/dataset/loader.py) — 重写为 `DatasetLoader` 协议 + 内置 loader。
  - 新增 `mmap_optimizer/dataset/dataset.py` — `SampleSet` / `DatasetSource`。
  - [mmap_optimizer/sampling/](file:///workspace/mmap_optimizer/sampling) — 重写为 `Sampler` 协议 + 内置 sampler 集合，移除 `optimization_sampler.py` / `dynamic_validation_sampler.py` 中的自由函数。
  - [mmap_optimizer/orchestration/round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) — 调用方从 `select_optimization_batch` 改为 `Sampler.sample()`。
  - [mmap_optimizer/cli/main.py](file:///workspace/mmap_optimizer/cli/main.py) — `_build_state` 从 `load_samples` + `load_ground_truths` 改为 `DatasetLoader.load`。
  - [data/samples.jsonl](file:///workspace/data/samples.jsonl) / [data/ground_truth.jsonl](file:///workspace/data/ground_truth.jsonl) — 数据格式迁移。
  - 现有测试 [tests/test_dynamic_validation_sampler.py](file:///workspace/tests/test_dynamic_validation_sampler.py) / [tests/test_risk_signals_sampling.py](file:///workspace/tests/test_risk_signals_sampling.py) 等需适配。

## ADDED Requirements

### Requirement: SampleSet 聚合

系统 SHALL 提供 `SampleSet` dataclass，包含 `samples: list[Sample]`、`states: dict[str, SampleState]`、`metadata: dict[str, Any]`，并提供 `active_samples()` / `get(sample_id)` / `update_state(sample_id, **kwargs)` / `composition(sample_ids)` 方法。

#### Scenario: 获取活跃样本

- **WHEN** 调用 `sample_set.active_samples()`
- **THEN** 返回所有 `active=True` 的 `Sample` 列表

#### Scenario: 更新样本状态

- **WHEN** 调用 `sample_set.update_state("sample_001", last_status="correct")`
- **THEN** `sample_set.states["sample_001"].last_status == "correct"`，若 state 不存在则自动创建

#### Scenario: 计算批次组合

- **WHEN** 调用 `sample_set.composition(["sample_001", "sample_002"])`
- **THEN** 返回 dict 包含 label / difficulty / tags 分布统计

### Requirement: DatasetLoader 协议

系统 SHALL 提供 `DatasetLoader` Protocol 与 `DatasetSource` dataclass，`DatasetLoader.load(source) -> SampleSet`。

#### Scenario: 加载 JSONL 数据集

- **WHEN** `DatasetSource(path="data/samples.jsonl", format="jsonl")` 传入 `JsonlDatasetLoader`
- **THEN** 返回 `SampleSet`，每个 `Sample` 包含 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags`

#### Scenario: 不支持的格式

- **WHEN** `DatasetSource(format="csv")` 传入 `JsonlDatasetLoader`
- **THEN** 抛出 `ValueError` 说明格式不支持

### Requirement: Sampler 协议

系统 SHALL 提供 `Sampler` Protocol，`Sampler.sample(sample_set, request, context) -> SampleBatch`，其中 `SampleRequest` 描述抽样目的与约束，`SamplingContext` 描述运行上下文，`SampleBatch` 保存 `sample_ids` / `composition` / `warnings`。

#### Scenario: 抽样结果可追溯

- **WHEN** 任意 `Sampler.sample()` 返回 `SampleBatch`
- **THEN** `batch.sample_ids` 中的每个 id 都存在于 `sample_set` 中，`batch.composition` 与 `batch.warnings` 非空

#### Scenario: 按目的过滤

- **WHEN** `SampleRequest(purpose="prompt_optimization", exclude_tags=["debug"])`
- **THEN** 返回的 batch 不包含 `tags` 含 `debug` 的样本

### Requirement: 内置 Sampler 集合

系统 SHALL 提供以下内置 sampler：`FullSampler` / `RandomSampler` / `HardCaseSampler` / `RegressionGuardSampler` / `StratifiedSampler` / `CompositeSampler`。

#### Scenario: FullSampler 返回全部活跃样本

- **WHEN** `FullSampler.sample(sample_set, request(batch_size=10), context)`
- **THEN** 返回所有 active 样本（可能超过 batch_size）

#### Scenario: HardCaseSampler 优先困难样本

- **WHEN** `HardCaseSampler.sample(...)` 在含错误样本的 `SampleSet` 上调用
- **THEN** 返回的 batch 中 `consecutive_wrong_count > 0` 或 `difficulty_score` 高的样本优先

#### Scenario: RegressionGuardSampler 优先脆弱样本

- **WHEN** `RegressionGuardSampler.sample(...)` 调用
- **THEN** 返回的 batch 中 `consecutive_correct_count` 高且 `fragility_score` 高的样本优先

#### Scenario: StratifiedSampler 覆盖标签

- **WHEN** `StratifiedSampler.sample(...)` 在含多 label 的 `SampleSet` 上调用
- **THEN** 返回的 batch 中每个 label 至少有 1 个样本（若总数允许）

#### Scenario: CompositeSampler 组合策略

- **WHEN** `CompositeSampler(components=[(HardCaseSampler, 0.6), (RegressionGuardSampler, 0.3), (RandomSampler, 0.1)])` 调用 `batch_size=100`
- **THEN** 返回的 batch 约 60 个来自 hard case、30 个来自 regression guard、10 个来自 random

### Requirement: 抽样状态更新

系统 SHALL 提供 `SampleSet.update_state` 的标准更新规则：评估后根据 `eval_result.status` 更新 `consecutive_correct_count` / `consecutive_wrong_count` / `last_status` / `selected_count` / `last_selected_round`，并在状态翻转时设置 `historical_fixed` / `toxic_trigger` / `fragility_score`。

#### Scenario: wrong 转 correct

- **WHEN** 样本上一轮 `last_status="wrong"`，本轮评估 `status="correct"`
- **THEN** `state.historical_fixed = True`，`consecutive_correct_count += 1`，`consecutive_wrong_count = 0`

#### Scenario: correct 转 wrong

- **WHEN** 样本上一轮 `last_status="correct"`，本轮评估 `status="wrong"`
- **THEN** `state.toxic_trigger = True`，`state.fragility_score += 1.0`，`consecutive_wrong_count += 1`，`consecutive_correct_count = 0`

### Requirement: 配置驱动抽样

系统 SHALL 通过 `prompt_optimization.sampler` 与 `fewshot_optimization.sampler` 配置段声明各阶段使用的 sampler 类型、batch_size 与组件比例。

#### Scenario: Prompt 阶段默认 composite

- **WHEN** 配置 `prompt_optimization.sampler.type=composite, components=[{type: hard_case, ratio: 0.6}, ...]`
- **THEN** PromptOptimizationRunner 使用 `CompositeSampler` 构造对应组件

#### Scenario: Few-shot 阶段默认 stratified

- **WHEN** 配置 `fewshot_optimization.sampler.type=stratified, cover={labels: true, difficulty: true, tags: true}`
- **THEN** FewShotOptimizationRunner 使用 `StratifiedSampler` 并按 cover 配置分层

## MODIFIED Requirements

### Requirement: Sample 数据模型

`Sample` dataclass SHALL 包含 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags` / `active` 字段，`ground_truth` 与 `assets` 内嵌在 sample 内，不再通过外键引用。

#### Scenario: 序列化与反序列化

- **WHEN** `Sample` 被 `asdict()` 后再 `Sample(**dict)` 重建
- **THEN** 重建后的 sample 与原 sample 字段完全一致，包括 `assets` 列表中的 `SampleAsset` 对象

### Requirement: SampleState 数据模型

`SampleState` SHALL 包含 `sample_id` / `selected_count` / `last_selected_round` / `consecutive_correct_count` / `consecutive_wrong_count` / `difficulty_score` / `fragility_score` / `last_status` / `historical_fixed` / `toxic_trigger` 字段，保留 `difficulty_ema` 作为 `difficulty_score` 的别名以兼容旧代码。

#### Scenario: 旧字段别名

- **WHEN** 旧代码访问 `state.difficulty_ema`
- **THEN** 返回 `state.difficulty_score` 的值，设置 `state.difficulty_ema = 0.5` 等价于设置 `state.difficulty_score = 0.5`

## REMOVED Requirements

### Requirement: GroundTruth 独立对象

**Reason**: `GroundTruth` 作为独立对象导致 `SampleSet` 需要维护 `dict[str, GroundTruth]` 与 `dict[str, SampleAsset]` 两个旁路映射，与统一数据底座设计冲突。
**Migration**: `GroundTruth.value` 与 `GroundTruth.primary_answer` 合并进 `Sample.ground_truth` dict；`load_ground_truths` 调用方改用 `DatasetLoader.load` 产出的 `SampleSet`。

### Requirement: select_optimization_batch / select_dynamic_validation_batch 自由函数

**Reason**: 两个函数各自有不同签名与返回类型，无法被 prompt / few-shot 阶段统一调用。
**Migration**: 调用方改用 `Sampler.sample(sample_set, request, context)`；`DynamicValidationBatch` 的 `composition` / `warnings` 字段由 `SampleBatch` 统一承载。
