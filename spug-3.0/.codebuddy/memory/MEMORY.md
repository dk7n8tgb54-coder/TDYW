# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount** `/mnt/e/TDYW/spug-3.0/spug_api -> /data/spug/spug_api`；连 dev 库；makemigrations/migrate 验证用此容器
- ⚠️ **改完后端代码后必须重启容器才能生效**：Django dev server 不会自动热更新。重启：`wsl bash -c 'docker restart tdyw-test'`
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx）
- ⚠️ Docker 内网回调：kkFileView 经 `http://tdyw` 回源，容器名须进 ALLOWED_HOSTS
- ⚠️ 生产单块机械盘：`chunks`/`documents`/`media` 同处 `/dev/sdd`

## 数据库配置
- `ATOMIC_REQUESTS=True`；`CONN_MAX_AGE=0`（gevent 兼容）；MariaDB 10.8.2；`sql_mode=STRICT_TRANS_TABLES,...`

## 测试与压测
- 运行：`docker exec ... tdyw python manage.py test apps.xxx.tests --noinput`
- ⚠️ Django test runner 创建 test_spug 失败（迁移依赖顺序问题）：用手动创建 test_spug 或 `--keepdb`；或直接写独立脚本用 dev 库跑
- 测试要点：access_token 32 字符；Role.created_by NOT NULL；User.tenant_id 默认 'admin'；make_user 设 version=0；json_response 错误时 data=''；update_by_dict 过滤 None；USE_TZ=False 禁 make_aware；test client 路径无 `/api/` 前缀；makemigrations 指定 app

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步；4. CharField->Date 先洗空串；5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀；6. 改 default_auto_field 触发所有老表 alter id；7. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`；8. **CharField/TextField 禁止 null=True**

## 代码验证流程
1. `read_lints`；2. py: `docker exec tdyw python -m py_compile <path>`；3. js: `node -e "@babel/parser"`；4. `git diff`；5. Django 测试必在容器内

## 模块架构速查
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token）；radio_license/contract_agreement/device/upgrade/fault/interference/department_duty_log 均走此机制；**例外：regulation 走独立 `storage.py`**
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
- makemigrations 必须指定 app 名；CharField/TextField 禁止 null=True

## 幂等性设计
- `libs/idempotency.py`：`check_recent_duplicate(model, filters, window_seconds=30)` —— 已含 `is_deleted=False` 过滤
- 已加 dedup 的模块：fault, interference, contract_agreement, department_duty_log, regulation, home/navigation, home/notice + signature（request_id 标杆）
- **未加 dedup 的模块（2026-08-01 发现）**：upgrade, device, radio_license
- 测试：`apps/idempotency_risk_tests.py`

## 审计修复记录（2026-08-01 批量）
- **regulation**：7 项修复（R1-R9），15/15 PASS
- **evidence**：4 项修复（R4/R8/R5/R7），报告 `EVIDENCE_CRUD_AUDIT_REPORT.md`
- **document**：第一轮 10 项修复（R1-R10）；第二轮 N1-N8 9 项已验证待修复，报告 `DOCUMENT_AUDIT_REPORT.md`
- **interference**：11 项修复，报告 `INTERFERENCE_CRUD_AUDIT_REPORT.md`
- **logs**：7 项确认风险（R1-R11），报告 `LOGS_AUDIT_REPORT.md`
- **home/navigation+notice**：22 项修复（事务+行锁+审计+update_fields+try/except+is_deleted过滤），18/18 PASS
- **upgrade**：19 项修复（TenantModelManager 根治 is_deleted 泄漏 + replace 软删除 + 日期边界 + 事务 + update_fields），19/19 PASS
- **department_duty_log**：8+5 项修复（CheckConstraint + 竞态 + 幂等 + CharField 约束 + 列表全量 + 签署幂等），114/114 PASS
- **radio_license + contract_agreement**：8 项风险确认，5 项已修复（R-CA-3 + R-AP-1~4），28/28 PASS
  - P0→FIXED: 批复 create/edit scan+audit 移入事务内
  - P1→FIXED: 批复 delete/ack audit 移入事务内；合同 save() 加 update_fields
  - P2(降级): 合同编辑 responsible_user 未验证（UI 不暴露，仅 API 硬化建议）

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
