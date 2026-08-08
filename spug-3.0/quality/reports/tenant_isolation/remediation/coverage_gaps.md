# 覆盖缺口

## 已覆盖

### TI-001: NavView 租户隔离
- 本租户列表访问 ✅
- 跨租户列表隔离 ✅
- 跨租户更新阻止 ✅
- 跨租户删除阻止 ✅
- 跨租户排序阻止 ✅
- 创建时 tenant_id 强制绑定 ✅
- 本租户更新成功 ✅
- 本租户删除成功 ✅
- 超级管理员全局可见 ✅

### TI-002: NoticeView 已移除
- 路由不可达 (404) ✅
- 模型已删除 ✅
- 模块文件已删除 ✅
- Announcement 替代模型存在 ✅

### TI-003: ReminderUsersView 租户隔离
- 本租户用户列表成功 ✅
- 跨租户用户不泄露 (id) ✅
- 跨租户用户名不泄露 (username) ✅
- 跨租户昵称不泄露 (nickname) ✅
- tenant_id 字段不暴露 ✅
- 超级管理员全局可见 ✅
- 无权限用户被拒绝 ✅

### Reminder 模块回归
- 本租户列表 ✅
- 跨租户列表隔离 ✅
- 跨租户更新阻止 ✅
- 跨租户删除阻止 ✅
- 创建时 tenant_id 强制绑定 ✅

## 未覆盖

### 1. 缓存命中后切换租户
- **原因**: Navigation 和 Reminder 模块未使用 Redis 缓存层，无缓存相关逻辑需测试。
- **风险评估**: 无风险。这两个模块直接查询数据库，不经过缓存。

### 2. 批量操作/导出入口
- **原因**: Navigation 和 Reminder 模块无批量操作或导出 API。
- **风险评估**: 无风险。

### 3. 搜索词绕过
- **原因**: ReminderUsersView 无搜索参数，仅返回用户列表。
- **风险评估**: 无风险。已验证响应体中不存在其他租户用户的任何字段。

### 4. Django TestCase (manage.py test)
- **原因**: WP5 定向测试使用 `manage.py shell` 脚本方式执行（因 Django test runner 迁移顺序问题），但 `test_home_api.py` 通过 `manage.py test` 成功运行（2 tests OK）。
- **风险评估**: 低。行为测试已通过 `manage.py shell` 验证真实数据库状态和 HTTP 响应。

### 5. 独立测试数据库
- **原因**: `tdyw-test` 容器连接 dev 库 (`spug@db:3306`)。测试在 dev 库上执行，创建和清理临时数据。
- **风险评估**: 中。测试数据使用 UUID 前缀避免冲突，测试后执行 cleanup 删除所有临时数据。但理论上若测试中断可能残留数据。
- **建议**: 后续搭建独立 test_spug 数据库。

## 预存在缺陷（非本任务范围）

### _validate_reminder_form 解包 bug
- `_validate_reminder_form` 返回 `(None, error_str)` 时，调用方 `(target_date, recipients), error = ...` 尝试解包 `None` 导致 TypeError。
- 此为预存在 bug，非本任务引入。当表单数据格式正确时不会触发。已在 REM-05 测试中通过正确格式的 `recipient_users`（JSON 字符串）规避。
