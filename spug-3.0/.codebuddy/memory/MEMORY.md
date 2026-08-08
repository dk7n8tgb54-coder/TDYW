# 项目记忆

## Playwright E2E 测试（2026-08-08）
- 位置：`quality/e2e/`，独立 package.json + @playwright/test 1.62.1
- 109 条测试覆盖 7 域 20 模块，Chromium 131，全部通过
- 前端用 `createBrowserHistory()`，路由路径 `/home`（非 `/#/home`）
- antd Button 中文有空格：`getByRole('button', { name: /登\s*录/ })`
- 登录 API：POST `/api/account/login/` JSON `{username, password, type:"default"}`
- Token 存 sessionStorage `token`，请求头 `X-Token`
- `page.addInitScript()` 注入 sessionStorage 可免 UI 登录
- 未认证访问受保护路由：渲染空 Layout，不重定向（设计选择非缺陷）
- E2E 测试用户：admin/E2E@Test2026! + e2e_tester/E2E@Test2026!
- 报告：`quality/reports/e2e/`

## 全系统盘点（2026-08-07/08）
- 20 app/45 模型/150+ API/97 权限/45 风险/10 WP。输出 `outputs/system_inventory/`
- 过期测试清理：删除 74 个一次性审计脚本。实际测试~99个（28根级+27 apps+25 Jest+~20 Locust）
- 大部分 app 仅单个 tests.py 冒烟测试，综合测试在 `spug_api/tests/` 根级

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- `tdyw-test` 容器（镜像 tdyw:django42-stage2）**有 bind mount**；连 dev 库；验证用此容器
- ⚠️ 改完后端代码后必须重启容器才能生效。重启：`wsl bash -c 'docker restart tdyw-test'`
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx）
- ⚠️ Docker 内网回调：kkFileView 经 `http://tdyw` 回源，容器名须进 ALLOWED_HOSTS

## 数据库配置
- `ATOMIC_REQUESTS=True`；`CONN_MAX_AGE=0`；MariaDB 10.8.2；`sql_mode=STRICT_TRANS_TABLES,...`

## 测试要点
- 运行：`docker exec ... tdyw python manage.py test apps.xxx.tests --noinput`
- ⚠️ Django test runner 创建 test_spug 失败（迁移顺序问题）：用手动创建 test_spug 或 `--keepdb`；或直接写独立脚本用 dev 库跑
- access_token 32 字符；Role.created_by NOT NULL；User.tenant_id 默认 'admin'；make_user 设 version=0
- json_response 错误时 data=''；update_by_dict 过滤 None；USE_TZ=False 禁 make_aware
- test client 路径无 `/api/` 前缀；makemigrations 指定 app

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration；3. 唯一约束拆步；4. CharField->Date 先洗空串
5. MariaDB 不支持部分唯一索引；逻辑删除唯一约束冲突用 `__deleted_{id}` 后缀
6. 改 default_auto_field 触发所有老表 alter id；7. MariaDB alter 被外键引用主键列报错 1833 -> `SET FOREIGN_KEY_CHECKS=0`
8. **CharField/TextField 禁止 null=True**

## 模块架构速查
- 数据分析 `apps/data_analysis`（纯只读聚合，无 model/migration）
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token）
  - radio_license/contract_agreement/device/upgrade/fault/interference/department_duty_log 走此机制
  - **例外：regulation 走独立 `storage.py` + RegulationAttachment**
  - 附件新建阶段上传模式：前端生成临时 UUID 作为 `object_id`，后端 `pk.isdigit()` 判断跳过记录存在性校验
- 账号签名 `apps/signature`（apply_signature 事务锁->SHA256->Usage+EvidenceEvent）
- 党建隔离 `DocumentSystemFolder` + `system_scope_validators`（fail-closed）
- 权限缓存 `User.page_perms` Redis `perms_{id}`=(version,perms)
- kkFileView `KKFILEVIEW_API_URL`(浏览器)/`KKFILEVIEW_SERVER_URL`(回源)
- preview_token **两套独立实现**（document/libs vs evidence/attachment_preview_token）待收口

## Celery
- 18 `@shared_task` / 5 队列；12 Beat + 6 事件触发
- `retry_clean_pending_files` 是 `is_pending_clean` 唯一消费者，不可删
- `check_weekly_report_reminders` 每 5 分钟轮询，10 分钟时间窗口 + get_or_create 幂等

## 公共组件
- `libs/pagination.py`: `paginate(request)` + `paginate_response()`
- `libs/tenant_utils.py`: `apply_tenant_filter(qs, user)` 多租户隔离
- `libs/alert.py`: `send_alert()` 统一告警
- `apps/logs/audit.py`: `record_audit_event()` 审计日志
- `libs/idempotency.py`: `check_recent_duplicate(model, filters, window_seconds=30)` -- 已含 `is_deleted=False` 过滤

## 幂等性设计
- 已加 dedup：fault, interference, contract_agreement, department_duty_log, regulation, home/navigation, home/notice + signature
- **未加 dedup**：upgrade, device, radio_license

## 审计修复记录（2026-08-01 批量）
- regulation 7 项(15/15) / evidence 4 项 / document 10+9 项 / interference 11 项 / logs 7 项
- home/navigation+notice 22 项(18/18) / upgrade 19 项(19/19) / department_duty_log 13 项(114/114)
- radio_license + contract_agreement 5 项已修复(28/28)

## 反思清单（跨会话必遵）
1. 反问质疑立即认错不掩盖；2. 增量>大爆炸+YAGNI+向后兼容；3. 配置化>硬编码(同串≥3处抽出)
4. 参考成熟产品+行业惯例；5. 每次修复后全局扫描同类；6. error 字段一致性(正常态无 error)
7. `obj?.method()` 触发 no-unused-expressions->`if(obj)obj.method()`；8. Model.save 签名 `def save(self,*args,**kwargs)`
9. 嵌套 atomic 仅 savepoint；10. 备份恢复同周期(DB->documents)

## CRUD 可靠性编码规范（摘要）
- NOT NULL/UNIQUE/CHECK/FK 必须在 DB 层强制
- 所有多步写操作必须 `transaction.atomic()` 包裹
- 核心写操作设计幂等键；核心业务表用逻辑删除
- **DateTimeField 禁用 `__date`/`__year`/`__month`/`__startswith`/`__icontains`**，改用 `__gte`/`__lt`
- `LIKE '%xxx'` 前缀通配无法走索引；复合索引遵循最左前缀

## 租户隔离审计与修复（2026-08-08/09）
- **TenantModelManager 只过滤 is_deleted，不自动过滤 tenant_id** -> Views 须手动调 apply_tenant_filter 或添加 Q(tenant_id=...)
- **WP5 修复（2026-08-08/09）**: NavView 完全删除（死代码：前端未 import + DB 0 条数据）；NoticeView 已删除（NOT_APPLICABLE）；ReminderUsersView 跨租户返回所有科室用户是**刻意设计**（科室A可提醒科室B/C提交材料），不修改
- **Navigation 功能已完全移除**: navigation.py 删除、Navigation 模型删除（migration 0011）、Nav.js/NavForm.js 删除、urls.py 移除路由
- **CRITICAL 漏洞（已修复）**: NavView + NoticeView 完全无 apply_tenant_filter
- **JsonParser 默认 type=str**: 列表传给无 type=list 的 Argument 会被 str() 转为单引号字符串，导致 json.loads() 失败
- **_validate_reminder_form 预存在 bug**: 返回 (None, error_str) 时解包 TypeError（非本任务引入）
- **Client() 测试**: 需设 ALLOWED_HOSTS += ['testserver']；Django test runner 可成功创建 test_spug
- 超管(is_supper=True)绕过所有租户过滤(已知设计)
- Test Client 需设 HTTP_X_REAL_IP header + ALLOWED_HOSTS=['*']

## 历史项目
- 资料库回收站功能已于 2026-06-23 完全移除（模型层保留 is_deleted/deleted_at 字段避免 migration）
- 资料库传输列表：3 Tab + 抽屉模式（参考阿里云盘/百度网盘）
- Babel 验证脚本：`node --check` 不支持 ESM，需 `@babel/core` + decorators + class-properties 插件
- 秒传/跨 transfer 哈希复用已于 2026-08-07 移除。保留断点续传

## 日常业务特征测试（2026-08-08）
- 5 模块 279 项测试全部通过（7 个 expectedFailure 标记生产缺陷）
- 测试文件在各模块 `tests/characterization/` 目录下
- 报告在 `quality/reports/daily_business/`
- **3 个生产缺陷**：DUTY-001(duty edit timezone P0)、RUNLOG-001(runlog closed datetime序列化 P0)、RUNLOG-002(runlog update duty_person NOT NULL P1)
- **测试数据库初始化**：Django test runner 因迁移顺序失败，改用从 spug 克隆表结构+django_migrations 记录
- **关键要点**：_make_record 须设 tenant_id；软删除后须用 all_with_deleted()；日期格式须 19 字符；SignatureUsage 须先创建

## 租户隔离审计（2026-08-08）
- 测试代码: `quality/tenant_isolation/`，报告: `quality/reports/tenant_isolation/`
- **TenantModelManager 只过滤 is_deleted，不自动过滤 tenant_id** → Views 须手动调 apply_tenant_filter
- **CRITICAL 漏洞**: NavView + NoticeView 完全无 apply_tenant_filter（列表/修改/删除均可跨租户）
- **HIGH 漏洞**: ReminderUsersView 泄露全部租户用户列表
- 正确隔离: reminder(CRUD)/runlog/fault/account/dashboard 均有效
- 全局数据(无tenant_id): Regulation/Setting/Alert/AlertRead/DocumentSystemFolder/AuditLogSequence
- 超管(is_supper=True)绕过所有租户过滤(已知设计)
- Test Client 需设 HTTP_X_REAL_IP header + ALLOWED_HOSTS=['*']

## 上传链审计结论（2026-08-05）
- **P0**：`ALLOWED_STATUS_TRANSITIONS` 缺失 `UPLOADING->COMPLETED`；XHR 回调未检查 `operationVersion`
- **P1**：`mergeChunks` 递归重试无深度限制
- **已修复**：DirectMergeView COMPLETED 分支增加文件记录验证

## 排班模块残留审计（2026-08-07）
- 删除提交 `93e81301`，后端 24 .py + 前端 23 .js
- **无活跃残留**：INSTALLED_APPS/urls.py/权限码/模型类均无引用

## 数据库结构与数据质量审计（2026-08-08）
- 审计工具: `quality/database_audit/`（audit_database.py + database_rules.yml + model_exceptions.yml）
- 审计报告: `quality/reports/database_audit/`（报告 + 7 个 CSV + coverage_gaps.md）
- 数据库环境: dev 库（tdyw-test 容器，MariaDB 10.8，InnoDB，72 表/216 迁移/268 权限/67 CT）
- **无严重风险**；**高 3 项**：6 表缺 tenant_id 索引、fault_date__icontains、nav/notices 全软删未清空
- **中 5 项**：8 处 CharField null=True、9 表缺 is_deleted 索引、9 处重复索引、Role.tenant_id 语义、ReminderLog 间接隔离
- schedule 模块数据库残留: **零**（表/迁移/权限/CT 均无残留）
- 孤儿数据: **0 条**；is_pending_clean: **0 条**
- DateTimeField 查询: 仅 `fault/exporters.py:91` 违规（__icontains on date）
- raw SQL: 仅 logs/middleware.py（参数化安全）+ alert/views.py（SHOW STATUS 安全）
- Docker shell 执行脚本: `cat script.py | docker exec -i ... tdyw-test python manage.py shell`（避免引号嵌套）

## ⚠️ 永久教训
- `manage.py flush` 会清空所有数据，绝对禁止在 dev/prod 容器执行
- tdyw-test 容器连的是 dev 库（不是独立测试库），flush/migrate/delete 都会影响 dev 数据
