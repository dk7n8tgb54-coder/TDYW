# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount** `/mnt/e/TDYW/spug-3.0/spug_api -> /data/spug/spug_api`，改代码即时可见；连 dev 库；makemigrations/migrate 验证用此容器
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
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步(加字段->回填->查重->AlterField)；4. CharField->Date 先洗空串；5. MariaDB 不支持部分唯一索引，is_deleted=True 设 NULL；6. 改 default_auto_field 触发所有老表 alter id；7. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`

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
- migration: `fault/0005` + `runlog/0013`
- 待修复（P0）: DepartmentDutyLog 新增 duty_date 独立索引
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
