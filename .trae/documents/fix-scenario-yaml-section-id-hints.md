# 修复计划：scenario.yaml 添加中文 section_id_hints

## 问题摘要

`_resolve_from_hints()` 使用子串匹配（`keyword.lower() in title.lower()`），因此：
- 中文 key `严重凌乱` 能匹配标题 "3.2 第二步：检查线缆是否严重凌乱" → `cable_check` ✅
- 英文 key `cable_check` 无法匹配中文标题 → `section_001` ❌

当前 `scenarios/default/scenario.yaml` 的 `section_id_hints` 仍为注释状态，未实际定义任何映射。

## 修改方案

### 1. `scenarios/default/scenario.yaml` — 添加中文 section_id_hints

将注释替换为实际的中文关键词映射，参考测试中已验证的 `DOMAIN_HINTS`：

```yaml
section_id_hints:
  场景适用: scene_check
  检查场景: scene_check
  线缆: cable_check
  布线: cable_check
  严重凌乱: cable_check
  杂物: debris_check
  工具: debris_check
  包装: debris_check
  最终结果: final_decision
  禁止行为: prohibited_behavior
  边界情况: edge_cases
  判定: quality_criteria
```

注意：`normalize_section_id` 按最长匹配优先（longest match wins），所以 `场景适用` 会优先于 `适用` 匹配到 `scene_check`。

### 2. 测试验证

无需新增测试文件。现有测试 `test_section_id_hints_flow_from_scenario_to_prompt_version` 已验证端到端链路。只需确认：

1. `python -m pytest tests/ -q` — 全部通过
2. 手动验证：用 `DOMAIN_HINTS` 中的中文 key 调用 `normalize_section_id("3.2 第二步：检查线缆是否严重凌乱", section_id_hints=hints)` 应返回 `cable_check`

## 文件变更清单

| 文件 | 变更 |
|---|---|
| `scenarios/default/scenario.yaml` | 将注释的 `section_id_hints` 替换为实际中文关键词映射 |

## 验证步骤

1. `python -m pytest tests/ -q` — 全部通过
2. `python -c "from mmap_optimizer.prompt.initializer import normalize_section_id; print(normalize_section_id('3.2 第二步：检查线缆是否严重凌乱', section_id_hints={'严重凌乱': 'cable_check'}))"` → 输出 `cable_check`
