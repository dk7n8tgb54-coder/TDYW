# 边界测试用例集（八类边界）

> 适用范围：spug-3.0 全部正式业务模块的 HTTP API 层。
> 编制依据：`spug_api/libs/` 公共层的实际行为（文中标注 file:line）+ `AGENTS.md` 全局契约 + 2026-09-20 的既有测试覆盖调查。
> 用法：每条用例给出目标、输入构造、期望结果与断言要点。标注【既有】的表示现有测试已覆盖（附引用，可直接复用断言风格），标注【新增】的表示缺口，按"建议落点"实现。同名前缀用例实现时应做成参数化模板，逐模块实例化，而不是复制粘贴。

---

## 0. 全局响应契约（所有用例的断言基线）

| 场景 | 契约 | 依据 |
|---|---|---|
| 未认证 | HTTP 401 + `{"error": "验证失败，请重新登录"}` | `libs/middleware.py:241-242` |
| 已登录、无权限 | HTTP 200 + `{"error": "权限拒绝"}` | `libs/decorators.py:28` |
| 业务校验失败 | HTTP 200 + `{"error": "<具体文案>"}`，不落库 | AGENTS.md 第九节 |
| 未捕获异常 | DEBUG=False 时 HTTP 200 + `{"error": "服务器内部错误，请联系管理员"}`；error 日志含 request_id 并触发告警 | `libs/middleware.py:93-130` |
| 分页参数 | page 钳制 ≥1，page_size 钳制 [1,200]，非法值回退默认 | `libs/pagination.py:27-35` |
| 幂等预检 | `check_recent_duplicate` 30 秒时间窗，自动排除软删记录 | `libs/idempotency.py:27-48` |

每条用例除响应断言外，按需追加四类副作用断言：

1. 数据库行数/字段状态（不能只看 HTTP 响应，AGENTS.md 六.4）；
2. 物理文件无孤儿（附件/文档类操作）；
3. 审计日志留痕恰一次；
4. 业务错误计数（`apps/alert/metrics.py` 的 record_business_error）被正确累计。

**执行环境**：后端用例一律在 tdyw-test 容器 + test_spug 库（`--keepdb`）执行。并发类用例必须继承 `TransactionTestCase`——`TestCase` 的事务包裹会让其他线程看不到未提交数据，`threading.Barrier` 先例见 `apps/department_duty_log/tests/test_signed_date_uniqueness.py:408-433`。数据库断连类 L3 演练只允许指向测试环境，禁止生产（AGENTS.md 质量工程约束 3/4/10）。

---

## 1. 空值（BC-NULL）

**目标**：必填缺失、显式 null、空串、纯空白、空数组、数组内 null、嵌套结构 null 均不产生 500、不落脏数据。
**输入矩阵**（对任一创建/编辑端点依次代入）：缺 key / `"x": null` / `"x": ""` / `"x": "   "` / `"x": []` / `"x": [null]` / 嵌套对象字段 null。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-NULL-01 | 必填字段整体缺失：对代表端点 POST 不带该 key（如 runlog 缺 event_title、contract 缺 name、radio_license 缺各 required 项） | 200 + error（"请输入…"类文案）；目标表 count 不变 | 【既有】contract `stable_contract/test_crud.py:33`、runlog `characterization/test_runlog.py:167-202` | 已覆盖，新增模块照此模板 |
| BC-NULL-02 | 显式 null：`"event_title": null` | 与缺失等价被拒；不得 TypeError 500（验证 JsonParser/required dict 对 None 的处理） | 【新增】 | 各 app `tests/` |
| BC-NULL-03 | 纯空白：`"title": "   "` | 视为空拒绝；入库字段不出现空白串 | 【既有先例】coop_task `test_coop_task_validation.py`（空白标题），扩展 runlog/reminder/regulation | 各 app `tests/` |
| BC-NULL-04 | 可选字段显式 null 与省略两种请求 | 落库结果完全一致；不产生字符串 `'None'` 入库 | 【新增】 | 各 app `tests/` |
| BC-NULL-05 | 嵌套结构空值：`POST /systems/` 传 `template_values: null`、`custom_fields: null`、`components: null`、`components: [null]`（equipment_lifecycle 结构化载荷） | 按现有契约拒绝或按空集处理，绝不 500、不产生半写 | 【新增】 | `apps/equipment_lifecycle/tests/` |
| BC-NULL-06 | 列表接口过滤参数空值：`?status=&keyword=` | 视为不过滤；不产生 `LIKE '%%'` 全表慢查（MariaDB 前缀通配无法走索引） | 【新增】 | 各 app `tests/` 或 `quality/database_audit/` |
| BC-NULL-07 | 附件字段空值：不传 attachments / `attachments: null` / 附件 id 为 null | 创建成功且 `EvidenceAttachment` 计数不变、无孤儿文件 | 【新增】 | 调用方业务 app `tests/`（AGENTS.md 测试落点规则） |
| BC-NULL-08 | PUT 半更新：只传部分字段 | 未传字段保持原值，不被静默清空/置 null（对齐 device PUT 不收位置字段的既有约定） | 【新增】 | 各 app `tests/` |

---

## 2. 超长字符串（BC-LEN）

**目标**：超长输入一律业务错误或统一兜底，绝不 500 裸异常、不暴露数据库错误码、不半写。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-LEN-01 | max_length 边界三连：N-1 / N / N+1（如 department_duty_log 备注 2000/2001） | N 及以内合法落库且回读一致；N+1 拒绝 | 【既有先例】`test_department_duty_log_validation.py:141`；固化为此标准模板 | 各 app `tests/` |
| BC-LEN-02 | 1MB 超大文本塞入普通 CharField/TextField | 200 + 业务 error 或中间件兜底 error；不暴露 DataError/数据库错误码；不落库 | 【既有】contract `stable_contract/test_crud.py:72-98` | 已覆盖，新增模块照此模板 |
| BC-LEN-03 | 特殊字符：emoji（4 字节 😀）、生僻字、零宽字符 U+200B、控制字符 `\x00`/`\x1f`、换行 | utf8mb4 下合法字符可存可回读；`\x00` 等非法字符被业务层拒绝而非 500；记录零宽字符是否 strip 的现状契约 | 【新增】 | 各 app `tests/` |
| BC-LEN-04 | 超长数字/ID：`id='1'*10000`、`page_size='9'*10` | int 解析路径不 ValueError 500（分页已钳制；其余 int 字段需视图 try/except） | 【新增】 | 各 app `tests/` |
| BC-LEN-05 | 超长数组：components 一万项、附件 id 列表一万个 | 校验拒绝或处理时间可控；不 500、不半写（不断言具体阈值，断言行为） | 【新增】 | `apps/equipment_lifecycle/tests/` 等 |
| BC-LEN-06 | 文件名超长：file_name 300 字；附件原始名接近 255 且重传 " (1)" 后缀越界 | 拒绝且物理目录无残留文件 | 【既有】document `test_upload_merge.py:343-344`；重传后缀膨胀场景【新增】 | `apps/document/tests/` |
| BC-LEN-07 | 注入形态长串：单引号/分号/`%`/`_`/`' OR '1'='1` | ORM 参数化下按普通文本处理；`LIKE '%_%'` 通配不崩溃不绕过过滤 | 【新增】 | 各 app `tests/` |

---

## 3. 负数（BC-NEG）

> **前置事实**：合同费用 `fee_amount` 已文本化（CharField 200），"-100元调整款"是**合法输入**——勿对费用字段设计"负数应拒绝"用例，见 `stable_contract/test_fee_text.py:243-250`。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-NEG-01 | 分页负值/非法值：`page=-1`、`page=0`、`page=abc` | 走统一分页钳制返回 page=1（`libs/pagination.py:27-30`）；自校验视图返回 error；均不 500 | 【既有】coop_task `test_coop_task_fault_tolerance.py:413-418`、dutylog `..._fault_tolerance.py:53`；其余列表端点抽查【新增】 | 各 app `tests/` |
| BC-NEG-02 | 路径/查询 ID 负数：GET/PUT/DELETE `id=-1` | 200 + 业务错误（不存在）；不 500；响应与他租户存在 id 不可区分 | 【新增】 | 各 app `tests/` |
| BC-NEG-03 | 数值业务字段负值：值班人数、时长、提醒提前天数、coop_task 配额等 | 按字段契约拒绝（负数不合理）或接受并 round-trip 一致（存取回读相等）；二选一必须明确 | 【新增】（数值字段负数覆盖薄，是主要增量空间） | 各 app `tests/` |
| BC-NEG-04 | 日期区间倒挂：start > end（值班日期、合同期限、提醒时间） | 业务校验错误；有 DB 约束的（如 contract_validity_consistent）断言约束兜底 | 【部分既有】contract 约束；其余模块【新增】 | 各 app `tests/` |
| BC-NEG-05 | 超大数值溢出：2147483648（int32 上限+1）、1e30 | 按字段类型上限处理；不 500、不静默截断为错误值 | 【新增】 | 各 app `tests/` |
| BC-NEG-06 | 文本化金额字段：`fee_amount = "-100元调整款"` 保存；纯 `-`、`元` 无数字文本 | 负号文本合法可存可回显；无数字文本被 `contract_fee_content_valid` 约束拒绝 | 【既有】`test_fee_text.py` | 已覆盖 |
| BC-NEG-07 | 统计接口负参数：data_analysis 传负天数/负区间 | 钳制或拒绝；不产生异常 SQL；Redis 缓存键不被污染 | 【新增】 | `apps/data_analysis/tests/` |

---

## 4. 重复提交（BC-DUP）

**机制盘点**：① 全局时间窗 `check_recent_duplicate(model, filters, window_seconds=30)`（`libs/idempotency.py:27-48`）；② equipment_lifecycle 专用 `client_token`（tenant_id+client_token 复合唯一索引，命中返回既有记录，`ledger_services.py:473-510`，超 64 字符截断 `:369`）；③ department_duty_log 签署用 request_id。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-DUP-01 | 同参数 30 秒内两次 POST | 第二次 error（"操作过于频繁…"类）；count=1 | 【既有】contract `test_crud.py:226-233` | 已覆盖，新增模块照此模板 |
| BC-DUP-02 | 窗口边缘：mock 时间或注入 window_seconds，第 31 秒重放 | 允许创建（窗口语义）；用时间注入保证确定性，不靠 sleep（防 flaky） | 【新增】 | 各 app `tests/` |
| BC-DUP-03 | 同窗口内**不同**业务参数两次 POST | 都成功（防幂等误伤正常业务） | 【新增】 | 各 app `tests/` |
| BC-DUP-04 | 相同 client_token 两次 POST（台账/工单/系统事件） | 返回同一条记录 id；count=1 | 【既有】equipment_lifecycle `stable_contract/`（ledger_base.py:143 构造） | 已覆盖 |
| BC-DUP-05 | 跨租户 client_token：租户 B 重放租户 A 的 client_token | 不命中 A 的记录，B 正常创建自己的（复合唯一索引含 tenant_id 的语义验证） | 【新增】 | `quality/tenant_isolation/` 或 `apps/equipment_lifecycle/tests/` |
| BC-DUP-06 | 软删后重提：30 秒窗口内删除记录后再提交同参数 | `check_recent_duplicate` 排除软删 → 允许重建，产生新记录（`idempotency.py:44-47` 语义固化） | 【新增】 | 各 app `tests/` |
| BC-DUP-07 | 状态机幂等：已验收再提交、已签署再签署、ack 重复确认 | 返回既有结果或明确业务错误；不产生第二条记录/第二条审计 | 【既有】coop_task `:355-371`、dutylog `:246-255`、contract `test_status_reminder.py:158` | 已覆盖 |
| BC-DUP-08 | 畸形 client_token：65+ 字符、空串、非字符串类型 | 契约固化：64 与 64+1 字符是否视为同一 token（截断语义 `ledger_services.py:369`）；畸形值拒绝且不 500 | 【新增】 | `apps/equipment_lifecycle/tests/` |

---

## 5. 并发提交（BC-CONC）

**先例两种**：真实线程 `threading.Barrier`（dutylog `test_signed_date_uniqueness.py:408-433`）与事务内检查点注入（coop_task `test_coop_task_concurrency.py:52-150`）。均需 `TransactionTestCase`。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-CONC-01 | 两线程 Barrier 后并发同日签署 | 恰一成功，另一 200+业务错误；无死锁；无重复行 | 【既有】dutylog（模板） | 已覆盖，可复制到其他唯一约束场景 |
| BC-CONC-02 | N=5 线程同 client_token 并发 POST | 恰 1 条记录；IntegrityError 被捕获回退为幂等返回（先例 document `test_folder_create_idempotent.py:349`） | 【新增】 | `apps/equipment_lifecycle/tests/` |
| BC-CONC-03 | 两会话基于同一 version 并发 PUT 台账 | 恰一成功，另一版本冲突业务错误；version 单调不回退 | 【新增】 | `apps/equipment_lifecycle/tests/` |
| BC-CONC-04 | 并发触发健康状态重算（GET_LOCK 串行域） | 串行执行，最终健康状态一致；锁在事务提交前不释放（契约测试先例 `test_system_events.py:583`） | 【既有契约，补真实线程并发【新增】】 | `apps/equipment_lifecycle/tests/stable_contract/` |
| BC-CONC-05 | 同一对象改/删竞态：A 改 B 删同时 | 结果确定（成功或明确业务错误）；无 500、无幽灵更新 | 【新增】 | 各 app `tests/` |
| BC-CONC-06 | 状态机动作互斥：并发 accept/void/urge（coop_task 检查点注入法），扩展到工单接单/复核 | 互斥成立，无中间态泄漏 | 【既有】coop_task；扩展【新增】 | 各状态机 app `tests/` |
| BC-CONC-07 | 幂等预检竞态：两请求同时通过 `check_recent_duplicate` 预检查 | 唯一约束/锁兜底，不产生双行；预检查不得用 select_for_update（gap 锁死锁教训，见 dutylog 签署） | 【新增】 | 各 app `tests/` |
| BC-CONC-08 | 并发写审计链 | AuditLogSequence 无分叉（哈希链稳定锁行修复后的回归） | 【既有】`apps/audit_risk_tests.py:252` + logs 金丝雀 | 已覆盖，引用即可 |

---

## 6. 未登录访问（BC-AUTHN）

**契约**：HTTP 401 + `{"error": "验证失败，请重新登录"}`（`libs/middleware.py:241-242`）。token 规则：32 位、匹配 access_token、未过期、is_active、可选 IP 绑定（`:189-212`）。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-AUTHN-01 | 完全缺失 x-token，请求各模块代表端点 | 401 + 固定文案 | 【既有】各模块 `test_unauthenticated_denied`（alert/device/upgrade 等） | 做成参数化抽查矩阵补全其余模块 |
| BC-AUTHN-02 | 无效 token：32 位随机串 / 31 位 / 33 位 / 空串 | 全部 401（长度≠32 直接拒，`:189`） | 【部分既有】regulation `test_04_permission_tenant.py:26-32` | 补长度边界 |
| BC-AUTHN-03 | 过期 token：token_expired < now | 401 | 【新增】 | `apps/account/tests/` |
| BC-AUTHN-04 | 停用账户的有效 token（is_active=False） | 401 | 【新增】 | `apps/account/tests/` |
| BC-AUTHN-05 | 预览端点 GET 且 URL 携带 x-token | 401 + 专属文案"预览端点禁止在 URL 中使用 x-token…"（H-5 修复，`:174-176`） | 【新增固化】 | `apps/document/tests/` |
| BC-AUTHN-06 | preview_token / attachment_preview_token 无效、过期、绑定字段不符（file_id/user_id/tenant_id 篡改） | 401；绑定字段不符即使 token 签名有效也拒绝 | 【部分既有】附件端点缺 token 拒绝；篡改场景【新增】 | `apps/document/`、`apps/evidence/tests/` |
| BC-AUTHN-07 | IP 绑定：同 token 换 IP 请求（bind_ip 开启时）；IP_CHECK_EXCLUDES 命中路径 | 换 IP 401；排除路径放行——按配置契约双向断言 | 【新增】 | `apps/account/tests/` |
| BC-AUTHN-08 | 白名单边界：AUTHENTICATION_EXCLUDES 外全量抽样 | 白名单外全部 401（防白名单过宽的正向回归） | 【新增】 | `apps/account/tests/` 或 `quality/permission_audit/` |
| BC-AUTHN-09 | token 篡改变形：前后加空格、大小写变换、加引号 | 401（不做 normalize） | 【新增】 | `apps/account/tests/` |

---

## 7. 越权访问（BC-AUTHZ）

**契约**：已登录无权限 = 200 + `{"error": "权限拒绝"}`；跨租户 = 不可见不可改且响应体不含对方数据。**基建直接复用** `quality/tenant_isolation/`：`factories/tenants.py` 的 `make_tenant_pair`、`factories/users.py` 的 `make_user`（直接造 token 不走登录）、`helpers/api_assertions.py` 的 `assert_no_cross_tenant` 等，照 `test_cross_tenant_crud.py` 的 `_rec()` 格式挂新用例。

| 用例ID | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|
| BC-AUTHZ-01 | 水平越权全家族：租户 A token 对租户 B 对象 get/put/delete/list/附件下载/统计 | 全部拦截；`assert_no_cross_tenant`；响应体无 B 数据字段 | 【既有体系】`quality/tenant_isolation/tests/` 6 个文件；未覆盖模块补齐 | `quality/tenant_isolation/` |
| BC-AUTHZ-02 | 垂直越权：有登录、无该模块权限码；相近权限码（view vs add）互换 | 200+"权限拒绝"；权限码不混淆 | 【既有先例】runlog `test_view_without_permission:532` | 各 app `tests/` 矩阵化 |
| BC-AUTHZ-03 | 权限缓存时效：改角色 → perms_version 更新 → 旧 token 立即按新权限判定（Redis perms_{id} 版本机制） | 提权/降权即时生效 | 【新增】 | `apps/account/tests/` 或 `quality/permission_audit/tests/runtime/` |
| BC-AUTHZ-04 | 对象级越权：公共空间 `check_public_space_permission`；党建 system_scope fail-closed 跨 scope 列表/详情/附件 | 全链拦截 | 【新增补缺】 | `apps/document/tests/`、`quality/tenant_isolation/` |
| BC-AUTHZ-05 | 批复全局共享特例（正反双向）：有 approval 权限用户跨租户可见可管；无权限者不可见；RadioLicense 不外溢仍租户私有；批复附件访问先校验父批复存在 | 三向断言全部成立（2026-09 例外契约） | 【部分既有】radio_license release_gate | `apps/radio_license/tests/` |
| BC-AUTHZ-06 | IDOR 参数篡改：请求体伪造 tenant_id/created_by/user_id | 服务端以 token 用户为准，载荷字段被忽略 | 【新增】 | `quality/tenant_isolation/` |
| BC-AUTHZ-07 | 存在性枚举防护：不存在 id vs 他租户 id 的响应 | 两者响应不可区分（不泄露他租户对象存在性） | 【新增】 | `quality/tenant_isolation/` |
| BC-AUTHZ-08 | 附件深链：猜 attachment id / preview-file URL 跨模块、跨租户访问 | 401 或业务错误；preview_token 绑定字段校验生效 | 【部分既有】各模块附件测试 | `quality/tenant_isolation/` |

---

## 8. 数据库断连（BC-DB）

**现状**：近零覆盖。唯一近似物是 `quality/disaster_recovery/runners/run_failure_drill.py:194-216`（名为模拟、实为结构化检查）；兜底路径已有实现但无测试。这是本用例集最大的增量空间。

**三层手段**（按环境隔离强度递增）：

- **L1 单元/集成（test_spug 库，可进常规门禁）**：patch 数据库 cursor 抛 `django.db.utils.OperationalError`（模拟 2006/2013 gone away），或 patch `django.db.connections`；恢复 patch 后断言自愈。
- **L2 集成真断连（tdyw-test 容器）**：测试进程中 `KILL <connection_id>` 真实杀连接后发起请求。
- **L3 环境演练（仅测试环境，走灾备门禁）**：`docker stop tdyw-db` → 全站请求 → `docker start` 恢复。

| 用例ID | 层级 | 输入构造 | 期望结果与断言 | 现状 | 建议落点 |
|---|---|---|---|---|---|
| BC-DB-01 | L1 | 读接口请求时 cursor 抛 OperationalError | 200 + `{"error": "服务器内部错误，请联系管理员"}`；响应不含堆栈/DB 指纹（表名、"MariaDB"、"Lost connection"）；error 日志含 request_id；send_alert 被调用 | 【新增】 | `quality/database_audit/`（跨模块通用兜底契约） |
| BC-DB-02 | L1 | 写接口事务内抛 OperationalError | 事务回滚，count 不变；响应同上统一结构 | 【新增】 | 同上 + 各 app 抽一个代表写接口 |
| BC-DB-03 | L1 | 写接口在物理文件已写之后 DB 断连（先文件后库契约，AGENTS.md 十一.2） | DB 无记录；**孤儿文件为已知行为**——用例固化现状并在报告中标记为改进项，不得静默通过 | 【新增】 | 调用方业务 app `tests/` |
| BC-DB-04 | L1 | 断连失败后恢复，同 client_token 重提 | 成功且仅 1 条（幂等键跨故障重试安全） | 【新增】 | `apps/equipment_lifecycle/tests/` |
| BC-DB-05 | L1 | 断连恢复后同一进程后续请求 | 正常返回（Django 连接自愈语义） | 【新增】 | `quality/database_audit/` |
| BC-DB-06 | L1 | Celery beat 任务执行中 DB 断连（如提醒检查/执照过期检查） | 重试有深度/次数上限不无限（AGENTS.md 十.3）；恢复后下一轮正常 | 【新增】 | 对应 app `tests/` |
| BC-DB-07 | L2/L3 | 断连期间与恢复后观察监控链路 | health_probe → unavailable 告警、恢复 → recovered（`apps/alert/tasks.py:70,139-180`）；record_business_error 计数增长 | 【新增】 | `apps/alert/tests/` |
| BC-DB-08 | L2 | 慢查询/锁等待超时（与断连同路径） | 走同一兜底路径，不挂死 worker | 【新增】 | `quality/database_audit/` |
| BC-DB-09 | L3 | tdyw-db stop 期间登录 | 登录接口统一错误结构，不暴露内部信息；恢复后登录正常 | 【新增】 | `quality/disaster_recovery/`（演练脚本） |

---

## 9. 既有覆盖对照与实现优先级

**重复风险高（实现前先查引用文件）**：①空值、②超长、④重复提交、⑥未登录、⑦越权——这五类在 contract_agreement、department_duty_log、coop_task、regulation、equipment_lifecycle 及 `quality/tenant_isolation/` 已有大量覆盖，新增时做成"未覆盖模块的参数化实例化"，不要重复写断言。

**增量空间大（优先排期）**：
1. **P1**：⑧数据库断连全组（近零覆盖）+ BC-CONC-02/03/07（真实线程并发与幂等竞态）+ BC-NEG-03/05（数值字段负数与溢出）。
2. **P2**：BC-AUTHZ-03/06/07（权限缓存时效、IDOR、枚举防护）+ BC-NULL-05/08（嵌套结构空值、PUT 半更新）+ BC-AUTHN-06（preview_token 绑定篡改）。
3. **P3**：其余抽查矩阵固化（各 app 照模板补齐，随模块改造顺带做）。

**落点规则**（AGENTS.md 测试落点）：单模块行为放 `apps/<app>/tests/`（稳定契约进 `stable_contract/`）；跨租户放 `quality/tenant_isolation/`；数据库/中间件通用兜底契约放 `quality/database_audit/`（若认为需要一个独立的 resilience 专项目录，先与维护者确认再新建，不擅自扩目录）；断连环境演练放 `quality/disaster_recovery/`。运行产物一律进 `quality/reports/`。

**本文件状态**：设计文档，未含可执行代码；状态字段均以 2026-09-20 覆盖调查为准，实现时如引用的既有测试已移动/改名，以实际仓库为准。
