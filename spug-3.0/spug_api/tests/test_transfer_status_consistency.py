#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
传输状态一致性测试

对应报告：资料库代码质量报告.md（P0-1）、资料库代码质量修复建议.md（第1项+第2项）
测试目标：
  1. TransferStatus 枚举与 TRANSFER_STATUS_CHOICES 一致
  2. 所有 ALLOWED_STATUS_TRANSITIONS 引用的状态都存在
  3. 合法/非法状态转换验证
  4. 终态不可转换
  5. DOWNLOADING / MERGING 关键路径转换
  6. 前端 BACKEND_STATUS_MAP / FRONTEND_STATUS_MAP 覆盖完整性

运行方式：
  docker exec tdyw python /data/spug/spug_api/tests/test_transfer_status_consistency.py
"""
import os
import sys
import re

# ── Django 初始化 ──
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django
django.setup()

from apps.document.constants import (
    TransferStatus,
    ALLOWED_STATUS_TRANSITIONS,
    is_valid_status_transition,
)
from apps.document.models import DocumentTransfer

# ── 前端状态映射（从 upload-core-constants.js 中提取） ──
BACKEND_STATUS_MAP = {
    'UPLOADING': 'uploading',
    'DOWNLOADING': 'downloading',
    'PAUSED': 'paused',
    'MERGING': 'merging',
    'COMPLETED': 'completed',
    'FAILED': 'error',
    'CANCELED': 'cancelled',
    'PENDING': 'waiting',
}

FRONTEND_STATUS_MAP = {
    'waiting': 'PENDING',
    'calculating': 'UPLOADING',
    'uploading': 'UPLOADING',
    'downloading': 'DOWNLOADING',
    'merging': 'MERGING',
    'paused': 'PAUSED',
    'completed': 'COMPLETED',
    'error': 'FAILED',
    'cancelled': 'CANCELED',
}

# 前端 UPLOAD_STATUS（含仅前端状态）
FRONTEND_ONLY_STATUSES = {'calculating', 'waiting'}

# ── 辅助 ──
passed = 0
failed = 0


def assert_test(condition, msg):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {msg}")
    else:
        failed += 1
        print(f"  ✗ {msg}")


# ================================================================
# 一、TransferStatus 枚举 vs TRANSFER_STATUS_CHOICES 一致性
# ================================================================
print("\n" + "=" * 60)
print("一、TransferStatus 枚举 vs TRANSFER_STATUS_CHOICES 一致性")
print("=" * 60)

# 1.1 枚举值集合
enum_values = {s.value for s in TransferStatus}
choices_values = {val for val, _label in DocumentTransfer.TRANSFER_STATUS_CHOICES}

print(f"\n  TransferStatus 枚举值: {sorted(enum_values)}")
print(f"  TRANSFER_STATUS_CHOICES: {sorted(choices_values)}")

# 1.2 枚举值应全部存在于 choices
for status in TransferStatus:
    assert_test(
        status.value in choices_values,
        f"枚举 {status.name}({status.value}) 存在于 TRANSFER_STATUS_CHOICES"
    )

# 1.3 choices 应全部能映射到枚举
enum_map = {s.value: s for s in TransferStatus}
for val, label in DocumentTransfer.TRANSFER_STATUS_CHOICES:
    assert_test(
        val in enum_map,
        f"Choices {val}('{label}') 存在于 TransferStatus 枚举"
    )

# 1.4 数量一致
assert_test(
    len(enum_values) == len(choices_values),
    f"枚举数量({len(enum_values)}) == Choices数量({len(choices_values)})"
)


# ================================================================
# 二、ALLOWED_STATUS_TRANSITIONS 引用的状态都存在
# ================================================================
print("\n" + "=" * 60)
print("二、ALLOWED_STATUS_TRANSITIONS 引用状态验证")
print("=" * 60)

# 2.1 所有 key 都是合法枚举值
for source_status in ALLOWED_STATUS_TRANSITIONS:
    assert_test(
        isinstance(source_status, TransferStatus),
        f"转换源 {source_status} 是 TransferStatus 实例"
    )

# 2.2 所有 value 列表中的目标状态都是合法枚举值
for source_status, targets in ALLOWED_STATUS_TRANSITIONS.items():
    for target in targets:
        assert_test(
            isinstance(target, TransferStatus),
            f"转换目标 {target}（来自 {source_status.name}）是 TransferStatus 实例"
        )

# 2.3 每个枚举值都出现在转换表中（要么是源，要么是某条规则的目标）
sources = set(ALLOWED_STATUS_TRANSITIONS.keys())
all_targets = set()
for targets in ALLOWED_STATUS_TRANSITIONS.values():
    all_targets.update(targets)

for status in TransferStatus:
    in_sources = status in sources
    in_targets = status in all_targets
    assert_test(
        in_sources or in_targets,
        f"{status.name} 出现在转换表中（源={in_sources}, 目标={in_targets}）"
    )


# ================================================================
# 三、合法/非法状态转换验证
# ================================================================
print("\n" + "=" * 60)
print("三、合法/非法状态转换验证")
print("=" * 60)

# 3.1 所有 ALLOWED 转换都应该通过 is_valid_status_transition
print("\n  --- 合法转换应通过 ---")
for source, targets in ALLOWED_STATUS_TRANSITIONS.items():
    for target in targets:
        result = is_valid_status_transition(source, target)
        assert_test(
            result is True,
            f"is_valid_status_transition({source.name}, {target.name}) == True"
        )

# 3.2 未在 ALLOWED 中定义的转换应被拒绝
print("\n  --- 非法转换应被拒绝 ---")
for source in TransferStatus:
    allowed = set(ALLOWED_STATUS_TRANSITIONS.get(source, []))
    for target in TransferStatus:
        if target not in allowed:
            result = is_valid_status_transition(source, target)
            assert_test(
                result is False,
                f"is_valid_status_transition({source.name}, {target.name}) == False"
            )


# ================================================================
# 四、终态验证
# ================================================================
print("\n" + "=" * 60)
print("四、终态验证")
print("=" * 60)

# COMPLETED 和 CANCELED 是终态，不应有出边
terminal_states = [TransferStatus.COMPLETED, TransferStatus.CANCELED]

for ts in terminal_states:
    out_transitions = ALLOWED_STATUS_TRANSITIONS.get(ts, [])
    assert_test(
        len(out_transitions) == 0,
        f"{ts.name} 无出边（终态），当前出边数={len(out_transitions)}"
    )

# 终态不应接受任何新状态
for ts in terminal_states:
    for other in TransferStatus:
        if other != ts:
            assert_test(
                not is_valid_status_transition(ts, other),
                f"终态 {ts.name} 不可转到 {other.name}"
            )


# ================================================================
# 五、DOWNLOADING / MERGING 关键路径转换
# ================================================================
print("\n" + "=" * 60)
print("五、DOWNLOADING / MERGING 关键路径转换")
print("=" * 60)

# 5.1 DOWNLOADING 的合法转换
downloading_allowed = set(ALLOWED_STATUS_TRANSITIONS.get(TransferStatus.DOWNLOADING, []))
print(f"\n  DOWNLOADING 允许转换: {[s.name for s in downloading_allowed]}")

assert_test(
    TransferStatus.COMPLETED in downloading_allowed,
    "DOWNLOADING -> COMPLETED 合法"
)
assert_test(
    TransferStatus.FAILED in downloading_allowed,
    "DOWNLOADING -> FAILED 合法"
)
assert_test(
    TransferStatus.CANCELED in downloading_allowed,
    "DOWNLOADING -> CANCELED 合法"
)
assert_test(
    TransferStatus.PAUSED in downloading_allowed,
    "DOWNLOADING -> PAUSED 合法"
)

# 5.2 MERGING 的合法转换
merging_allowed = set(ALLOWED_STATUS_TRANSITIONS.get(TransferStatus.MERGING, []))
print(f"\n  MERGING 允许转换: {[s.name for s in merging_allowed]}")

assert_test(
    TransferStatus.COMPLETED in merging_allowed,
    "MERGING -> COMPLETED 合法"
)
assert_test(
    TransferStatus.FAILED in merging_allowed,
    "MERGING -> FAILED 合法"
)
assert_test(
    TransferStatus.CANCELED in merging_allowed,
    "MERGING -> CANCELED 合法"
)

# 5.3 哪些状态可以转到 MERGING
merging_sources = []
for source, targets in ALLOWED_STATUS_TRANSITIONS.items():
    if TransferStatus.MERGING in targets:
        merging_sources.append(source.name)
print(f"\n  可转到 MERGING 的状态: {merging_sources}")
assert_test(
    len(merging_sources) > 0,
    f"至少有一个状态可转到 MERGING（当前: {merging_sources}）"
)

# 5.4 哪些状态可以转到 DOWNLOADING
downloading_sources = []
for source, targets in ALLOWED_STATUS_TRANSITIONS.items():
    if TransferStatus.DOWNLOADING in targets:
        downloading_sources.append(source.name)
print(f"\n  可转到 DOWNLOADING 的状态: {downloading_sources}")
assert_test(
    len(downloading_sources) > 0,
    f"至少有一个状态可转到 DOWNLOADING（当前: {downloading_sources}）"
)


# ================================================================
# 六、关键业务链路端到端转换
# ================================================================
print("\n" + "=" * 60)
print("六、关键业务链路端到端转换")
print("=" * 60)

# 6.1 小文件上传：PENDING -> UPLOADING -> COMPLETED
print("\n  --- 小文件上传（无分片合并） ---")
assert_test(
    is_valid_status_transition(TransferStatus.PENDING, TransferStatus.UPLOADING),
    "PENDING -> UPLOADING"
)
assert_test(
    is_valid_status_transition(TransferStatus.PENDING, TransferStatus.COMPLETED),
    "PENDING -> COMPLETED（小文件直接完成）"
)
assert_test(
    is_valid_status_transition(TransferStatus.PENDING, TransferStatus.FAILED),
    "PENDING -> FAILED（入队后上传前失败）"
)

# 6.2 分片上传：PENDING -> UPLOADING -> MERGING -> COMPLETED
print("\n  --- 分片上传（含合并） ---")
assert_test(
    is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.MERGING),
    "UPLOADING -> MERGING"
)
assert_test(
    is_valid_status_transition(TransferStatus.MERGING, TransferStatus.COMPLETED),
    "MERGING -> COMPLETED"
)

# 6.3 上传暂停/恢复
print("\n  --- 暂停/恢复 ---")
assert_test(
    is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.PAUSED),
    "UPLOADING -> PAUSED"
)
assert_test(
    is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.UPLOADING),
    "PAUSED -> UPLOADING（恢复）"
)

# 6.4 下载链路：PENDING -> DOWNLOADING -> COMPLETED
print("\n  --- 下载链路 ---")
assert_test(
    is_valid_status_transition(TransferStatus.PENDING, TransferStatus.DOWNLOADING),
    "PENDING -> DOWNLOADING"
)
assert_test(
    is_valid_status_transition(TransferStatus.DOWNLOADING, TransferStatus.COMPLETED),
    "DOWNLOADING -> COMPLETED"
)

# 6.5 下载暂停/恢复
print("\n  --- 下载暂停/恢复 ---")
assert_test(
    is_valid_status_transition(TransferStatus.DOWNLOADING, TransferStatus.PAUSED),
    "DOWNLOADING -> PAUSED"
)
assert_test(
    is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.DOWNLOADING),
    "PAUSED -> DOWNLOADING（恢复下载）"
)

# 6.6 失败重试
print("\n  --- 失败重试 ---")
assert_test(
    is_valid_status_transition(TransferStatus.FAILED, TransferStatus.UPLOADING),
    "FAILED -> UPLOADING（上传重试）"
)
assert_test(
    is_valid_status_transition(TransferStatus.FAILED, TransferStatus.DOWNLOADING),
    "FAILED -> DOWNLOADING（下载重试）"
)

# 6.7 各非终态取消
print("\n  --- 非终态取消 ---")
cancelable_from = [
    TransferStatus.PENDING,
    TransferStatus.UPLOADING,
    TransferStatus.DOWNLOADING,
    TransferStatus.MERGING,
    TransferStatus.FAILED,
]
for src in cancelable_from:
    assert_test(
        is_valid_status_transition(src, TransferStatus.CANCELED),
        f"{src.name} -> CANCELED"
    )

# 6.8 合并失败
print("\n  --- 合并失败 ---")
assert_test(
    is_valid_status_transition(TransferStatus.MERGING, TransferStatus.FAILED),
    "MERGING -> FAILED"
)


# ================================================================
# 七、前端 BACKEND_STATUS_MAP 覆盖完整性
# ================================================================
print("\n" + "=" * 60)
print("七、前端 BACKEND_STATUS_MAP 覆盖完整性")
print("=" * 60)

# 7.1 每个后端 TransferStatus 值都应有前端映射
for status in TransferStatus:
    mapped = status.value in BACKEND_STATUS_MAP
    assert_test(
        mapped,
        f"后端 {status.name}({status.value}) 在 BACKEND_STATUS_MAP 中有映射"
    )

# 7.2 每个前端映射目标都应能反向映射
for backend_val, frontend_val in BACKEND_STATUS_MAP.items():
    assert_test(
        frontend_val in FRONTEND_STATUS_MAP,
        f"前端 '{frontend_val}' 在 FRONTEND_STATUS_MAP 中有反向映射"
    )

# 7.3 正向映射和反向映射一致
for backend_val, frontend_val in BACKEND_STATUS_MAP.items():
    if frontend_val in FRONTEND_STATUS_MAP:
        reverse = FRONTEND_STATUS_MAP[frontend_val]
        assert_test(
            reverse == backend_val,
            f"映射一致: {backend_val} -> {frontend_val} -> {reverse}"
        )

# 7.4 前端仅内部状态（calculating/waiting）应有反向映射到后端状态
for fe_status in FRONTEND_ONLY_STATUSES:
    assert_test(
        fe_status in FRONTEND_STATUS_MAP,
        f"前端仅状态 '{fe_status}' 在 FRONTEND_STATUS_MAP 中有后端映射"
    )

# 7.5 前端 UPLOAD_STATUS 缺少 PENDING（后端有，前端用 WAITING 代替）
assert_test(
    'PENDING' in BACKEND_STATUS_MAP and BACKEND_STATUS_MAP['PENDING'] == 'waiting',
    "后端 PENDING 映射到前端 waiting"
)


# ================================================================
# 八、枚举值拼写一致性（避免 CANCELED/CANCELLED 混用）
# ================================================================
print("\n" + "=" * 60)
print("八、枚举值拼写一致性")
print("=" * 60)

# 8.1 后端统一使用 CANCELED（美式拼写）
assert_test(
    TransferStatus.CANCELED.value == 'CANCELED',
    "后端使用 CANCELED（美式拼写），非 CANCELLED"
)

# 8.2 模型 choices 也使用 CANCELED
canceled_in_choices = any(v == 'CANCELED' for v, _ in DocumentTransfer.TRANSFER_STATUS_CHOICES)
assert_test(
    canceled_in_choices,
    "模型 TRANSFER_STATUS_CHOICES 使用 CANCELED"
)

# 8.3 前端映射 CANCELED -> cancelled
assert_test(
    BACKEND_STATUS_MAP.get('CANCELED') == 'cancelled',
    "前端映射 CANCELED -> cancelled（前端内部用英式拼写）"
)


# ================================================================
# 九、状态转换完备性检查
# ================================================================
print("\n" + "=" * 60)
print("九、状态转换完备性检查")
print("=" * 60)

# 9.1 每个非终态都应有至少一个出边
for status in TransferStatus:
    out_edges = ALLOWED_STATUS_TRANSITIONS.get(status, [])
    if status in terminal_states:
        assert_test(
            len(out_edges) == 0,
            f"终态 {status.name} 出边数=0"
        )
    else:
        assert_test(
            len(out_edges) > 0,
            f"非终态 {status.name} 至少有1个出边（当前={len(out_edges)}）"
        )

# 9.2 每个非初始态都应有至少一个入边
initial_states = {TransferStatus.PENDING}
non_initial = set(TransferStatus) - initial_states
for status in non_initial:
    in_count = sum(
        1 for src, targets in ALLOWED_STATUS_TRANSITIONS.items()
        if status in targets
    )
    assert_test(
        in_count > 0,
        f"非初始态 {status.name} 至少有1个入边（当前={in_count}）"
    )


# ================================================================
# 十、TransferStatus(value) 构造验证
# ================================================================
print("\n" + "=" * 60)
print("十、TransferStatus(value) 构造验证")
print("=" * 60)

# 10.1 每个 choices 值都能构造枚举
for val, label in DocumentTransfer.TRANSFER_STATUS_CHOICES:
    try:
        status = TransferStatus(val)
        assert_test(True, f"TransferStatus('{val}') 构造成功 -> {status.name}")
    except ValueError:
        assert_test(False, f"TransferStatus('{val}') 构造失败（ValueError）")

# 10.2 不存在的值应抛出 ValueError
try:
    TransferStatus('NONEXISTENT')
    assert_test(False, "TransferStatus('NONEXISTENT') 应抛出 ValueError")
except ValueError:
    assert_test(True, "TransferStatus('NONEXISTENT') 正确抛出 ValueError")


# ================================================================
# 结果汇总
# ================================================================
print("\n" + "=" * 60)
total = passed + failed
print(f"测试结果: {passed}/{total} 通过, {failed}/{total} 失败")
print("=" * 60)

if failed > 0:
    print("\n⚠ 存在失败项，请检查上方输出中的 ✗ 标记")
    sys.exit(1)
else:
    print("\n✓ 所有状态一致性测试通过")
    sys.exit(0)
