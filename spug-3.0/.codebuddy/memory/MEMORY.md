# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount** `/mnt/e/TDYW/spug-3.0/spug_api -> /data/spug/spug_api`；连 dev 库；makemigrations/migrate 验证用此容器
- ⚠️ **改完后端代码后必须重启容器才能生效**：`docker exec` 启动的一次性命令（`manage.py check`/`test`/`makemigrations`）能读到最新代码；但 **Django dev server（gunicorn/supervisor 长驻进程）不会自动热更新**，已加载的模块不会变。重启命令：`wsl bash -c 'docker restart tdyw-test'`。每次改完后端代码后，验证前务必先重启容器
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx）
- ⚠️ Docker 内网回调：kkFileView 经 `http://tdyw` 回源，容器名须进 ALLOWED_HOSTS
- ⚠️ 生产单块机械盘：`chunks`/`documents`/`media` 同处 `/dev/sdd`。合并 worker 并发已降至 1 + 缓冲 16MB + fallocate 预分配

## 数据库配置
- `ATOMIC_REQUESTS=True`（每个请求自动事务）；`CONN_MAX_AGE=0`（gevent 兼容，禁连接池）
- 未显式配置 `isolation_level`（MySQL 默认 RR）
- MariaDB 10.8.2；`sql_mode=STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,...`

## 测试与压测
- 10 app 有测试(465 全绿)；7 app 冒烟模板；6 app 无测试（document极复杂/evidence无HTTP入口/exec/schedule/safety_question_bank）
- 运行：`docker exec ... tdyw python manage.py test apps.xxx.tests --noinput`
- locust runner `./locustfile/run_all_locust.sh`；SLA `locustfile/SLA_THRESHOLDS.md`
- 测试要点：access_token 32 字符；Role.created_by NOT NULL；User.tenant_id 默认 'admin'；make_user 设 version=0；json_response 错误时 data=''；update_by_dict 过滤 None；USE_TZ=False 禁 make_aware；test client 路径无 `/api/` 前缀；makemigrations 指定 app；上传 post 不返回 id 前端按名匹配

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步(加字段->回填->查重->AlterField)；4. CharField->Date 先洗空串；5. MariaDB 不支持部分唯一索引；逻辑删除时唯一约束冲突解法：CharField 追加 `__deleted_{id}` 后缀（不设 NULL，Django 官方反对 CharField null=True）；6. 改 default_auto_field 触发所有老表 alter id；7. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`；8. **CharField/TextField 禁止 null=True**（Django 官方：两种"空"状态 NULL 和 '' 导致查询歧义）

## 批量删除陷阱 ⚠️
- QuerySet 切片惰性重查，删循环用 `while True: batch=list(qs.exclude(id__in=failed_ids)[:BATCH])` + max_iterations 安全阀，绝不用 `range(count)+qs[start:end]`

## 代码验证流程
1. `read_lints`；2. py: `docker exec tdyw python -m py_compile <path>`；3. js: `node -e "@babel/parser"`；4. `git diff`；5. Django 测试必在容器内

## 模块架构速查
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token）；radio_license/contract_agreement/device/upgrade/fault/interference/department_duty_log 均走此机制存 MEDIA_ROOT；**例外：regulation 走独立 `storage.py`**
- 账号签名 `apps/signature`（apply_signature 事务锁->SHA256->Usage+EvidenceEvent）
- 党建隔离 `DocumentSystemFolder` + `system_scope_validators`（fail-closed）
- 权限缓存 `User.page_perms` Redis `perms_{id}`=(version,perms)
- kkFileView `KKFILEVIEW_API_URL`(浏览器)/`KKFILEVIEW_SERVER_URL`(回源)
- 磁盘用量 `DiskUsageView` Redis 缓存 60s
- preview_token **两套独立实现**（document/libs vs evidence/attachment_preview_token）待收口

## Celery
- 17 `@shared_task` / 5 队列；11 Beat + 6 事件触发
- `retry_clean_pending_files` 是 `is_pending_clean` 唯一消费者，不可删

## Django 升级路线
- 2.2->3.2->4.2.30(完成)->5.2 LTS(待做)；Channels4 consumer `__init__` 禁访问 `self.scope`

## 生产内存(8G)
- tdyw 2G/tdyw-db 3G(innodb_buffer_pool 2G)/kkfileview 1.5G；MySQL max_connections 300

## 权限码
- 新功能走 UI `pages/system/role/codes.js`->角色勾选->`PATCH /api/account/role/`；不写 `.sql` 预置；`is_supper` 放行

## 反思清单（跨会话必遵）
1. 反问质疑立即认错不掩盖；2. 增量>大爆炸+YAGNI+向后兼容；3. 配置化>硬编码(同串≥3处抽出)；4. 参考成熟产品+行业惯例；5. 每次修复后全局扫描同类；6. error 字段一致性(正常态无 error)；7. `obj?.method()` 触发 no-unused-expressions->`if(obj)obj.method()`；8. Model.save 签名 `def save(self,*args,**kwargs)`；9. 嵌套 atomic 仅 savepoint；10. 备份恢复同周期(DB->documents)

## CRUD 可靠性编码规范（新增/修改代码必遵）
> 来源：`CRUD系统可靠性指南.md`，以下为各章节的编码落地要求

### 数据库约束（1.1）
- NOT NULL / UNIQUE / CHECK / FK 必须在数据库层强制，不能仅靠应用层校验
- 外键 `ON DELETE` 按业务语义选：CASCADE(级联) / SET_NULL(置空) / PROTECT(禁止删)
- 唯一约束是幂等性的数据库层保障，核心业务表必须建唯一约束防重复
- **CharField/TextField 禁止 null=True**（Django 官方：两种"空"状态导致查询歧义）

### 事务边界（1.2）
- 所有涉及多步写操作的业务逻辑必须 `transaction.atomic()` 包裹
- 事务粒度尽量小，禁止事务内做长阻塞外部调用（HTTP 长重试等）
- 禁止事务内循环写入大批量数据，应分批提交
- 嵌套 atomic 仅创建 savepoint，不开启新事务
- 项目隔离级别 RR（MariaDB 默认），低并发内部系统无需改 RC

### 幂等性设计（1.3）
- 核心写操作设计幂等键（业务唯一约束 + `INSERT ... ON DUPLICATE KEY UPDATE`）或 request_id 去重
- 异步任务用状态机控制：只有特定状态才允许执行，执行后原子更新状态
- DELETE 天然幂等；UPDATE 用绝对值而非增量（`SET count = 5` 而非 `count + 1`）
- 已有工具：`libs/idempotency.py` 的 `check_recent_duplicate(model, filters, window_seconds=30)`

### 防误操作与可追溯（1.5）
- 核心业务表用逻辑删除替代物理删除（is_deleted + deleted_at）
- 关键数据变更留痕：操作人、变更前后值、时间戳（审计日志 `apps/logs`）
- 高风险操作（批量删除、全表更新）增加二次校验 + 权限管控
- 数据库账号最小权限：应用账号无 DROP/TRUNCATE 权限

### 索引与慢查询（2.1）
- 所有业务查询上线前必须核对执行计划（EXPLAIN）
- 禁止无边界查询（不带时间范围、不带筛选条件的全表列表/导出）
- **DateTimeField 禁用 `__date`/`__year`/`__month`/`__startswith`/`__icontains`**，改用 `__gte`/`__lt` 范围查询
- `LIKE '%xxx'` 前缀通配无法走索引
- 复合索引遵循最左前缀原则
- 导出操作加上限行数 + 异步生成

### 可追溯日志体系（3.2）
- 错误日志必须带完整上下文：请求参数、链路 ID（request_id）、异常栈
- 数据操作日志可定位到具体人、具体时间、具体变更内容（变更前后值）
- 日志分级：ERROR 触发告警，WARN 记录观察，INFO 用于审计追溯
- 保留周期：操作审计日志 ≥ 180 天，错误日志 ≥ 30 天
- 告警通过 `libs/alert.py` 的 `send_alert()` 统一发送

### 数据库变更规范（4.1）
- 大表 DDL 用在线工具（pt-online-schema-change / gh-ost），避免锁表
- MariaDB 不支持部分唯一索引，加唯一约束前先清洗重复数据
- 改字段类型先洗空串/非法值再迁移
- 禁止无 WHERE 条件的 UPDATE/DELETE
- 变更前必须先备份对应表
- 加字段优先 nullable + default，避免锁表和 NOT NULL 失败
- 拆步操作：加字段 -> 回填 -> 查重 -> 加约束，每步可独立回退
- **makemigrations 必须指定 app 名**，避免扫描全项目生成意外迁移

## 备份恢复脚本
- 入口 `backups/backup_set_create.sh` / `backup_set_restore.sh`；Python 工具全部在 `backups/` 目录（不在 `scripts/`）
- DB->documents/media 必须同一停写窗口

## 数据库性能优化（2026-07-29）
- `__date` 绕过索引（翻译成 `DATE(col)=...`），改用 `__gte`/`__lt` + datetime 范围
- `__startswith` 在 DateTimeField 上绕过索引；CharField 不受影响
- `__year`/`__month` 绕过索引（翻译成 `YEAR(col)=N AND MONTH(col)=N`），改用 `__gte`/`__lt`
- `.extra({'date': 'DATE(col)'})` 绕过索引 + 产生 `Using temporary; Using filesort`
- `__icontains` 在 DateTimeField 上生成 `CAST(col AS CHAR) LIKE '%xxx%'`，绕过列索引（tenant_id 索引仍可用）
- `__icontains` 在无索引 CharField/TextField 上：`LIKE '%xxx%'` 前缀通配符无法用 B-Tree 索引
- **复合索引最左前缀违反**：`DepartmentDutyLog` 的 `(status, deleted_at, duty_date)` 索引，大多数查询直接按 `duty_date` 过滤，索引完全不可用（EXPLAIN 确认 type=ALL）
- Dashboard `home/views.py:get_statistic` 已加 Redis 缓存 60s
- audit_logs 关键词搜索默认限制最近 90 天
- migration: `fault/0005` + `runlog/0013` + `department_duty_log/0009_add_duty_date_index`
- **已修复（P0-P3，2026-07-30）**：
  - P0: DepartmentDutyLog 新增 `duty_log_date_idx(-duty_date, -id)` 索引 + 改 `__year/__month` 为 `__gte/__lt`
  - P1: `fault/exporters.py` `fault_date__icontains` -> 智能日期解析 `_parse_fault_date_filter()`；`upgrade/statistics_service.py` `.extra(DATE())` -> 逐日范围查询(≤365天)/TruncDate(>365天)
  - P2: `fault/views.py` system_names 加 Redis 缓存(5min)；runlog/device 证据包审计日志加 90天+1000条限制
  - P3: device 导出加 10000 条限制；department_duty_log 加 `MAX_QUERY_DAYS=365` 查询范围限制
- 完整排查报告：`INDEX_RISK_AUDIT_REPORT.md`

## 幂等性设计（2026-07-29）
- 新增 `libs/idempotency.py`：`check_recent_duplicate(model, filters, window_seconds=30)` 时间窗口去重工具
- 8 个 view 的 POST 分支已加 dedup：duty/fault(×2)/interference/runlog/regulation(×2)/home(×2)
- `document/tasks/merge.py` `_create_file_instance` 加了 `FileModel.objects.filter` 存在性检查（Celery 重试幂等）
- 测试：`apps/idempotency_risk_tests.py`（10 TestCase，`docker exec tdyw-test python manage.py test apps.idempotency_risk_tests`）
- `signature` 模块有完整 request_id 幂等机制，是项目最佳实践标杆
- 未修复（低优先级）：前端表单 loading / DepartmentDutyLog / UpgradeRecordStep / RadioLicense

## 公共组件
- `libs/pagination.py`: `paginate(request)` + `paginate_response(qs, page, page_size, serialize_fn, items_key)`
- `libs/date_utils.py`: `date_range_filter` + `today_range()` + `month_range()` + `parse_date()`
- date_range_filter 格式：纯日期 'YYYY-MM-DD' -> `__lt: dt+1day`；含时间 -> `__lte: dt`
