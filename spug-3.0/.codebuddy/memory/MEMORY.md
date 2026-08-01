# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount** `/mnt/e/TDYW/spug-3.0/spug_api -> /data/spug/spug_api`；连 dev 库；makemigrations/migrate 验证用此容器
- ⚠️ **改完后端代码后必须重启容器才能生效**：`docker exec` 启动的一次性命令能读到最新代码；但 Django dev server（gunicorn/supervisor 长驻进程）不会自动热更新。重启：`wsl bash -c 'docker restart tdyw-test'`
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx）
- ⚠️ Docker 内网回调：kkFileView 经 `http://tdyw` 回源，容器名须进 ALLOWED_HOSTS
- ⚠️ 生产单块机械盘：`chunks`/`documents`/`media` 同处 `/dev/sdd`

## 数据库配置
- `ATOMIC_REQUESTS=True`；`CONN_MAX_AGE=0`（gevent 兼容）；MariaDB 10.8.2；`sql_mode=STRICT_TRANS_TABLES,...`

## 测试与压测
- 10 app 有测试(465 全绿)；7 app 冒烟模板；6 app 无测试
- 运行：`docker exec ... tdyw python manage.py test apps.xxx.tests --noinput`
- ⚠️ **Django test runner 创建 test_spug 失败**：迁移依赖顺序问题（radio_license_version 外键约束）。解决方案：① 手动创建 test_spug ② 从 dev 库复制 schema + django_migrations 表 ③ 用 `--keepdb` 运行。或直接写独立脚本用 dev 库跑（如 `run_evidence_audit.py`）
- 测试要点：access_token 32 字符；Role.created_by NOT NULL；User.tenant_id 默认 'admin'；make_user 设 version=0；json_response 错误时 data=''；update_by_dict 过滤 None；USE_TZ=False 禁 make_aware；test client 路径无 `/api/` 前缀；makemigrations 指定 app

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步；4. CharField->Date 先洗空串；5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀；6. 改 default_auto_field 触发所有老表 alter id；7. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`；8. **CharField/TextField 禁止 null=True**

## 批量删除陷阱 ⚠️
- QuerySet 切片惰性重查，删循环用 `while True: batch=list(qs.exclude(id__in=failed_ids)[:BATCH])` + max_iterations 安全阀

## 代码验证流程
1. `read_lints`；2. py: `docker exec tdyw python -m py_compile <path>`；3. js: `node -e "@babel/parser"`；4. `git diff`；5. Django 测试必在容器内

## 模块架构速查
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token）；radio_license/contract_agreement/device/upgrade/fault/interference/department_duty_log 均走此机制；**例外：regulation 走独立 `storage.py`**
- regulation 审计发现（2026-08-01 修复）：**R1(P0)** Regulation 无 created_at 导致 check_recent_duplicate FieldError（已加字段+migration 0009）；R2/R3/R4 save() 无 update_fields（已修复）；R5 删除时冗余 soft-delete 被 CASCADE 覆盖（已移除）；R6 4处 icontains 改 startswith（保留 title 模糊搜索）；R7 page/page_size 死代码（已删除）；R9 PreviewFileView 统一用 _get_attachment。**7 项全部修复，15/15 PASS**
- evidence 审计发现（2026-07-31）：**R4(P0)** 哈希链 `record_evidence_event` 缺 `select_for_update` 并发竞态；**R8(P1 BUG)** `download_response` 未过滤 `is_deleted`；R5 soft_delete_by_object 无 atomic；R7 哈希链重试不幂等。**4 项已修复**（select_for_update + is_deleted=False + transaction.atomic + idempotency_key）。报告：`EVIDENCE_CRUD_AUDIT_REPORT.md`
- document 审计+修复（2026-08-01）：**R1(P1)** `get_active_descendant_folder_ids` 无循环引用检测→无限循环（properties.py:30-50，已运行时确认 5s 超时）；**R2(P1)** `folder_copy_service.py` 无事务保护（复制中途失败残留副本树）；**R9(P1)** `_delete_folder` 无外层事务（部分删除无法回滚）；R3 文件夹创建无审计日志（AUDIT_ACTION_MAP 缺 FOLDER_CREATE）；R4/R6/R7 save() 无 update_fields（folder/move.py + merge.py）；R5 folder/move 作用域重校验在事务外（TOCTOU，file/move 已正确）；R10 generate_unique_name while 无 max_iter。**10 项全部已修复并验证通过**（11/11 PASS）。修复验证脚本：`apps/document/tests/test_document_fix_verify.py`。报告：`DOCUMENT_AUDIT_REPORT.md`
- interference 审计+修复（2026-08-01）：**R1(P1)** Export is_deleted 过滤 / **R2(P1)** 证据包 fallback 90天+1000行限制 / R3+R4+R12 删除 `transaction.atomic()`+`update_fields`+`select_for_update` / R5 `Substr`->`TruncDate` / R6 创建事务 / R7 通用错误消息 / R9 datetime null=False (migration 0009) / R10 删重复 timezone 导入 / R13 count() 缓存。**11 项修复全部验证通过**，R8 接受（快照模式）。报告：`INTERFERENCE_CRUD_AUDIT_REPORT.md`
- logs 审计发现（2026-08-01）：**7 项确认风险**。R1 CharField null=True（tenant_id/request_id/user_agent，Migration 0008 遗漏）；R2/R3 `__icontains` 绕过索引（detail TextField + username 有 Meta.indexes）；R4 无关键词无时间范围时缺默认 90 天限制；R6 `_capture_before_values` 用 SELECT *；**R7 verify_hash_chain 已实现但无调用入口**（无 URL/视图/Beat/Task）；R11 cleanup 无审计记录。R5 误报：verify_hash_chain 的 has_prev 设计能优雅处理 cleanup 删链首。报告：`LOGS_AUDIT_REPORT.md`
- home/navigation 审计发现（2026-08-01）：**R1/B1(P0)** PATCH sort swap 缺 `transaction.atomic()`（行为验证：mock save 失败后两记录 sort_id 冲突）；**R2/B2(P1)** POST create 缺 `transaction.atomic()`（孤儿记录 sort_id=0）；**R3/B3(P1)** DELETE 缺 `transaction.atomic()`（audit 日志已写但记录未删除）；**R4(P1)** POST create/edit 缺 `record_audit_event`；R6 GET 未过滤租户；R7/R8 模型缺 updated_at/deleted_by；R9/B4 to_view `json.loads` 无 try/except 致 500；B5/B6 不存在 ID 静默成功；B7 `check_recent_duplicate` 未过滤 `is_deleted`。**22 项全部验证为真**。对照 notice.py（已修复事务+行锁）发现 navigation 未同步修复。脚本：`apps/home/run_navigation_audit.py`
- home/navigation+notice 修复（2026-08-01）：4 文件修复 + 1 迁移(0009)。navigation.py：POST/PATCH/DELETE 全加 `transaction.atomic()`+`select_for_update()`+`record_audit_event`+`update_fields`+不存在ID错误返回。notice.py：DELETE 加事务+审计，POST 加审计日志。models.py：两模型补 5 字段(updated_at/updated_by_id/updated_by_name/deleted_by_id/deleted_by_name)+to_view 加 try/except。idempotency.py：`check_recent_duplicate` 加 `is_deleted=False` 过滤。**18/18 验证通过**。脚本：`apps/home/run_fix_verification.py`
- upgrade 审计发现（2026-08-01）：**is_deleted 软删除泄漏重灾区（9 处）**。**R01-R04(P0)** upload.py/exporters.py/statistics_service.py/status_log_service.add_log 全部未过滤 `is_deleted=False`（2026-07-30 加了字段但服务层/视图层未适配）；**R05/R06(P1)** apply_to_record replace 物理删除+append start_seq 夸大；**R07(P1)** 日期范围 `__lte` 边界（单日只匹配午夜）；**R08(P1)** batch_update_status 状态日志在 `transaction.atomic()` 外；**R10a-d(P1)** 4 处 `save()` 无 `update_fields`；R09/R13/R14 步骤/记录过滤遗漏 `is_deleted`；R11 icontains 性能；R12 `created_at=now_str` 死代码。**19 项全部验证为真**。报告：`UPGRADE_CRUD_AUDIT_REPORT.md`。**修复完成（19/19 验证通过）**：① `TenantModelManager.get_queryset()` 自动过滤 `is_deleted=False`（根治 9 处泄漏）② `UpgradeRecordStep` 添加 `objects = TenantModelManager()` ③ replace 模式物理删除->软删除 ④ 日期范围 `__lte`->`__lt`+1天 ⑤ 状态日志移入 atomic 块 ⑥ 4处 save 加 update_fields ⑦ icontains->startswith ⑧ 移除 created_at 死代码
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

## CRUD 可靠性编码规范（摘要）
- NOT NULL/UNIQUE/CHECK/FK 必须在 DB 层强制；外键 ON DELETE 按语义选
- 所有多步写操作必须 `transaction.atomic()` 包裹；事务粒度小，禁止事务内长阻塞外部调用
- 核心写操作设计幂等键；异步任务用状态机控制
- 核心业务表用逻辑删除；高风险操作二次校验+权限管控
- **DateTimeField 禁用 `__date`/`__year`/`__month`/`__startswith`/`__icontains`**，改用 `__gte`/`__lt`
- `LIKE '%xxx'` 前缀通配无法走索引；复合索引遵循最左前缀
- makemigrations 必须指定 app 名
- CharField/TextField 禁止 null=True

## 数据库性能优化（2026-07-29）
- `__date`/`__year`/`__month` 绕过索引，改用 `__gte`/`__lt` + datetime 范围
- `__icontains` 在无索引 CharField/TextField 上：`LIKE '%xxx%'` 前缀通配符无法用 B-Tree 索引
- 已修复 P0-P3：DepartmentDutyLog 索引+查询优化、fault 导出日期解析、upgrade 统计 TruncDate、Redis 缓存、导出限制
- 完整排查报告：`INDEX_RISK_AUDIT_REPORT.md`

## 幂等性设计（2026-07-29）
- `libs/idempotency.py`：`check_recent_duplicate(model, filters, window_seconds=30)`
- ⚠️ `check_recent_duplicate` **未过滤 `is_deleted` 和 `tenant_id`**（2026-08-01 navigation 审计发现 B7）：软删除记录会触发误判，跨租户同标题也会误判
- 8 个 view 的 POST 已加 dedup；signature 模块有完整 request_id 幂等机制（标杆）
- 测试：`apps/idempotency_risk_tests.py`

## 发布回滚脚本（2026-07-31）
- `docker/scripts/`：deploy.sh（双 tag 镜像+健康检查+自动回滚）、rollback.sh、post_deploy_watch.sh
- 运行：`wsl bash -c '/mnt/e/TDYW/spug-3.0/docker/scripts/deploy.sh'`

## 公共组件
- `libs/pagination.py`: `paginate(request)` + `paginate_response(qs, page, page_size, serializer)`
- `libs/tenant_utils.py`: `apply_tenant_filter(qs, user)` 多租户隔离
- `libs/alert.py`: `send_alert()` 统一告警
- `apps/logs/audit.py`: `record_audit_event()` 审计日志

## 历史项目
- 资料库回收站功能已于 2026-06-23 完全移除（模型层保留 is_deleted/deleted_at 字段避免 migration）
- 资料库传输列表：3 Tab + 抽屉模式 + 拖拽把手 + 闪烁 + 快捷键 + ERROR_CODES 错误分类（参考阿里云盘/百度网盘）
- Babel 验证脚本：`node --check` 不支持 ESM，需 `@babel/core` + decorators + class-properties 插件

## ⚠️ 永久教训
- `manage.py flush` 会清空所有数据，绝对禁止在 dev/prod 容器执行
- tdyw-test 容器连的是 dev 库（不是独立测试库），flush/migrate/delete 都会影响 dev 数据
