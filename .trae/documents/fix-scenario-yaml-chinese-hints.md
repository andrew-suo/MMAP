# 修复 scenario.yaml 中文 section_id_hints 映射

## 问题分析

### 根因
`_resolve_from_hints()` 使用**子串匹配**：`keyword.lower() in title.lower()`。

- 英文 key `cable_check` **不是**中文标题 "3.2 第二步：检查线缆是否严重凌乱" 的子串 → 匹配失败 → 退化为 `section_001`
- 中文 key `严重凌乱` **是**该标题的子串 → 匹配成功 → 产生 `cable_check`

### 当前状态
- `scenarios/default/scenario.yaml` 第 7 行：`# section_id_hints: {}`（注释状态，未生效）
- 代码管道已打通：`scenario.yaml → ScenarioConfig → CLI → initialize_prompt_from_file() → normalize_section_id()`
- 测试文件 `test_prompt_initializer_markdown_sections.py` 中的 `DOMAIN_HINTS` 已验证中文 key 匹配正确

### 最长匹配优先
`_resolve_from_hints` 按 key 长度降序选择最佳匹配，因此：
- `严重凌乱`（4 字）优先于 `线缆`（2 字）→ 都映射到 `cable_check`
- `场景适用性`（5 字）优先于 `场景适用`（4 字）→ 都映射到 `scene_check`

## 修改方案

### 文件：`/workspace/scenarios/default/scenario.yaml`

将第 7 行注释 `# section_id_hints: {}` 替换为实际的中文关键词映射：

```yaml
section_id_hints:
  场景适用性: scene_check
  检查场景: scene_check
  场景适用: scene_check
  严重凌乱: cable_check
  线缆: cable_check
  布线: cable_check
  明显杂物: debris_check
  杂物: debris_check
  工具: debris_check
  包装: debris_check
  最终结果: final_decision
  禁止行为: prohibited_behavior
  边界情况: edge_cases
  判定: quality_criteria
```

**设计决策**：
1. 同时包含长短关键词（如 `严重凌乱` + `线缆`），确保不同标题写法都能匹配
2. `禁止行为` 和 `边界情况` 虽然在 `_GENERIC_ZH_KEYWORDS` 中已有，但在 domain hints 中显式声明更清晰，且优先级更高
3. `判定` 映射到 `quality_criteria`：generic hints 中只有 `判定标准`（无法匹配 "结果判定总逻辑"），`判定` 可覆盖此场景

## 验证步骤

1. 运行现有测试确认无回归：
   ```bash
   python -m pytest tests/test_prompt_initializer_markdown_sections.py -v
   ```
2. 手动验证 `scenario.yaml` 加载后 `section_id_hints` 正确：
   ```bash
   python -c "from mmap_optimizer.core.scenario import load_scenario; s = load_scenario('scenarios/default'); print(s.section_id_hints)"
   ```
3. 运行全量测试：
   ```bash
   python -m pytest tests/ -v
   ```
