
## 测试计划：验证公告模块 6 个审查发现

### 测试文件清单

| # | 测试文件 | 类型 | 验证的 Bug |
|---|---|---|---|
| 1 | `spug_api/apps/home/tests/defect_reproduction/test_bug3_scope_lost_on_edit.py` | Django TestCase | Bug 3（编辑时 scope 丢失） |
| 2 | `spug_api/apps/home/tests/defect_reproduction/test_bug4_publish_race_condition.py` | Django TestCase + threading | Bug 4（发布/撤回竞态条件） |
| 3 | `spug_api/apps/home/tests/defect_reproduction/test_bug5_null_published_at_ordering.py` | Django TestCase | Bug 5（未发布公告 NULL 排序） |
| 4 | `spug_api/apps/home/tests/defect_reproduction/test_bug2_celery_schedule_expression.py` | Django TestCase | Bug 2（Beat Schedule 表达式验证） |
| 5 | `spug_web/src/pages/system/announcement/__tests__/bug1_double_error_notification.test.js` | Jest 单元测试 | Bug 1（双重错误提示） |
| 6 | `spug_web/src/pages/system/announcement/__tests__/bug3_edit_scope_tenant_ids.test.js` | Jest 单元测试 | Bug 3 前端佐证（表单不传 scope 数据） |

### 测试详细设计

---

#### 后端测试 1：Bug 3 — 编辑指定部门公告时 scope 丢失

**文件**：`test_bug3_scope_lost_on_edit.py`

**核心逻辑**：
1. 创建一个 `scope_type=tenant` 的公告，并创建 2 条 `AnnouncementScope` 记录（t1、t2）
2. 通过管理端详情 API `GET /home/announcement/admin/<id>/` 获取数据
3. 断言响应中**不包含** `_scope_tenant_ids` 字段（验证 Bug 存在）
4. 模拟前端编辑流程：将详情返回的数据作为编辑 payload（不补充 scope），POST 到管理端编辑接口
5. 断言保存后 `AnnouncementScope` 记录被清空（0 条），验证 scope 丢失
6. 验证用户端 `is_visible_to()` 返回 False（scope 为 tenant 但无 scope 记录）

**关键断言**：
- `body['data']` 不包含 `_scope_tenant_ids` key
- 编辑后 `AnnouncementScope.objects.filter(announcement=ann).count() == 0`
- `ann.is_visible_to(user_t1) == False`（即使 t1 曾在 scope 中）

---

#### 后端测试 2：Bug 4 — 发布/撤回无并发保护

**文件**：`test_bug4_publish_race_condition.py`

**核心逻辑**：
1. 创建一个 `status=unpublished` 的公告
2. 使用 `threading.Thread` 同时发起 2 个发布请求
3. 等待两个请求都完成
4. 检查公告的 `published_by_id` 和 `published_by_name` 是否来自同一个用户还是两个不同用户
5. 如果两个不同用户的名称都出现在快照中，说明发生了竞态（数据快照不一致）
6. 同样测试撤回操作的竞态条件

**关键断言**：
- 并发发布后公告 `status == STATUS_PUBLISHED`（最终状态正确）
- 检查 `published_by_name` 快照是否被覆盖（说明竞态发生了）
- 两个撤回请求不应报错（因为都通过 `status == STATUS_PUBLISHED` 检查）

---

#### 后端测试 3：Bug 5 — 未发布公告 NULL published_at 排序

**文件**：`test_bug5_null_published_at_ordering.py`

**核心逻辑**：
1. 创建 3 个公告：一个已发布（published_at=2小时前）、一个未发布（published_at=None）、一个未发布（published_at=None）
2. 请求管理端列表，获取返回结果的 id 顺序
3. 断言 `NULL` 值公告在列表中的位置
4. 记录 MariaDB 的 NULL 排序行为（NULLS FIRST 还是 NULLS LAST）
5. 验证这种行为是否与预期一致（未发布公告排在最前面或最后面）

**关键断言**：
- 记录并断言两个 `published_at=NULL` 的公告出现在列表中的具体位置
- 如果 NULL 排在中间或无序，说明排序有问题

---

#### 后端测试 4：Bug 2 — Celery Beat Schedule 表达式验证

**文件**：`test_bug2_celery_schedule_expression.py`

**核心逻辑**：
1. 导入 `HOME_BEAT_SCHEDULE`
2. 解析 `crontab(minute=5)` 的实际含义
3. 断言 schedule 对象的 `minute` 属性值
4. 断言注释说"每小时第 5 分钟"，验证 schedule 确实是每小时 :05 执行
5. 创建一个结束时间为 5 分钟后的已发布公告
6. 模拟 `sync_announcement_status()` 任务执行
7. 验证该公告没有被立即标记为 expired（因为任务在 :05 才运行，而公告可能在 :06 到期）

**关键断言**：
- `schedule.minute == '5'`（不是 `*/5`，不是 `*/1`）
- 验证在最坏情况下，管理端 `status` 字件滞后可达 59 分钟

---

#### 前端测试 5：Bug 1 — 双重错误提示

**文件**：`bug1_double_error_notification.test.js`

**核心逻辑**：
由于项目不使用 DOM 渲染（无 @testing-library），采用纯逻辑测试：
1. Mock `antd` 的 `message.error` 和 `notification.error`，记录调用次数
2. Mock `libs/http` 的拦截器行为（模拟 `handleResponse` 的 reject 逻辑）
3. 从 `index.js` 提取 `doPublish` 的核心逻辑（error → notification.error）
4. 模拟拦截器先调用 `message.error('公告已发布，请勿重复发布')`
5. 然后触发 `.catch(e => notification.error(...))`
6. 断言 `message.error` 被调用了 1 次
7. 断言 `notification.error` 也被调用了 1 次
8. 验证总共有 2 个错误提示被触发（确认 Bug 存在）

**关键断言**：
- `mockMessage.error.mock.calls.length === 1`
- `mockNotification.error.mock.calls.length === 1`
- 错误内容匹配

---

#### 前端测试 6：Bug 3 前端佐证 — 编辑时 scope 数据缺失

**文件**：`bug3_edit_scope_tenant_ids.test.js`

**核心逻辑**：
1. 模拟后端返回的详情数据（不含 `_scope_tenant_ids` 字段）
2. 模拟 `Form.js` 中编辑初始化逻辑（第 21-27 行）
3. 断言初始化后 `target_tenant_ids` 为空数组 `[]`
4. 模拟保存 payload 构造逻辑
5. 断言 payload 中 `target_tenant_ids` 为空数组
6. 这证明编辑时 scope 信息不会被回传给后端

**关键断言**：
- 初始化后 `target_tenant_ids` === `[]`
- 保存 payload 中 `target_tenant_ids` === `[]`

---

### 运行命令

**后端测试**（在 Docker 容器中）：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
  python manage.py test apps.home.tests.defect_reproduction --noinput -v 2
```

**前端测试**（在 spug_web 目录下）：
```bash
cd spug_web && npx react-app-rewired test --testPathPattern="system/announcement/__tests__/bug" --watchAll=false
```

### 目录结构
```
spug_api/apps/home/tests/
  defect_reproduction/
    __init__.py
    test_bug2_celery_schedule_expression.py
    test_bug3_scope_lost_on_edit.py
    test_bug4_publish_race_condition.py
    test_bug5_null_published_at_ordering.py

spug_web/src/pages/system/announcement/
  __tests__/
    bug1_double_error_notification.test.js
    bug3_edit_scope_tenant_ids.test.js
```

### 注意事项
- 所有后端测试遵循项目已有模式（Django TestCase、`_make_user`、`_grant_perms`、`_make_client`、`setup_test_env`）
- 所有前端测试遵循项目已有模式（Jest、`jest.mock('libs/http')`、无 DOM 渲染）
- Bug 6（TenantModelManager 风险）属于架构风险，无法通过单元测试可靠验证，不写测试用例
- 测试分类为 `defect_reproduction`（已确认缺陷的最小复现测试）
