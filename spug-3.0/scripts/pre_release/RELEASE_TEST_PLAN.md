# Spug 发布前全量测试方案

> 目标：在项目首次上线前，系统性验证"开发环境正常但生产可能出问题"的所有风险点。
>
> 创建日期：2026-07-19
> 项目：TDYW/spug-3.0
> 生产服务器 IP：192.168.40.118

## 项目测试现状

| 维度 | 现状 | 风险 |
|---|---|---|
| 业务 app | 22 个 | - |
| 有后端单元测试的 app | 9 个（department_duty_log / radio_license / regulation / signature×2 / logs / setting / account / checksheet） | 🟢 良好 |
| 无后端测试的 app | 13 个（其中 7 个有基础冒烟模板：contract_agreement / device / duty / home / runlog / upgrade / fault；6 个完全无：document / evidence / exec / schedule / safety_question_bank / 其他无 HTTP 入口） | 🟡 中 |
| 前端测试 | 17 个文件，全集中在 document/stores/upload/ | 🟡 中 |
| CI/CD | 无（仅 git→gitee 镜像） | 🟡 中 |
| 数据库迁移 | 全部已应用，makemigrations --check 无变更 | 🟢 良好 |
| 压测脚本 | 11 个 locustfile | 🟢 良好 |

## 测试方案（7 阶段，按优先级）

### 🔴 阶段 1：环境与配置审计 ✅ 已完成

**目标**：检查"开发环境正常但生产可能炸"的配置差异。

**自动化审计脚本**：`scripts/pre_release/audit_config.py`
```bash
wsl bash -c "docker exec -i tdyw python - < scripts/pre_release/audit_config.py"
```

**手工审计手册**：`scripts/pre_release/CONFIG_AUDIT_CHECKLIST.md`

**审计结果**（2026-07-19）：
- ✅ 62 PASS / ⚠️ 5 WARN / 0 FAIL / 26 INFO
- 已修复：`ALLOWED_HOSTS` 从 `*` 改为 `192.168.40.118,localhost,127.0.0.1`
- 已修复：`ALLOWED_ORIGINS` 从未设置改为 `https://192.168.40.118,http://localhost,http://127.0.0.1`
- 已修复：`docker-compose.yml` 中 `ALLOWED_HOSTS` 硬编码 `*` 改为引用 `.env`
- 剩余 5 个 WARN 全部可忽略（Celery 时区/STATIC_ROOT/TRANSFER_DIR/REDIS_HOST/REDIS_PORT）

**覆盖范围**（11 大类）：
1. Django 安全配置（DEBUG/SECRET_KEY/ALLOWED_HOSTS/USE_TZ/TIME_ZONE）
2. 数据库（连通性/MySQL 版本/max_connections/buffer_pool/sql_mode/slow_query_log）
3. Redis（DB0 channels / DB1 cache / DB2 broker / DB3 result）
4. Celery（Worker ping / Beat schedule）
5. 文件系统（MEDIA_ROOT/STATIC_ROOT/TRANSFER_DIR/logs/storage）
6. 数据库迁移（未应用迁移 / 模型-迁移一致性）
7. 业务模块（19 个 app 是否全注册）
8. 关键文件（nginx.conf/SSL 证书/supervisord.conf/start-*.sh/build/index.html）
9. Supervisor 进程（13 个进程是否 RUNNING）
10. 环境变量（11 个必需变量）
11. Docker Volume（named volume 陷阱提醒）

---

### 🔴 阶段 2：fresh 库全量迁移演练

**目标**：验证从空数据库能完整建起来——这是开发环境永远不会暴露的问题。

**步骤**：
1. 起一个空数据库容器
2. 跑 `migrate` 全流程
3. 确认从零能建起来
4. 对关键 migration 做回滚测试（`migrate app 000X` 回滚再前进）

**重点检查**：
- `unique_key` 字段、`is_deleted` 软删除、`tenant_id` 隔离的索引
- MariaDB 10.8.2 不支持部分唯一索引，`is_deleted=True` 时 `unique_key` 设 NULL
- CharField→Date/DateTimeField 迁移必须先清洗空串

---

### 🔴 阶段 3：已有自动化测试全跑

**目标**：保证现有 9 个 app 后端测试 + 17 个前端 jest 测试全绿。

**后端测试**（437 tests 全绿）：
```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
  python manage.py test \
  apps.department_duty_log.tests \
  apps.radio_license.tests \
  apps.regulation.tests \
  apps.signature.tests.test_signature \
  apps.signature.tests.test_signature_usage \
  apps.logs.tests \
  apps.setting.tests \
  apps.account.tests \
  apps.checksheet.tests \
  --noinput -v 1
```

**2026-07-20 新增测试**（187 tests）：
- `apps/logs/tests.py`（37 tests）：审计日志查询/筛选/分页/租户隔离/导出/哈希链/工具函数
- `apps/setting/tests.py`（26 tests）：系统设置/个人设置/MFA/email_test/about/AppSetting 工具
- `apps/account/tests.py`（87 tests）：登录/登出/锁定/用户CRUD/角色CRUD/可分配角色边界/租户CRUD/个人设置/role_permissions 工具
- `apps/checksheet/tests.py`（37 tests）：模板CRUD/记录查询保存/提交批次状态流转/PDF导出权限/证据包导出/状态机模型

**顺手修复的生产 bug**：
- `apps/logs/views.py`：`timezone.make_aware()` 在 `USE_TZ=False` 下会抛 `ValueError: MySQL backend does not support timezone-aware datetimes`。审计日志时间范围筛选（start_time/end_time）会 500。修复：直接用 naive datetime（4 处，AuditLogView + AuditLogExportView）。

**前端测试**：
```bash
cd spug_web && npx react-app-rewired test --watchAll=false
```

**测试隔离纪律**：
- 测试必须 `@override_settings(MEDIA_ROOT=tempfile.mkdtemp())` 隔离文件系统
- 测试必须 `@override_settings(CACHES=...)` 或 setUp/tearDown `cache.clear()` 隔离 Redis
- 跑测试前确认 tearDown 不动生产文件/Redis
- `manage.py test` 用 INSTALLED_APPS 注册路径（apps.xxx.tests）
- test_spug 已存在时加 --noinput

---

### 🟡 阶段 4：关键路径手工冒烟测试

**目标**：覆盖无单元测试的 17 个 app 的核心流程。

**17 个无测试 app 清单**：
account / checksheet / contract_agreement / device / document / duty / evidence / exec / fault / home / interference / logs / runlog / safety_question_bank / schedule / setting / upgrade

**每个模块最少验证**：
- 列表 / 新建 / 编辑 / 删除
- 权限码
- 租户隔离（多租户数据不串）

**关键模块必测路径**：
| 模块 | 必测路径 |
|---|---|
| account | 登录/登出/角色 CRUD/权限分配/可分配角色边界 |
| document | 文件夹 CRUD/拖拽上传/分片上传/秒传/合并/预览/搜索/党建隔离 |
| evidence | 附件上传/预览令牌/多态查询 |
| upgrade | 升级计划 CRUD/状态流转/步骤/附件 |
| checksheet | 检查单 CRUD/导出 |
| device | 设备 CRUD/履历 |
| home | 公告/统计概览 |
| logs | 审计日志/哈希 |
| runlog | 运行日志 CRUD/事件类型/统计 |

---

### 🟡 阶段 5：跨模块集成测试

**目标**：验证真实业务流的全链路。

**测试场景**：
1. 登录 → 上传文件 → 关联到业务对象 → 签署 → 审计日志记录
2. 多租户场景：建 2 个租户、各建用户/数据，确认完全隔离
3. 党建 vs 普通文档隔离
4. 权限缓存失效：超管改角色权限 → 普通用户立即生效
5. Celery 任务：到期提醒（执照/批复）、文档清理、定时任务 beat 触发
6. kkFileView 预览：doc/xlsx/pdf/img 各上传一份

---

### 🟡 阶段 6：性能与压力测试

**目标**：覆盖 22 个业务模块的核心性能场景 + 基础设施瓶颈 + 长时间稳定性。

**覆盖度盘点**（2026-07-20 重新审计）：
- 业务模块覆盖：9/22（41%），高风险模块（PDF 导出/审计日志/预览）已补
- 关键场景覆盖：17/20（85%），仅缺 N+1 专项扫描/冷启动/spike test
- 基础设施覆盖：通过混合负载 + soak test 间接覆盖

**SLA 阈值**：见 `locustfile/SLA_THRESHOLDS.md`（通用阈值 + 分场景阈值 + 监控命令 + 报告模板）

**统一 runner**：`locustfile/run_all_locust.sh`
```bash
./locustfile/run_all_locust.sh --list          # 列出所有脚本
./locustfile/run_all_locust.sh                 # 跑上线前必补（9 个）
./locustfile/run_all_locust.sh --all           # 跑全部（14 个，含上线后可补）
./locustfile/run_all_locust.sh --only pdf_export  # 只跑指定脚本
```

**🔴 上线前必补脚本（9 个）**：
| 脚本 | 场景 | 风险 | 默认并发 |
|---|---|---|---|
| `account_login_stress.py` | 登录并发 | PBKDF2 hash CPU | 50 |
| `document_stress.py` | 资料 CRUD + 分片上传 | 主脚本，文件夹/文件/分片/合并 | 30 |
| `locustfile_document.py` | 高并发 + 锁竞争 | 同名合并/分片锁 | 20 |
| `locustfile_folder_depth.py` | 文件夹深度嵌套 | 递归性能/深度限制 | 15 |
| `locustfile_pdf_export.py` | PDF 导出并发 | **8G 服务器最易 OOM** | 10 |
| `locustfile_download.py` | 大文件下载 | 带宽/Gunicorn worker 占满 | 30 |
| `locustfile_kkfileview_preview.py` | kkFileView 预览 | **LibreOffice OOM** | 15 |
| `locustfile_audit_log.py` | 审计日志 | 哈希链 O(n)/深页 OFFSET | 20 |
| `locustfile_mixed_workload.py` | 混合负载（早高峰） | 资源争用/DB 连接池 | 50 |

**🟡 上线后可补脚本（5 个）**：
| 脚本 | 场景 | 风险 | 默认并发 |
|---|---|---|---|
| `locustfile_multi_tenant.py` | 多租户并发 | tenant_id 索引效率 | 40 |
| `locustfile_permission_cache.py` | 权限缓存击穿 | Redis 失效风暴 | 30 |
| `locustfile_celery_queue.py` | Celery 队列积压 | merge 超时/pack 堆积 | 20 |
| `locustfile_websocket.py` | WebSocket 推送 | Channels 连接上限 | 50 |
| `locustfile_soak_test.py` | 8h+ 长时间稳定性 | 内存/连接/磁盘泄漏 | 20 |

**已有但未列入 runner 的旧脚本**（保留备用）：
| 脚本 | 说明 |
|---|---|
| `locustfile_device.py` | 设备 CRUD（与 mixed_workload 重叠，可按需单独跑） |
| `locustfile_interference.py` | 干扰记录 CRUD（同上） |
| `locustfile_runlog.py` | 运行日志 CRUD（同上） |
| `locustfile_pagination.py` | 通用分页（与 audit_log 深页重叠） |

**关注指标**（详见 SLA_THRESHOLDS.md）：
- 8G 服务器下 MySQL 连接数上限 300（留 20% 余量，实际 < 240）
- 主容器内存 2G（实际 < 1.8G）
- kkFileView 1.5G（实际 < 1.35G）
- 失败率 < 0.1%，HTTP 500 率 = 0
- 压测时开 MySQL slow query log，找 N+1

**已清理的旧脚本**（2026-07-20）：
- ❌ `document_stress_test.py`（v1，含已删除的回收站接口）
- ❌ `document_stress_test_v2.py`（v2，含回收站）
- ❌ `document_stress_test_v3.py`（v3，字段 bug，场景已被 document_stress.py 覆盖）

---

### 🟢 阶段 7：部署演练与回滚预案

**目标**：验证 fresh 镜像构建 + 数据备份恢复 + 回滚预案。

**步骤**：
1. fresh 镜像构建：`docker build -t tdyw:test -f docker/Dockerfile .`
2. 容器拉起：`docker-compose up -d` 三个容器全部 healthy
3. healthcheck 通过：`curl https://localhost/api/document/health/`
4. 首屏加载：浏览器访问能看到登录页
5. 登录测试：admin / Admin888.. 能登录
6. 数据备份演练：`database_maintenance/` 下脚本跑通
7. 恢复演练：用备份恢复到新容器，确认数据完整
8. 回滚预案文档：写"出问题怎么回滚"的 runbook

**named volume 陷阱复查**：
- `tdyw-media` / `tdyw-documents` / `tdyw-document-chunks` 是 named volume
- 切换 compose 项目名或重建 volume 即丢失
- 生产部署前确认数据备份策略

---

## 执行进度跟踪

| 阶段 | 状态 | 完成日期 | 结果 |
|---|---|---|---|
| 1. 环境与配置审计 | ✅ 完成 | 2026-07-19 | 62 PASS / 5 WARN / 0 FAIL |
| 2. fresh 库迁移演练 | ✅ 完成 | 2026-07-20 | 133 条 migration 全部应用，54 张业务表创建成功，回滚测试通过 |
| 3. 已有测试全跑 | ✅ 完成 | 2026-07-20 | 后端 465 tests 全绿（17 app），前端 282 tests 全绿 |
| 4. 手工冒烟测试 | ⏳ 待做 | - | - |
| 5. 跨模块集成测试 | ✅ 完成 | 2026-07-20 | 24/24 集成测试全通过（多租户/权限缓存/哈希链/登录/部分字段编辑） |
| 6. 性能压测 | 🟡 脚本就绪 | 2026-07-20 | 14 个脚本(9 必补+5 可补)+ SLA 阈值 + 统一 runner,待执行 |
| 7. 部署/回滚演练 | ⏳ 待做 | - | - |

## 判定标准

| 等级 | 含义 | 处理方式 |
|---|---|---|
| PASS | 通过 | 无需处理 |
| WARN | 警告 | 评估后决定是否处理，可上线 |
| FAIL | 失败 | **必须处理**，否则不可上线 |
| INFO | 信息 | 仅供参考 |
