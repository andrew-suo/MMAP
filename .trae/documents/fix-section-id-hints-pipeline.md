# 修复计划：Domain-Specific Section ID 不匹配

## 问题摘要

分析模型生成的补丁引用 `cable_check`、`debris_check`、`scene_check` 等 domain-specific section ID，但 `initialize_prompt_from_file()` 实际生成的 section ID 是 `jian_cha_bu_zhou`、`role_definition` 等（由 markdown 标题自动推导）。

**根因**：`section_id_hints` 参数已存在于 `initialize_prompt_from_file()` 和 `normalize_section_id()` 中，但整个调用链从未传递该参数：
1. `ScenarioConfig` 没有 `section_id_hints` 字段
2. `scenario.yaml` 没有定义 `section_id_hints`
3. CLI 的 `_build_state()` / `check_prompt()` 调用 `initialize_prompt_from_file()` 时没有传递 `section_id_hints`

## 当前状态

- `initialize_prompt_from_file(path, prompt_type, contract, *, section_id_hints=None)` — 已支持 hints，但默认 None
- `ScenarioConfig` — 仅有 `id, root, optimizer_config, config_hash, data_dir, prompts_dir, schemas_dir, manifest`
- `load_scenario()` — 从 `scenario.yaml` 读取 manifest，但不解析 `section_id_hints`
- `_build_state()` — 调用 `initialize_prompt_from_file()` 时无 hints
- `check_prompt()` — 同上
- `scenarios/default/scenario.yaml` — 无 `section_id_hints` 字段
- 测试文件 `test_prompt_initializer_markdown_sections.py` 已验证 hints 机制本身可用

## 修改方案

### 1. `mmap_optimizer/core/scenario.py` — ScenarioConfig 增加 section_id_hints

- `ScenarioConfig` 新增字段 `section_id_hints: dict[str, str] = field(default_factory=dict)`
- `load_scenario()` 从 `manifest` 中读取 `section_id_hints`（若存在），传入 `ScenarioConfig`

```python
@dataclass
class ScenarioConfig:
    id: str
    root: Path
    optimizer_config: OptimizerConfig
    config_hash: str
    data_dir: Path
    prompts_dir: Path
    schemas_dir: Path
    manifest: dict[str, object] = field(default_factory=dict)
    section_id_hints: dict[str, str] = field(default_factory=dict)  # 新增
```

`load_scenario()` 中：
```python
section_id_hints = manifest.get("section_id_hints", {})
if not isinstance(section_id_hints, dict):
    section_id_hints = {}
return ScenarioConfig(
    ...,
    section_id_hints=section_id_hints,
)
```

### 2. `mmap_optimizer/cli/main.py` — 传递 section_id_hints

#### 2a. `_apply_scenario_args()` — 将 hints 存入 args

```python
def _apply_scenario_args(args: argparse.Namespace) -> None:
    scenario_path = getattr(args, "scenario", None)
    if not scenario_path:
        return
    scenario = load_scenario(scenario_path)
    # ... 现有路径替换逻辑 ...
    args.section_id_hints = scenario.section_id_hints  # 新增
    args.loaded_scenario_id = scenario.id
```

#### 2b. `_build_state()` — 传递 hints 到 initialize_prompt_from_file

```python
def _build_state(args: argparse.Namespace) -> tuple[OptimizerState, OutputSchemaContract, OutputSchemaContract]:
    hints = getattr(args, "section_id_hints", {}) or {}  # 新增
    extraction_prompt = initialize_prompt_from_file(
        args.extraction_prompt, PromptType.EXTRACTION, extraction_contract,
        section_id_hints=hints,  # 新增
    )
    analysis_prompt = initialize_prompt_from_file(
        args.analysis_prompt, PromptType.ANALYSIS, analysis_contract,
        section_id_hints=hints,  # 新增
    )
    ...
```

#### 2c. `check_prompt()` — 同样传递 hints

```python
def check_prompt(args: argparse.Namespace) -> None:
    _apply_scenario_args(args)
    hints = getattr(args, "section_id_hints", {}) or {}  # 新增
    prompts = {
        "extraction": initialize_prompt_from_file(
            args.extraction_prompt, PromptType.EXTRACTION, extraction_contract,
            section_id_hints=hints,  # 新增
        ),
        "analysis": initialize_prompt_from_file(
            args.analysis_prompt, PromptType.ANALYSIS, analysis_contract,
            section_id_hints=hints,  # 新增
        ),
    }
    ...
```

### 3. `scenarios/default/scenario.yaml` — 添加示例 section_id_hints

```yaml
name: Default Scenario
description: A default scenario for testing MMAP optimizer
optimizer_config: optimizer.yaml
data_dir: data
prompts_dir: prompts
schemas_dir: schemas
# section_id_hints: {}  # Optional: map heading keywords → section IDs
```

默认 scenario 不需要 hints（使用通用英文标题），仅添加注释说明。

### 4. 测试

在 `tests/test_prompt_initializer_markdown_sections.py` 中新增测试：
- 验证 `ScenarioConfig` 从 manifest 中正确读取 `section_id_hints`
- 验证 `_build_state()` 传递 hints 后 section ID 符合预期
- 验证无 scenario 时 hints 为空 dict，不影响现有行为

## 文件变更清单

| 文件 | 变更 |
|---|---|
| `mmap_optimizer/core/scenario.py` | `ScenarioConfig` 新增 `section_id_hints` 字段；`load_scenario()` 从 manifest 读取 |
| `mmap_optimizer/cli/main.py` | `_apply_scenario_args()` 存储 hints；`_build_state()` / `check_prompt()` 传递 hints |
| `scenarios/default/scenario.yaml` | 添加注释说明 `section_id_hints` 用法 |
| `tests/test_prompt_initializer_markdown_sections.py` | 新增集成测试 |

## 验证步骤

1. `python -m pytest tests/ -q` — 全部通过
2. `python -m mmap_optimizer.cli.main run-smoke --scenario scenarios/default --rounds 1 --run-dir /tmp/smoke-test` — smoke 通过
3. 创建一个带 `section_id_hints` 的 scenario.yaml，验证 section ID 符合 hints 映射
