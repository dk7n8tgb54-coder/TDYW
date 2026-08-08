# 覆盖缺口报告

## 1. 已覆盖的稳定业务不变量

### 完全覆盖
- 认证边界（所有 5 模块）
- 权限边界（device/fault）
- 租户列表隔离（device/fault/interference）
- 跨租户修改阻止（device/fault/interference）
- 跨租户删除阻止（device/fault/interference）
- 创建失败数据完整性（device/fault/interference）
- 软删除保留数据（fault/interference）
- 审计记录（device/fault）
- 旧架构字段记录（全部 5 模块，46 个测试全通过）

### 部分覆盖
- CRUD 完整性（device PUT/DELETE 因 CHECK 约束跳过）
- 审计记录（interference 因字段缺失失败）
- 告警幂等/处理（alert 因中间件认证跳过）

### 未覆盖
- upgrade 模块所有 stable_contract（中间件认证问题，21 个跳过）
- alert 模块大部分 stable_contract（中间件认证问题，7 个跳过）
- 统计不混入其他租户（upgrade 跳过）
- 附件数据库与物理文件一致（未测试）
- 重复请求幂等性（未测试 check_recent_duplicate）
- 已关闭/已完成对象的再次操作规则（未测试）
- 日期、时间和状态流转合法性（未测试）

## 2. 环境阻塞

| 阻塞 | 影响范围 | 原因 | 建议 |
|---|---|---|---|
| 中间件认证失败 | upgrade/alert 模块 | make_user + make_client 创建的认证用户访问 /upgrade/ 和 /alert/ URL 时返回"验证失败" | 调查中间件 _authenticate_x_token 在测试环境的行为 |
| DeviceResume CHECK 约束 | device PUT/DELETE | device_delete_fields_valid 约束阻止保存 | 调查约束逻辑和触发条件 |
| Interference is_reported 必填 | interference create | 缺少 is_reported 字段返回错误 | 已在测试中添加字段 |

## 3. 未测试的业务规则

| 规则 | 原因 | 优先级 |
|---|---|---|
| 重复请求不产生重复数据 | 需要模拟快速重复提交 | 中 |
| 附件物理文件与数据库一致 | 需要文件系统测试环境 | 中 |
| 已关闭对象再次操作规则 | 需要状态流测试 | 中 |
| 统计不混入其他租户 | upgrade 跳过 | 中 |
| 告警 Celery 重复执行幂等 | 需要 Celery 测试环境 | 低 |
| 告警已停用规则不产生新告警 | 需要 Celery 测试环境 | 低 |

## 4. legacy_characterization 覆盖

| 模块 | 已记录行为数 | 覆盖状态 |
|---|---|---|
| device | 10 | 完整 |
| fault | 10 | 完整 |
| upgrade | 9 | 完整 |
| interference | 4 | 基本完整 |
| alert | 6 | 完整 |

## 5. 建议补充的测试

1. **修复中间件认证问题** - 解锁 28 个跳过的测试
2. **修复 DeviceResume CHECK 约束** - 解锁 4 个条件跳过的测试
3. **增加幂等性测试** - 测试 check_recent_duplicate
4. **增加状态流测试** - 测试已关闭对象的再次操作
5. **增加附件一致性测试** - 测试物理文件与数据库一致
