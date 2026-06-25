"""Patch 分组模块。

提供按 target_section 分组的 Section-Aware 分组逻辑：
- ``group_by_section``：基础分组
- ``categorize_by_section``：区分 groupable / single_pass
- ``split_oversized_group``：超限分割
"""

from __future__ import annotations

from collections import defaultdict


def _get_target_section(patch: dict) -> str | None:
    """获取 patch 的 target_section 字段。

    返回 None 表示该 patch 没有有效的 target_section
    （字段缺失、为 None 或空字符串）。
    """
    section = patch.get("target_section")
    if section is None or section == "":
        return None
    return section


def split_oversized_group(group: list[dict], branch_factor: int) -> list[list[dict]]:
    """将超出 branch_factor 的组分割为多个子组。

    尽量均匀分割，每个子组不超过 branch_factor 个 patch。
    """
    n = len(group)
    if n <= branch_factor:
        return [group]
    # 计算需要的子组数量（向上取整）
    num_subgroups = (n + branch_factor - 1) // branch_factor
    # 每个子组的大小（向上取整以保证均匀且不超限）
    subgroup_size = (n + num_subgroups - 1) // num_subgroups
    subgroups: list[list[dict]] = []
    for i in range(0, n, subgroup_size):
        subgroups.append(group[i:i + subgroup_size])
    return subgroups


def group_by_section(patches: list[dict], branch_factor: int = 8) -> list[list[dict]]:
    """按 target_section 分组。

    - 同 section 的 patch 分到同组
    - 超出 branch_factor 时分割为多个子组
    - 无 target_section 的 patch 单独分组（每个一个组）

    Returns: list of groups, each group is a list of patches
    """
    section_groups: dict[str, list[dict]] = defaultdict(list)
    no_section_patches: list[dict] = []

    for patch in patches:
        section = _get_target_section(patch)
        if section is None:
            # 无 target_section 的 patch 单独收集
            no_section_patches.append(patch)
        else:
            section_groups[section].append(patch)

    result: list[list[dict]] = []
    for section, group in section_groups.items():
        if len(group) > branch_factor:
            # 超出 branch_factor，分割为多个子组
            result.extend(split_oversized_group(group, branch_factor))
        else:
            result.append(group)

    # 无 target_section 的 patch 单独分组（每个一个组）
    for patch in no_section_patches:
        result.append([patch])

    return result


def categorize_by_section(
    patches: list[dict], branch_factor: int = 8
) -> tuple[list[list[dict]], list[dict]]:
    """区分 groupable 和 single_pass。

    - single_pass: 同 section 内只有 1 个 patch 的，直接传递，不需要 LLM 合并
    - groupable: 同 section 内有 2+ 个 patch 的，需要分组后 LLM 合并

    Returns: (groupable_groups, single_pass_patches)
    """
    section_groups: dict[str, list[dict]] = defaultdict(list)
    no_section_patches: list[dict] = []

    for patch in patches:
        section = _get_target_section(patch)
        if section is None:
            # 无 target_section 的 patch 单独收集
            no_section_patches.append(patch)
        else:
            section_groups[section].append(patch)

    groupable_groups: list[list[dict]] = []
    single_pass_patches: list[dict] = []

    for section, group in section_groups.items():
        if len(group) == 1:
            # 同 section 内只有 1 个 patch，直接传递，不需要 LLM 合并
            single_pass_patches.append(group[0])
        else:
            # 同 section 内有 2+ 个 patch，需要分组后 LLM 合并
            if len(group) > branch_factor:
                groupable_groups.extend(split_oversized_group(group, branch_factor))
            else:
                groupable_groups.append(group)

    # 无 target_section 的 patch 也作为 single_pass 直接传递
    single_pass_patches.extend(no_section_patches)

    return groupable_groups, single_pass_patches
