# 稳定业务不变量清单

## 概述

以下不变量在重构后仍应成立。stable_contract 测试保护这些不变量。

## 1. 认证与权限不变量

| ID | 不变量 | 保护测试 | 状态 |
|---|---|---|---|
| INV-AUTH-01 | 未认证用户不能访问任何模块数据 | 所有模块 test_unauthenticated_denied | 通过 |
| INV-AUTH-02 | 无权限用户不能读取数据 | 所有模块 test_no_permission_denied | 通过 |
| INV-AUTH-03 | 有 view 权限用户可以列表 | 所有模块 test_view_can_list | 通过(device/fault/interference) |
| INV-AUTH-04 | 无 add 权限用户不能创建 | 所有模块 test_no_add_cannot_create | 通过(device/fault) |

## 2. 租户数据隔离不变量

| ID | 不变量 | 保护测试 | 状态 |
|---|---|---|---|
| INV-TENANT-01 | 租户 A 看不到租户 B 的数据列表 | 所有模块 test_cross_tenant_list_isolated | 通过 |
| INV-TENANT-02 | 租户 A 不能查看租户 B 的详情 | device test_cross_tenant_detail_blocked | 通过 |
| INV-TENANT-03 | 租户 A 不能修改租户 B 的数据 | 所有模块 test_cross_tenant_update_blocked | 通过 |
| INV-TENANT-04 | 租户 A 不能删除租户 B 的数据 | 所有模块 test_cross_tenant_delete_blocked | 通过 |

## 3. CRUD 数据完整性不变量

| ID | 不变量 | 保护测试 | 状态 |
|---|---|---|---|
| INV-CRUD-01 | 创建失败不留下半条数据 | 所有模块 test_create_failure_no_partial_data | 通过 |
| INV-CRUD-02 | 修改一条记录不影响其他记录 | 所有模块 test_update_one_doesnt_affect_others | 通过(fault) |
| INV-CRUD-03 | 软删除保留数据 | 所有模块 test_soft_delete_preserves_data | 通过(fault/interference) |
| INV-CRUD-04 | 删除设备不删除历史事件 | device test_delete_device_doesnt_delete_events | 通过 |

## 4. 审计记录不变量

| ID | 不变量 | 保护测试 | 状态 |
|---|---|---|---|
| INV-AUDIT-01 | 创建操作写入审计日志 | 所有模块 test_audit_log_records_create | 通过(device/fault) |
| INV-AUDIT-02 | 删除操作写入审计日志 | 所有模块 test_audit_log_records_delete | 通过(fault) |

## 5. 告警特有不变量

| ID | 不变量 | 保护测试 | 状态 |
|---|---|---|---|
| INV-ALERT-01 | 标记已读幂等 | AlertMarkReadIdempotencyTest | 跳过(环境问题) |
| INV-ALERT-02 | 处理后状态变为 resolved | AlertResolveTest | 跳过(环境问题) |
| INV-ALERT-03 | 告警级别合法 | AlertLevelTest | 通过 |

## 6. 不在 stable_contract 中过度断言的内容

以下内容不应在 stable_contract 中断言：
- 当前数据库表名（tdyw_device_resume 等）
- 当前模型类名（DeviceResume 等）
- 当前 JSON 字段完整集合
- 当前内部 Service 调用次数
- 当前 DeviceResume 的所有字段
- 当前名称文本关联方式
- 当前候选项实现方式
