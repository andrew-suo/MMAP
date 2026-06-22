# Tasks

- [ ] Task 1: 重构 Sample / SampleAsset / SampleState 数据模型
  - [ ] SubTask 1.1: 在 `dataset/sample.py` 重构 `Sample` dataclass 为 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags` / `active`，移除 `ground_truth_id` / `asset_ids` / `text_context` / `structured_context`
  - [ ] SubTask 1.2: `SampleAsset.type` 改为 `Literal["image", "pdf", "text", "json"]`
  - [ ] SubTask 1.3: `SampleState` 新增 `selected_count` / `last_status` / `difficulty_score` 字段，保留 `difficulty_ema` 与 `selected_count_recent_window` 作为属性别名（getter/setter 转发到新字段）
  - [ ] SubTask 1.4: 移除 `GroundTruth` dataclass（其内容合并进 `Sample.ground_truth`）
  - [ ] SubTask 1.5: 为新数据模型编写单元测试，覆盖序列化/反序列化与字段别名

- [ ] Task 2: 实现 SampleSet 聚合
  - [ ] SubTask 2.1: 新建 `dataset/dataset.py`，定义 `SampleSet` dataclass（`samples` / `states` / `metadata`）
  - [ ] SubTask 2.2: 实现 `active_samples()` / `get(sample_id)` / `update_state(sample_id, **kwargs)` / `composition(sample_ids)` 方法
  - [ ] SubTask 2.3: `composition()` 返回 label / difficulty / tags 分布统计
  - [ ] SubTask 2.4: 为 `SampleSet` 编写单元测试

- [ ] Task 3: 实现 DatasetLoader 协议与内置 loader
  - [ ] SubTask 3.1: 在 `dataset/dataset.py` 定义 `DatasetSource` dataclass（`path` / `format` / `image_root` / `schema` / `metadata`）
  - [ ] SubTask 3.2: 在 `dataset/loader.py` 定义 `DatasetLoader` Protocol（`load(source) -> SampleSet`）
  - [ ] SubTask 3.3: 实现 `JsonlDatasetLoader`，读取标准 JSONL 格式（每行含 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags`）
  - [ ] SubTask 3.4: 实现 `JsonDatasetLoader`，读取单个 JSON 文件（数组或 `{samples: [...]}` 结构）
  - [ ] SubTask 3.5: 实现 `FolderDatasetLoader`，扫描文件夹下每个 sample 一个子目录或一个 JSON 文件
  - [ ] SubTask 3.6: 不支持的 `format` 抛出 `ValueError`
  - [ ] SubTask 3.7: 为三个 loader 编写单元测试

- [ ] Task 4: 实现 Sampler 协议与 SampleBatch
  - [ ] SubTask 4.1: 新建 `sampling/base.py`，定义 `Sampler` Protocol（`name` / `sample(sample_set, request, context) -> SampleBatch`）
  - [ ] SubTask 4.2: 定义 `SampleRequest` dataclass（`batch_size` / `purpose` / `include_tags` / `exclude_tags` / `include_sample_ids` / `exclude_sample_ids` / `require_active`）
  - [ ] SubTask 4.3: 定义 `SamplingContext` dataclass（`phase` / `round_index` / `seed` / `eval_history` / `previous_batches`）
  - [ ] SubTask 4.4: 新建 `sampling/batch.py`，定义 `SampleBatch` dataclass（`id` / `purpose` / `sample_ids` / `sampler_name` / `round_index` / `composition` / `warnings` / `metadata`）与 composition 工具函数
  - [ ] SubTask 4.5: 为协议与数据结构编写单元测试

- [ ] Task 5: 实现内置 Sampler（第一阶段 6 个）
  - [ ] SubTask 5.1: `sampling/full.py` — `FullSampler`，返回所有 active 样本（或 request 指定的子集）
  - [ ] SubTask 5.2: `sampling/random.py` — `RandomSampler`，按 `context.seed` 随机抽样
  - [ ] SubTask 5.3: `sampling/hard_case.py` — `HardCaseSampler`，按 `consecutive_wrong_count` / `difficulty_score` / `historical_fixed` / `fragility_score` 排序
  - [ ] SubTask 5.4: `sampling/regression_guard.py` — `RegressionGuardSampler`，按 `consecutive_correct_count` 高 + `fragility_score` 高 + `toxic_trigger` 排序
  - [ ] SubTask 5.5: `sampling/stratified.py` — `StratifiedSampler`，按 label / difficulty / tags 分层覆盖
  - [ ] SubTask 5.6: `sampling/composite.py` — `CompositeSampler`，按 ratio 组合多个子 sampler
  - [ ] SubTask 5.7: 每个 sampler 编写单元测试，覆盖核心场景（FullSampler 全量、HardCaseSampler 优先困难、StratifiedSampler 覆盖标签、CompositeSampler 比例）

- [ ] Task 6: 实现抽样状态更新规则
  - [ ] SubTask 6.1: 在 `dataset/dataset.py` 实现 `SampleSet.apply_eval_result(sample_id, status, round_index)` 方法
  - [ ] SubTask 6.2: 实现 wrong→correct 设置 `historical_fixed`，correct→wrong 设置 `toxic_trigger` 与 `fragility_score += 1.0`
  - [ ] SubTask 6.3: 更新 `consecutive_correct_count` / `consecutive_wrong_count` / `last_status` / `selected_count` / `last_selected_round`
  - [ ] SubTask 6.4: 为状态更新规则编写单元测试，覆盖 correct→correct、wrong→correct、correct→wrong、wrong→wrong 四种翻转

- [ ] Task 7: 配置驱动 sampler 选择
  - [ ] SubTask 7.1: 在 `core/config.py` 的 `PromptOptimizationConfig` / `FewShotOptimizationConfig` 新增 `sampler` 子字段（`type` / `batch_size` / `components` / `cover`）
  - [ ] SubTask 7.2: 新增 `sampling/factory.py`，实现 `build_sampler(config) -> Sampler`，根据 `type` 构造对应 sampler（含 `composite` 的组件递归构造）
  - [ ] SubTask 7.3: 为 factory 编写单元测试

- [ ] Task 8: 数据格式迁移
  - [ ] SubTask 8.1: 编写一次性迁移脚本 `scripts/migrate_data_format.py`，将旧 `samples.jsonl` + `ground_truth.jsonl` 合并为新格式 `samples.jsonl`（每行含 `id` / `input` / `ground_truth` / `assets` / `metadata` / `tags`）
  - [ ] SubTask 8.2: 运行迁移脚本转换 [data/samples.jsonl](file:///workspace/data/samples.jsonl) 与 [data/ground_truth.jsonl](file:///workspace/data/ground_truth.jsonl)
  - [ ] SubTask 8.3: 更新 [scenarios/default/data/example.json](file:///workspace/scenarios/default/data/example.json) 适配新格式
  - [ ] SubTask 8.4: 在 `dataset/loader.py` 提供向后兼容读取：若 JSONL 行缺少 `input` 字段但含 `text_context`，自动转换为 `input={"text": text_context}`

- [ ] Task 9: 适配调用方
  - [ ] SubTask 9.1: [cli/main.py](file:///workspace/mmap_optimizer/cli/main.py) 的 `_build_state` 改用 `DatasetLoader.load` 产出 `SampleSet`，`OptimizerState` 持有 `SampleSet` 而非 `samples` + `ground_truths` + `assets` + `sample_states` 四个独立字段
  - [ ] SubTask 9.2: [orchestration/round_runner.py](file:///workspace/mmap_optimizer/orchestration/round_runner.py) 中 `select_optimization_batch` / `select_dynamic_validation_batch` 调用改为 `Sampler.sample()`
  - [ ] SubTask 9.3: 移除 `sampling/optimization_sampler.py` 与 `sampling/dynamic_validation_sampler.py` 中的自由函数（保留 `DynamicValidationBatch` 字段映射到 `SampleBatch` 的兼容层一个版本）
  - [ ] SubTask 9.4: 更新 `OptimizerState` dataclass：`samples` / `assets` / `ground_truths` / `sample_states` 四字段合并为 `sample_set: SampleSet`，提供属性别名以减少破坏

- [ ] Task 10: 适配与补充测试
  - [ ] SubTask 10.1: 更新 [tests/test_dynamic_validation_sampler.py](file:///workspace/tests/test_dynamic_validation_sampler.py) 适配 `Sampler` 接口
  - [ ] SubTask 10.2: 更新 [tests/test_risk_signals_sampling.py](file:///workspace/tests/test_risk_signals_sampling.py) 适配新 `SampleState`
  - [ ] SubTask 10.3: 新增 `tests/test_sample_set.py` 覆盖 Task 2
  - [ ] SubTask 10.4: 新增 `tests/test_dataset_loader.py` 覆盖 Task 3
  - [ ] SubTask 10.5: 新增 `tests/test_samplers.py` 覆盖 Task 5 的 6 个 sampler
  - [ ] SubTask 10.6: 新增 `tests/test_sample_state_update.py` 覆盖 Task 6
  - [ ] SubTask 10.7: 运行全量测试套件确认无回归

# Task Dependencies

- Task 2 依赖 Task 1（SampleSet 依赖新 Sample / SampleState）
- Task 3 依赖 Task 1、Task 2（loader 产出 SampleSet）
- Task 5 依赖 Task 1、Task 2、Task 4（sampler 依赖 SampleSet 与协议）
- Task 6 依赖 Task 1、Task 2
- Task 7 依赖 Task 5（factory 构造 sampler）
- Task 8 依赖 Task 1（新格式定义后才能迁移）
- Task 9 依赖 Task 1-7 全部完成
- Task 10 依赖 Task 1-9 全部完成
- Task 4 与 Task 6 可并行（无相互依赖）
- Task 5 各 sampler 子任务可并行
