# -*- coding: utf-8 -*-
"""一次性运维脚本：清理 Role.page_perms 中已退役模块的旧权限组（2026-10-24）。

背景：device/fault/duty/runlog 四模块已整体下线（代码、路由、数据表均已移除），
equipment_lifecycle 早期阶段遗留的 device/relation 假分组、data_analysis 中
随设备管理/故障处置退役的分支同样失效。本脚本按"精确退役权限组"白名单清理：

- 顶层组：device / fault / duty / runlog（整组删除）；
- equipment_lifecycle 组内子键：device / relation（旧阶段占位，均为空列表）；
- data_analysis 组内子键：device / fault（数据分析设备/故障分支已退役）。

不触碰：upgrade.*、interference.* 等其它任何键；equipment_lifecycle 现行
子键（system/operation_record/ledger/ledger_template/config）原样保留。

幂等：已清理过的角色再次执行不产生任何变更（save 不触发、perms_version 不变）。
审计：逐角色打印变更前后差异；执行前先手工备份（见
quality/reports/el_migration_baseline_20261024/roles_page_perms_before.tsv）。

用法（在应用容器内，连接目标库）：
    python manage.py shell -c "exec(open('/data/spug/spug_api/scripts/'
        'cleanup_retired_role_perms_20261024.py').read())"

版本缓存：走 Role.save() 既有路径——page_perms 变化时自动自增 perms_version，
相关用户的 Redis 权限缓存（perms_{id}）随之失效，无需手工清缓存。
"""
import json

from apps.account.models import Role

# 整组退役：模块已删除，page_perms 顶层键直接移除
RETIRED_TOP_LEVEL_GROUPS = ('device', 'fault', 'duty', 'runlog')

# 组内子键退役：模块仍在，但该子权限组对应的业务已退役
RETIRED_SUBGROUPS = {
    'equipment_lifecycle': ('device', 'relation'),
    'data_analysis': ('device', 'fault'),
}


def clean_page_perms(perms):
    """按白名单清理 page_perms 字典，返回 (new_perms, removed)。"""
    removed = []
    if not isinstance(perms, dict):
        return perms, removed
    for group in RETIRED_TOP_LEVEL_GROUPS:
        if group in perms:
            perms.pop(group)
            removed.append(group)
    for group, subkeys in RETIRED_SUBGROUPS.items():
        if isinstance(perms.get(group), dict):
            for sub in subkeys:
                if sub in perms[group]:
                    perms[group].pop(sub)
                    removed.append('%s.%s' % (group, sub))
    return perms, removed


def main():
    for role in Role.objects.all().order_by('id'):
        if not role.page_perms:
            continue
        try:
            perms = json.loads(role.page_perms)
        except (ValueError, TypeError):
            print('[SKIP] role=%s page_perms 非 JSON，人工检查' % role.id)
            continue
        new_perms, removed = clean_page_perms(perms)
        if not removed:
            print('[OK] role=%s(%s) 无退役权限组，跳过' % (role.id, role.name))
            continue
        before_version = role.perms_version
        role.page_perms = json.dumps(new_perms, ensure_ascii=False)
        # Role.save 检测到 page_perms 变化自动自增 perms_version（项目既有路径）
        role.save(update_fields=['page_perms'])
        print('[CLEAN] role=%s(%s) 移除=%s perms_version: %s -> %s' % (
            role.id, role.name, ','.join(removed),
            before_version, role.perms_version))


main()
