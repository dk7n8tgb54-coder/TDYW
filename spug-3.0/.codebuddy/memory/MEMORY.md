# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount**；连 dev 库；验证用此容器
- ⚠️ 改完后端代码后必须重启容器才能生效。重启：`wsl bash -c 'docker restart tdyw-test'`
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx）
- kkFileView `KKFILEVIEW_API_URL`(浏览器)/`KKFILEVIEW_SERVER_URL`(回源)，容器名须进 ALLOWED_HOSTS
- MariaDB 10.8.2；`ATOMIC_REQUESTS=True`；`CONN_MAX_AGE=0`；`sql_mode=STRICT_TRANS_TABLES`
- ⚠️ **永久教训**：`manage.py flush` 会清空所有数据，绝对禁止在 dev/prod 容器执行。tdyw-test 连 dev 库。

## 测试体系
- E2E: `quality/e2e/`，109 条 Playwright 测试，admin/E2E@Test2026! + e2e_tester/E2E@Test2026!
  - 前端用 `createBrowserHistory()`，路由 `/home`（非 `/#/home`）；Token 存 sessionStorage `token`，请求头 `X-Token`
  - `page.addInitScript()` 注入 sessionStorage 可免 UI 登录；antd Button 中文有空格用 `/登\s*录/`
- 资料库回归测试（2026-08-09）：三层 42 tests 在 `apps/document/tests/regression/`（快速14+标准16+完整12）
  - Django test runner 无法发现包级路径，需指定到具体 `.py` 模块
  - `retry_clean_pending_files` 有 3600s 冷却期，测试需重置 `last_clean_attempt`
  - Celery 合并任务名是 `merge_file_chunks`（非 `merge_chunks`，后者是 ChunkMerger 方法）
  - `DirectMergeView` 幂等检查：COMPLETED + 文件存在 -> `is_idempotent=True`
  - `TransferStatus` 无 CALCULATING；FAILED 非终态（允许重试）
  - 容错测试 19 个（8 维度）：删除补偿/broker不可达/kkFileView降级/幂等/状态机/边界bug/合并超时/清理重试上限
  - mock `safe_delete_document_file` 需双路径 patch：`pending_files` 模块级 import + `document_utils` 源模块（mixin 内 local import）
  - `auto_now=True` 字段设旧值用 `Model.objects.filter(id=...).update(field=old_time)` 绕过
- 日常业务特征测试（2026-08-08）：5 模块 279 项，各模块 `tests/characterization/`
  - 3 个生产缺陷：DUTY-001(duty timezone P0)、RUNLOG-001(closed datetime序列化 P0)、RUNLOG-002(duty_person NOT NULL P1)
  - 测试数据库初始化：Django test runner 迁移顺序失败，改用从 spug 克隆表结构+django_migrations
  - _make_record 须设 tenant_id；软删除后须用 all_with_deleted()；日期格式 19 字符
- 测试要点：test client 路径无 `/api/` 前缀；makemigrations 指定 app；需设 HTTP_X_REAL_IP + ALLOWED_HOSTS
- access_token 32 字符；Role.created_by NOT NULL；User.tenant_id 默认 'admin'；json_response 错误时 data=''

## 模块架构速查
- 数据分析 `apps/data_analysis`（纯只读聚合，无 model/migration）
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token）
  - radio_license/contract_agreement/device/upgrade/fault/interference/department_duty_log 走此机制
  - **例外：regulation 走独立 `storage.py` + RegulationAttachment**
  - 附件新建阶段：前端生成临时 UUID 作为 `object_id`，后端 `pk.isdigit()` 跳过记录存在性校验
- 账号签名 `apps/signature`（apply_signature 事务锁->SHA256->Usage+EvidenceEvent）
- 党建隔离 `DocumentSystemFolder` + `system_scope_validators`（fail-closed）
- ⚠️ 私有空间已于 2026-08-11 移除：DocumentFilePrivate/DocumentFolderPrivate 模型+表已删，get_folder_model/get_file_model 始终返回 Public，DocumentTransfer.is_public 保留但 default=True
- 权限缓存 `User.page_perms` Redis `perms_{id}`=(version,perms)
- preview_token **两套独立实现**（document/libs vs evidence/attachment_preview_token）待收口
- Celery: 18 `@shared_task` / 5 队列；12 Beat + 6 事件触发；`retry_clean_pending_files` 不可删
- 公共组件: `libs/pagination.py`/`tenant_utils.py`/`alert.py`/`idempotency.py`（已含 is_deleted=False）；`apps/logs/audit.py`

## 租户隔离
- **TenantModelManager 只过滤 is_deleted，不自动过滤 tenant_id** -> Views 须手动调 apply_tenant_filter
- **WP5 修复（2026-08-08/09）**: NavView/NoticeView 已删除；Navigation 功能完全移除（migration 0011）
- ReminderUsersView 跨租户返回所有科室用户是**刻意设计**（科室间提醒），不修改
- 全局数据(无tenant_id): Regulation/Setting/Alert/AlertRead/DocumentSystemFolder/AuditLogSequence
- 超管(is_supper=True)绕过所有租户过滤(已知设计)
- JsonParser 默认 type=str: 列表传给无 type=list 的 Argument 会被 str() 转为单引号字符串

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步；4. CharField->Date 先洗空串
5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀
6. 改 default_auto_field 触发所有老表 alter id；7. FK 引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`
8. **CharField/TextField 禁止 null=True**；**DateTimeField 禁用 `__date`/`__year`/`__month`**，改用 `__gte`/`__lt`

## 审计修复记录（2026-08-01 批量）
- regulation 15/15 / evidence 4 / document 19 / interference 11 / logs 7
- home/navigation+notice 18/18 / upgrade 19/19 / department_duty_log 114/114 / radio_license+contract_agreement 28/28
- 数据库审计: 无严重风险；高3(6表缺tenant_id索引/fault_date__icontains/nav全软删)；中5(CharField null=True/缺is_deleted索引/重复索引)
- 孤儿数据 0 条；is_pending_clean 0 条；排班模块残留：零

## 反思清单（跨会话必遵）
1. 反问质疑立即认错不掩盖；2. 增量>大爆炸+YAGNI+向后兼容；3. 配置化>硬编码(同串≥3处抽出)
4. 参考成熟产品+行业惯例；5. 每次修复后全局扫描同类；6. error 字段一致性(正常态无 error)
7. `obj?.method()` 触发 no-unused-expressions->`if(obj)obj.method()`；8. Model.save 签名 `def save(self,*args,**kwargs)`
9. 嵌套 atomic 仅 savepoint；10. 备份恢复同周期(DB->documents)

## 历史项目
- 资料库回收站 2026-06-23 移除（模型层保留 is_deleted/deleted_at 避免 migration）
- 资料库传输列表：3 Tab + 抽屉模式（参考阿里云盘/百度网盘）
- 秒传/跨 transfer 哈希复用 2026-08-07 移除。保留断点续传
- 上传链审计（2026-08-05）：P0 `ALLOWED_STATUS_TRANSITIONS` 缺 `UPLOADING->COMPLETED`；已修复 DirectMergeView COMPLETED 分支
- Babel 验证脚本：`node --check` 不支持 ESM，需 `@babel/core` + decorators + class-properties 插件
