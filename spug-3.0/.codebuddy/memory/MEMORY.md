# 项目记忆

## 附件功能架构（2026-06-30 确立）

**架构**：后端 evidence 通用底座 + 前端公共组件

**后端**：
- `apps/evidence/models.py` 的 `EvidenceAttachment`：通用表（module+object_type+object_id 多态关联）
- `apps/evidence/attachment_service.py`：通用 AttachmentService（upload/list/download/soft_delete/soft_delete_by_object）+ AttachmentConfig 配置类
- 各模块写桥接视图（参考 `apps/upgrade/views/upload.py`），负责：校验业务对象存在 + 校验模块权限码 + 转调 evidence.AttachmentService
- evidence 不提供 views/urls（因为无法感知各模块权限码）
- radio_license 保持独立实现（向后兼容，有 attachment_type 业务字段）

**前端**：
- `components/AttachmentManager.js`：公共组件，路径/权限全参数化
- 各模块 `import { AttachmentManager } from 'components'`，传 URL + 权限码

**后续模块加附件标准流程**：
1. 后端：复制 `apps/upgrade/views/upload.py` 作为模板，改 MODULE/OBJECT_TYPE/权限码/Config
2. 后端：业务对象删除时调用 `AttachmentService.soft_delete_by_object(module=..., object_type=..., object_id=...)`
3. 前端：`import { AttachmentManager } from 'components'`，传 URL + 权限码
4. 无需新建附件表、无需新建 service

**技术要点**：
- migration 里 `human_datetime` 引用路径是 `libs.utils.human_datetime`（mixins.py 没有 re-export）
- `AlterModelOptions` 在 Django 2.2 下第一个参数是 `name`（不是 `model_name`）
- 文件名清洗防路径穿越：`os.path.basename` + 替换 `..` `/` `\` `\x00`
- 下载鉴权用 `x-token` GET 参数
- 软删除保留物理文件和 DB 记录作为证据痕迹
- upgrade 附件数据存 evidence 表，通过 `module='upgrade'/object_type='record'/object_id=<record_id>` 关联

## Django 升级路线（2026-06-27 进行中）
- 总路线：2.2.28 → 3.2.25（阶段1已完成）→ 4.2.30（阶段2已完成验收）→ 5.2 LTS（阶段3待做）
- 容器 `tdyw-test`（镜像 `tdyw:django42-stage2`），项目路径 `/data/spug/spug_api`，Python 3.10
- 阶段2验收中把 Channels 从 3.x 升到 4.x（3.x 与 asgiref 3.11 有兼容 bug），需重建镜像固化
- **Channels 4.x 升级三要素**：consumer `__init__` 不能访问 `self.scope`（改用 `init()` 钩子）；routing 用 `Consumer.as_asgi()` 注册；asgi.py 用 `from spug.routing import application` 替代 `get_default_application()`
- 遗留：settings.py 的 CELERY_TASK_ROUTES 任务名与资料库 cleanup 模块重构后路径不一致（非升级阻断项）

## 项目规范

### 上传状态机 operationVersion（7.3 异步并发安全）
- 每个上传 item 有 `operationVersion` 字段，方法在 `UploadQueueStore`（queue.js）
- `bumpOperationVersion` / `getOperationVersion` / `isCurrentOperation`
- START/RESUME/PAUSE/CANCEL 事件在 `UploadStateMachine.transition` 中自动递增
- 绕过状态机的取消路径（cancelItem / cancelAll）需显式 `bumpOperationVersion`
- 异步回调携带 `operationVersion`，过期则丢弃（调用点检查 + 状态机 payload 兜底）
- 向后兼容：无版本号的 transition 正常执行（旧测试/mock 不受影响）

### 数据库迁移纪律 ⚠️ 重要（2026-06-28 约定）

**修改 Django 模型后必须执行迁移**：
```bash
# 1. 生成迁移文件（指定 app + 手动命名，避免 0006_auto_xxx）
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations <app> --name <语义化名称>

# 2. 执行迁移
docker exec tdyw python /data/spug/spug_api/manage.py migrate <app>
```

**迁移纪律约定**：
1. **一个功能 PR 尽量只产生一个 migration**：同一 PR 内的多个模型改动合并到同一个迁移文件，避免迁移历史碎片化。
2. **migration 文件手动命名**：`makemigrations --name xxx` 给语义化名称，少用 Django 自动生成的 `0006_auto_20260628_1234` 这类无意义名。
3. **schema migration 和 data migration 尽量分开**：结构变更（加字段/改约束）与数据回填/清洗分成独立迁移文件，便于回滚和审计。
4. **CI 检查项**（必须通过）：
   - `python manage.py makemigrations --check --dry-run` — 检测是否有未提交的模型变更（有则 CI 失败，强制先 makemigrations）
   - `python manage.py migrate --plan` — 打印迁移执行计划，人工/脚本核对顺序与依赖是否合理

**已踩过的坑**：
- `makemigrations` 不指定 app 名会扫描全部 app，对其他模块 Meta 选项变更（verbose_name_plural/ordering）也会生成意外迁移文件，污染迁移历史。误生成应立即删除。
- 加唯一约束必须拆步：先加非唯一字段 → 回填 → 检查重复 → 再 AlterField 加 unique（见 0005 迁移）。
- **字段 `db_index=True` 与 `Meta.indexes` 同字段单列索引会生成两套索引**（Django 不去重）。`Meta.indexes` 只用于复合索引或需自定义命名的场景；声明前先检查字段是否已 `db_index=True`。logs app 0004 迁移即清理此类重复（`audit_req_hash_idx` 等三条与自动索引重复）。
- **CharField→DateTimeField/DateField 迁移必须先清洗空字符串**：可空时间字段历史数据可能有空串 `''`（非 NULL），直接 `ALTER` 到 `DATETIME` 会失败或产生 `0000-00-00` 垃圾值。迁移文件中在 `AlterField` 前加 `RunPython` 把 `filter(col='').update(col=None)`。`NULL` 在 ALTER 时安全保持，无需处理。迁移前用 `STR_TO_DATE(col, fmt) IS NULL` 统计 NULL/空串/合法/非法分布。logs+runlog 已完成此迁移（0006/0009）。
- **手写 migration 的 Index name 必须与 model Meta.indexes 的 name 一致**：如果 model 的 `Meta.indexes` 里 Index 没有指定 `name`，Django 会自动生成哈希名（如 `tdyw_upgrad_upgrade_d8a2d4_idx`）；手写 migration 里如果用了不同的 name，Django 会生成一个 rename index 迁移。解决：在 model 和 migration 都显式指定相同的 `name='xxx'`。upgrade 0008 迁移即踩此坑。

### Docker 路径
- 容器内项目路径: `/data/spug/spug_api/`
- manage.py 位置: `/data/spug/spug_api/manage.py`

### 资料库备份/还原脚本（2026-07-04 修复一致性缺陷）
- 脚本：`backups/documents_incremental_backup.sh`、`backups/documents_restore.sh`
- **增量发现 = mtime + ctime**：用 `find -newermt "@${epoch}" -o -newerct "@${epoch}"`。**不用 `-cnewer marker`**——标记文件经 `docker cp` 进容器后 ctime 被重置为当前时间，`-cnewer` 会失效。epoch 取宿主机 marker 的 mtime，时区无关。
- 每次备份产物 3 件：`.tar.gz` + `.manifest`(TSV: 相对路径/大小/mtime/ctime) + `.meta`(key=value)。0 文件增量只生成 meta。
- 还原流程：`tar tzf` 校验全量+所有增量 → 清空目标(`CLEAR_TARGET=YES`默认) → 全量+按文件名时间戳顺序应用增量 → manifest 校验(`comm -23` 求缺失) → 恢复报告。
- **核心教训**：数据库备份和 documents 备份必须同周期；只恢复数据库不恢复文件卷 → 前端可见但预览/下载报"文件不存在"。恢复顺序：停业务→恢复DB→清空documents→full→incrementals→启动→一致性检查。
- Windows 验证：用 `wsl -e bash`（路径 `/mnt/e/...`），`C:\Windows\System32\bash.exe` 是 WSL；`/e/` 路径在此 WSL 也有效但 PowerShell 直传 `bash /e/...` 会找不到文件。

### 生产环境内存分配（8G 服务器，2026-06-29 调整）
8G 物理服务器下三个容器的内存分配（扣除系统 ~1G，剩 7G 分给容器）：
| 容器 | memory limit | memory reservation | 关键内存项 |
|---|---|---|---|
| tdyw（主应用） | 2G | 512M | Django+Gunicorn(4×16)+Celery+Nginx |
| tdyw-db（数据库） | 3G | 1G | innodb_buffer_pool_size=2G |
| kkfileview | 1.5G | 512M | LibreOffice 转换（峰值高但并发低） |
- MySQL `max_connections` 从 800 下调到 300（Gunicorn 64 连接 + Celery + kkFileView 最多 ~150）
- 16G 服务器可恢复原配置（tdyw 4G / db 8G buffer_pool 4G / kkfileview 4G / max_connections 800）

### 代码验证流程（post-write-verification skill）
1. Lint 检查: `read_lints(paths=[...])`
2. 语法检查:
   - Python: `docker exec tdyw python -m py_compile <path>`
   - **WSL docker 调用**（本机 docker 在 WSL 中）：`wsl docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check`；Django check 输出会被 PowerShell CLIXML 包装吞掉，改用 `wsl bash -c 'docker exec ... python manage.py check'`（单引号避免内层双引号 EOF）；`-w` 指定工作目录避免 `bash -c "cd ..."`
   - JavaScript (项目用 ES Module + 装饰器 + classProperties):
     ```
     cd e:/TDYW/spug-3.0/spug_web && node -e "const parser = require('@babel/parser'); const code = require('fs').readFileSync('FILE', 'utf8'); parser.parse(code, { sourceType: 'module', plugins: ['classProperties', 'decorators-legacy', 'dynamicImport'] });"
     ```
   - **注意**: `tdyw` Docker 容器是 Python 容器，无 node；不要用 acorn 解析 JS（不支持装饰器）
3. 代码变更确认: `git diff`
4. 针对性测试脚本验证（专用脚本，验证完清理）

### 核心教训
- 遇到问题第一反应是回查 skill 文档，而非凭直觉绕过
- skill 是经过验证的标准流程，比个人直觉更可靠
- Windows 本地环境存在编码、缺少依赖等问题，不适合直接运行 Python 测试
- **antd 版本差异**：antd 4.x 使用 `visible` 属性控制 Modal 显示，antd 5.x 使用 `open` 属性。本项目使用 antd 4.21.5，必须用 `visible`

### 角色委派权限边界（2026-07-05 实施，两轮完成）
- **问题**：拥有"用户管理/创建账号"权限的普通管理员可看到并分配超管创建的高权限角色 → 越权授权
- **修复**：后端为准，前端只做体验优化
- **数据模型**：`Role` 增加 `tenant_id`（null=平台级角色）和 `is_system`（系统内置角色）；`Role.to_dict()` 显式输出这两个字段供前端回显
- **统一授权方法**（`apps/account/role_permissions.py`）：
  - `get_assignable_roles(operator)` — 超管全部；普通管理员本租户非系统非全局管理员
  - `validate_assignable_role_ids(operator, role_ids, target_tenant_id=None)` — **超管校验租户角色与目标租户一致性**（平台级角色和全局管理员角色不限；租户角色必须 tenant_id == target_tenant_id）；target_tenant_id=None 时超管宽松放行（向后兼容）；普通管理员仍只能分配本租户普通角色
  - `get_manageable_role(operator, role_id)` — 角色 CRUD 可管理范围
  - `flatten_page_perms` / `validate_page_perms_subset` / `validate_group_perms_subset` / `validate_deploy_perms_subset` — 普通管理员新角色权限必须是自身权限子集
- **Migration 0006 历史回填**（保守策略）：超管创建→平台级系统角色；普通用户创建→归属其 tenant_id；is_global_admin=True→强制平台级系统；无 created_by/脏数据→默认平台级系统
- **调用点**：
  - RoleView.get/post/patch/delete 全部经统一方法
  - RoleView.post() 解析 tenant_id/is_system，超管可设置，普通管理员强制覆盖；编辑时若 is_global_admin/tenant_id/is_system 变更则 clear_perms_cache + token_expired=0
  - UserView._handle_user_create：先 _resolve_tenant_id 再用 target_tenant_id 校验 role_ids
  - UserView._handle_user_edit：用编辑后目标 tenant_id 校验（超管同时改 tenant_id 和 role_ids 时按新 tenant_id 校验）
  - 普通管理员不能编辑超管账号
- **前端**：RoleView.get 已过滤；角色 Form.js 超管专用表单项（角色归属 platform/tenant + 租户下拉 + is_system Switch + is_global_admin Switch）；普通管理员不显示且不提交；租户下拉复用 /api/account/user/tenant_choices/
- **测试**：`tests/test_role_delegation.py` 27 个用例全通过（含超管租户一致性 5 个 + to_dict 1 个）
- **第四轮：账号表单可分配角色下拉专用接口**（2026-07-05，体验优化）
  - 新增 `GET /api/account/role/assignable/?tenant_id=<可选>`，受 `AssignableRoleView(AdminView)` 保护，`PERM_MAP={'GET':'system.account.view'}`
  - `role_permissions.py` 新增 `get_assignable_roles_for_target(operator, target_tenant_id=None)`：普通管理员忽略 target_tenant_id 只返回本租户普通角色；超管返回全局管理员角色 + 目标租户角色（target_tenant_id 有值时追加），**不返回平台级普通角色**（收紧，见下方"平台级角色概念修正"）
  - 与 `get_assignable_roles`（角色管理列表用，超管返回全部）并存，**不要合并**——方案明确区分"角色管理列表"与"账号可分配角色下拉"两个概念
  - 前端 `Form.js` 改用 `assignableRoles` state 拉取渲染下拉；超管切换 tenant_id 时重新拉取并清空 role_ids；extra 文案"仅显示当前账号可分配给该用户的角色"
  - `Table.js` 仍用 `rStore.idMap` 显示账号列表角色名称，**不能动**
  - `validate_assignable_role_ids` 强校验保留，新接口仅体验优化不替代安全边界
- **平台级角色概念修正（2026-07-05）**：平台级角色 `tenant_id=null` 只表示归属平台层，**不等于"可分配给任意租户用户"**。`get_assignable_roles_for_target` 收紧为不返回平台级普通角色（只返回全局管理员角色 + 目标租户角色）；`validate_assignable_role_ids` 逻辑不变（超管提交平台级角色后端仍放行，属超管权限），只改注释表述。未来如需跨租户分配平台级普通角色，应新增 `is_cross_tenant_assignable` 字段显式开启。

### 技术细节
- spug_web 使用 antd 4.21.5
- spug_api 使用 Django + MySQL
- 租户隔离使用 TenantModelMixin
- **数据库: MariaDB 10.8.2**（不支持部分唯一索引 WHERE 条件）
- Django `UniqueConstraint(condition=Q(...))` 在 MariaDB 上**静默跳过**，不创建数据库索引
- 解决方案：使用 `unique_key` 字段（MD5 哈希），is_deleted=True 时设为 NULL，利用 MySQL 中 NULL 不参与唯一索引

### 模型 Mixin 架构（2026-06-11 重构）
- **5 个 Mixin** 消除了 Public/Private 模型的重复逻辑：
  1. `SoftDeleteFolderMixin`（abstract Model）：文件夹 delete(hard)/restore()
  2. `FolderPathMixin`（普通类）：get_full_path() 迭代实现 + 循环/深度保护
  3. `UniqueKeyMixin`（abstract Model）：save() 自动计算 unique_key hook
  4. `SoftDeleteFileMixin`（abstract Model）：文件 restore()
  5. `DocumentFileDeleteMixin`（abstract Model）：硬删除 + 物理文件/缩略图清理 + is_pending_clean 兜底
- **MRO**: `DocumentFolderPrivate(SoftDeleteFolderMixin, FolderPathMixin, UniqueKeyMixin)`
- **MRO**: `DocumentFilePrivate(SoftDeleteFileMixin, DocumentFileDeleteMixin)`
- **不变性**：db_table、字段、约束全部不变，无需 migration
- **子类差异**：`_compute_unique_key()` 由子类各自实现（Private 含 tenant_id+created_by，Public 不含）
- `hashlib` 已移到模块顶部 import（之前在 `_compute_unique_key` 函数内 import）

### 迁移 0005 关键设计（2026-06-11 修正）
- **4 步拆分**：删旧约束 → 加非唯一字段 → 回填+重复检查(raise) → AlterField 加 unique
- **原因**：如果先加 unique 再回填，历史重复数据会导致 UPDATE 撞唯一索引失败
- **重复检查**：backfill 函数发现重复时 `raise RuntimeError` 中止迁移，强制先清理数据
- **回填方向**：需要 reverse_backfill 将 unique_key 清空为 NULL

### DocumentFileDeleteMixin 事务语义（2026-06-11 修正）
- 嵌套 `transaction.atomic()` 只是 **savepoint**，外层回滚时标记也会丢失
- 调用方若需要 is_pending_clean 可靠落库，**不应在捕获异常后回滚外层事务**
- 如需更强保障，需改用异步补偿（如 Celery 任务重试待清理文件）

### 文件夹创建幂等改造（2026-06-11）
- **问题**：深层目录上传触发 `Duplicate entry for key 'unique_key'`（1062 错误）
- **根因**：前端 `_createPathStructure` 递归创建路径，多个叶子路径共享祖先时并发重复创建
- **修复方案（双保险）**：
  1. **后端** `FolderView.post` 改为幂等接口：先查已有 → 创建 → 撞 IntegrityError 再查一次
     - 新增 `_find_existing_folder()` 静态方法
     - 返回 `{ id, created }` 区分新建/复用
     - IntegrityError 在 `transaction.atomic()` 外捕获（避免事务 broken 状态）
  2. **前端** `FolderStructureBuilder` 改为"全路径展开 + 按层创建"：
     - `_extractDepthGroups` 展开所有祖先路径（A/B/C/file.txt → A, A/B, A/B/C）
     - `_createSinglePath` 只创建路径最后一级，父 ID 从 folderMap 取
     - 删除 `_checkExisting`（后端已幂等，前端无需预查）
     - 删除 `_createPathStructure`（递归创建被按层创建替代）
- **关键约束**：unique_key 保留（最后防线），业务层把 1062 转为返回已有 ID

### 公共空间 unique_key 规则的影响
- 公共空间 unique_key = `MD5(name:parent_id)`，**不含 created_by**
- 这意味着公共空间同名文件夹是**全局唯一**（不区分创建人）
- 所有冲突检查逻辑（恢复、重命名、移动）都不应按 created_by 过滤
- 之前 folder_restore.py 的 `_resolve_name_conflict` 误加了 `created_by=user` 过滤，已修正

### 重构方法论（用户偏好）
- **渐进式重构 > 大爆炸式重构**：每阶段独立 PR、独立可回滚
- **修 P1 > 重构架构**：先用最小改动修高风险问题（如内存泄漏、暂停失效），再考虑抽象
- **YAGNI > 抽象层复用**：不预先创建 BatchExecutor 等抽象，等出现第 3 种场景再考虑
- **关注点分离 > DRY**：职责清晰比代码行数少更重要
- **测试驱动 > 凭直觉**：每个修复都用专用测试脚本验证
- 用户倾向：先给完整方案（写入 MD），用户认可后再实施，而不是边做边改

### 运行日志 (runlog) 模块
- `RunLog.update_count` 是缓存字段，存储动态记录数量
- 存在数据不一致问题：检查发现 `ID=7` (stored=3, actual=1) 和 `ID=6` (stored=8, actual=1) 不一致
- 已添加修复接口：`POST /api/runlog/repair/`
- 已有检查脚本：`/data/spug/spug_api/check_runlog_update_count.py`

### 导出功能架构（2026-06-26 重新设计）
- **公共工具**：`spug_api/libs/export_utils.py`（Excel）、`spug_web/src/libs/exportFile.js`（下载）、`spug_web/src/components/ExportButton.js`（按钮）
- **原则**：统一导出机制不统一业务字段；Excel 模块后端全量导出（非当前页）；PDF 模块保留专用模板
- **导出上限**：默认 10000 条，超量/空数据返回 `JsonResponse`（http 拦截器解析二进制中的 JSON 错误）
- **6 模块**：fault/interference/upgrade/device列表(Excel) + checksheet/runlog/device履历(PDF)
- **复用**：upgrade 复用 `RecordService._apply_filters`；PDF 模块统一改用 `exportFile`（含 `loadingText`）
- **文件名**：RFC 5987 中文编码（`filename*=UTF-8''`）；格式 `模块名_范围_时间.ext`
- **store 约定**：每个模块 store 提供 `getExportParams()`，日期范围用 `f_export_date_range`（moment 对象）

---

## 反思清单（2026-06-06 固化，源自资料库传输列表重构 5 轮迭代）

> 这一节是**跨会话必须遵循**的反思。每条都来自真实的踩坑，不是空话。

### 1. 用户用反问句质疑时，立即承认错误
- **踩坑**：用户问"哪11个文件状态机怎么重写"，我曾用"重构范围"做挡箭牌继续说
- **正确做法**：反问句 = 用户已经发现我在夸张。**第一句就承认**：实际动的是 4 个文件、状态机没动、之前说"11 个"是营销话术
- **底线**：宁可承认错 5 次，也不要用漂亮话术掩盖 1 次

### 2. 增量改进 > 大爆炸式重写
- 5 轮迭代每一轮都独立可回滚（3 Tab / 抽屉 / 拖拽+闪烁 / 快捷键 / 错误分类）
- 每一轮都不破坏上一轮（向后兼容：缺省 errorCode 默认可重试）
- **反面教材**：如果第一轮就"重写整个传输列表"，一定挂

### 3. 配置化（枚举+集合）> 散落的硬编码
- ERROR_CODES 枚举 + RETRYABLE/NON_RETRYABLE 集合 + ERROR_CODE_MESSAGES 映射
- 未来加快捷键、加错误码，都只改一处
- **判断标准**：如果同一个字符串/状态在 3 处以上出现，必须抽出来

### 4. 参考成熟产品 + 行业惯例驱动设计（YAGNI 反义）
- 3 Tab、cancelled 归失败、paused 归上传中 — 全部来自阿里云盘/百度网盘
- **不是抄袭，是用成熟方案消除"过度设计"**
- **新需求前先问**：百度/阿里/Dropbox 怎么做的？

### 5. 不要预先做全套 UI 改进
- 用户每次只问一个点（"传输列表怎么设计"→3 Tab→抽屉→拖拽→闪烁→快捷键→文案→错误分类）
- 推进顺序：用户确认方向 → 实施 → 验证 → 等下一个反馈
- **判断标准**：用户没问的，绝不主动加

### 6. 每次修复后主动全局扫描同类问题
- 修完 `chunkUpload.js:496` 的 merging+error bug 后，主动扫 `UploadLifecycle.js:104` 和 `ChunkUploadCoordinator.js:30`，发现并修了同款 bug
- **这是用户问"还有其他吗"的标准答案**：不是只说"没有了"，是已经扫完了再说

### 7. error 字段一致性原则
- 正常状态（waiting/calculating/uploading/merging）**不应有** error 字段
- 错误状态（error/cancelled）才设置 error 字段
- 原因：`TransferItem.js:294` 的双重条件 `status === 'error' && item.error` 防止误显示
- 副作用：error 字段会触发 React.memo 重渲染（`TransferItem.js:340`）
- **扫描脚本思路**：在 calculating/uploading/merging 状态附近 300 字符窗口不应有 `error: '...'`

### 8. MD5 是内部技术细节，不该向用户暴露
- 行业惯例：百度/阿里/Dropbox/OneDrive/iCloud/微云均不单独显示 MD5 计算
- 我们的选择：保留 calculating 状态（因为状态机依赖），但**优化文案**：
  - "计算中" → "准备上传"（更通俗）
  - 加 Tooltip 解释"计算文件指纹以加速上传（秒传/断点续传）"

### 9. 合并中必须显示（MD5 的反例）
- 合并耗时长（最长 5 分钟，`MERGE_MAX_POLLING_TIME: 300`）
- Celery 任务无 progress，进度条卡 100% 用户会以为卡死
- 行业惯例：百度/阿里/微云/Dropbox 都显示"合并中"或"Finalizing…"

### 10. 错误分类决定 UX
- 权限错误 → 提示"联系管理员"，**无重试按钮**（重试无用）
- 配额满 → 提示"清理后重试"，**无重试按钮**（重试无用）
- 网络错误 → 提示"检查网络后重试"，**有重试按钮**（重试可能成功）
- **设计原则**：按钮的可见性应该由"重试能否解决问题"决定，不是"出错没出错"

### 11. 抽屉模式核心实现（仿百度网盘）
- 收起态：底部居中小条（fixed, bottom:0, left:50%, h=40px），不挡视野
- 展开态：antd Drawer placement="bottom" + 可调高度（240-720px）
- 触发：右上角图标按钮 / 点击小条 / Ctrl+Shift+U
- 自动隐藏：无任务时不渲染 MiniBar

### 12. 手写拖拽把手的关键坑
- 用 `document.addEventListener('mousemove'/'mouseup')` 而非 React onMouseMove（避免鼠标离开把手时事件丢失）
- **必须**在 `componentWillUnmount` 解绑，否则组件卸载后遗留监听器
- 高度 < 120px 时自动触发收起（贴边行为）
- 边界约束由父组件强制 240-720px

### 13. 键盘快捷键的关键坑
- 输入控件聚焦时不响应 — `isInEditableElement()` 检测 `input/textarea/select/contenteditable`
- Mac 兼容 — `e.ctrlKey || e.metaKey`
- `preventDefault + stopPropagation` 阻止浏览器默认
- useEffect 单一挂载点（不要在 onKeyDown 里 addEventListener）
- SHORTCUTS 配置化数组

### 14. PowerShell 环境适配
- `npx`/`head` 在 PowerShell 不可用，改用 `node test_xxx.js` + `1> out.txt 2>&1` 重定向
- `node --check` 不支持 ESM `import`，需用 `@babel/core` 脚本
- 项目用 legacy decorators，必须加 `@babel/plugin-proposal-decorators`
- 项目用 class properties，必须加 `@babel/plugin-proposal-class-properties`
- C:\temp 写入受限，改写到工作区根目录

### 15. Skill 流程 > 个人直觉
- 遇到问题**第一反应是回查 skill 文档**，不是凭直觉绕过
- post-write-verification skill：Lint → Docker py_compile → git diff → 针对性测试脚本
- 依赖 Django 环境的测试**必须在 Docker 容器内执行**，不要在 Windows 本地跑
- **判断标准**：skill 是经过验证的标准流程，比个人直觉更可靠

### 15.5 ESLint `no-unused-expressions` 陷阱
- **触发条件**：`obj?.method()` 这种 optional chaining + 方法调用模式
- **错误信息**：`Expected an assignment or function call and instead saw an expression`
- **原因**：ESLint 把 `obj?.method()` 视为"表达式语句"而非"函数调用"，因为左侧是 `obj?.method`（属性访问）
- **修复**：`obj?.method()` → `if (obj) obj.method();`
- **预防**：函数体内用 optional chaining 调用方法时，永远写成 `if` 保护

### 15.6 `@ant-design/icons` 实际可用图标候选（验证过）
- **不存在的图标**：`KeyboardOutlined`（想用"键盘"图标结果没有）
- **键盘/快捷键相关**：`KeyOutlined`（单个键，最贴合"快捷键"）、`MacCommandOutlined`、`ControlOutlined`
- **通用信息类**：`InfoCircleOutlined`、`InfoCircleFilled`、`QuestionCircleOutlined`
- **验证脚本**：用 `node -e "const i=require('@ant-design/icons'); console.log(typeof i.KeyOutlined)"` 检查存在性
- **type: 'object' 是正常的**：antd 图标用 `React.forwardRef` 包装，对 Node 端 typeof 是 object，但 React 能识别为组件
- **真正的验证**：`ReactDOMServer.renderToString(React.createElement(IconName))` 能产出 HTML 才算 PASS

### 16. 抽屉状态机升级的思路
- 老：`visible: true/false`（只有开/关）
- 新：`expanded: true/false`（开/关） + `drawerHeight: number`（240-720px）
- **原则**：状态机升级要**正交分解**，不要堆叠 boolean（否则会出现 `visible && expanded && !collapsed` 的混乱）

### 17. 代码审查中的关键教训（2026-06-11 补充）
- **迁移加唯一约束必须拆步**：先加非唯一字段 → 回填 → 检查重复 → 再加 unique，否则历史重复数据导致回填撞唯一索引
- **嵌套 atomic() 不是独立事务**：savepoint 会被外层回滚，注释必须如实说明，不能误导调用方
- **冲突检查要和约束规则一致**：公共空间 unique_key 不含 created_by，冲突检查也不能按 created_by 过滤
- **Django Model.save() 签名必须兼容**：`def save(self, *args, **kwargs)` 不能丢 `*args`
- **ErrorBoundary 不要暴露 error.message**：生产环境显示通用提示，详细错误只打日志

### 18. 上传并发瓶颈分析（2026-06-16 性能压测方案）
- **首要瓶颈**：Celery 合并队列容量（general-worker concurrency=4 + dev-worker concurrency=2 = 总计 6 并发）
- **次要瓶颈**：合并磁盘 I/O 串行写（`FILE_COPY_BUFFER_SIZE = 1MB`，应增到 8-16MB）
- **第三瓶颈**：MySQL `CONN_MAX_AGE = 0`（gevent 兼容无连接池，每次请求建新连接）
- **Gunicorn**：gevent worker，4 核容器 → 4 worker，worker_connections=10000
- **关键文件**：
  - 前端：`spug_web/src/pages/document/stores/constants/upload.js`（MAX_CONCURRENT_UPLOADS=3）
  - 后端合并：`spug_api/apps/document/tasks/merge.py`（FILE_COPY_BUFFER_SIZE=1MB）
  - Celery 启动：`spug_api/tools/start-celery-worker.sh`（concurrency=2）、`start-celery.sh`（concurrency=4）
  - Gunicorn：`spug_api/gunicorn.conf.py`（gevent, workers=CPU核数）
  - 压测脚本：`locustfile/locustfile_upload_pressure.py`
  - 压测方案：`locustfile/UPLOAD_PRESSURE_TEST_PLAN.md`
- **P0 优化建议**：① merge worker concurrency 2→8 ② FILE_COPY_BUFFER_SIZE 1MB→8MB ③ 安装 django-db-geventpool

### 19. 状态机与上传队列解耦（2026-06-17 Loop-200 修复，zlkloop 闭环）
- **根因**：入队时为每个文件批量 `stateMachineManager.create()`，`MAX_MACHINES=200` 硬上限 → 第 201 个 `create()` 返回 null → `startWaiting()` 只调度"已有状态机"的 waiting 任务 → 后续任务永久卡住
- **修复原则**：队列无限制，状态机懒创建，终态及时释放
- **关键改动**：
  - `UploadCoordinator.ensureStateMachine(item)`：唯一懒创建入口，调度时才创建，创建失败判空返回 null 保持 waiting
  - `startWaiting()`：不再 `filter(sm && sm.canTransition)`，改为先筛 waiting 再 `ensureStateMachine`
  - 入队路径（`_processBatch`/`_processUniform`/`processSingleFile`）：移除全部 `create()` 调用
  - `StateChangeHandler.handle()`：`completed/error/cancelled` 终态 `setTimeout(0)` 释放状态机
  - `ItemOperationController.resumeItem`：终态释放后重试时复用 `ensureStateMachine` 重建（**否则重试失效**）
  - `cancelItem`/`removeItem`：绕过状态机直接出队，需显式 `remove()` 否则泄漏
  - `MAX_MACHINES` 200→1000（仅保护性上限，不再是容量上限）
  - `MAX_DISPLAY_COUNT` 注释明确仅显示用途、不参与调度
- **全局监听器**：`index.js _initStateMachine` 注册的 globalListener 自动接入 `StateChangeHandler.handle`，懒创建的状态机无需单独 addListener
- **终态释放时机安全**：`onCompleted/onError` 不引用本任务状态机（已核实），`setTimeout(0)` 在回调链后执行
- **验证**：ESLint 0 错误；Babel 编译 6/6 OK；单测 29 通过/3 失败（3 个失败为预先存在的批量操作测试，与本次无关，`git diff` 证实 StateMachineManager 仅改 MAX_MACHINES）
- **教训**：保护性上限放错层级会变成业务容量上限；终态释放必须同步检查所有"读取状态机"的入口（resume/retry/cancel/delete）能否处理缺失
- **第二轮教训（1003 卡住）**：并发计数器 `activeUploads` 只统计 `uploading` 状态，不统计 `calculating`（大文件 MD5 计算期间），导致 `startWaiting` 误判有空闲槽位超发。修复：调度入口 `activeCount` 改为直接 `queue.filter(calculating + uploading)` 统计，不依赖只计 uploading 的计数器。注释写"calculating+uploading"但代码只统计 uploading——注释与代码不一致是 bug 高发区
- **第三轮教训（保护阈值彻底降级）**：仅抬高 `MAX_MACHINES` 上限不是"无数量限制"的真正解。真正解 = 入队不创建状态机 + 调度按并发槽位懒创建 + 创建失败 break 不扫爆 + 无法 START 立即 remove + 终态释放后触发 processPending 闭环 + 保护阈值只做异常兜底（强化清理终态+orphan）。关键：保护阈值只能限制运行时资源，不能限制单次入队文件数。重命名 `MAX_MACHINES` → `MAX_ACTIVE_MACHINES` 语义更清晰。目标架构：队列无上限、状态机稳定在并发数左右、并发由 `MAX_CONCURRENT_UPLOADS` 控制
- **第四轮教训（remove 误删运行中状态机）**：在 startWaiting 调度循环里对 `canTransition('START')` 失败的状态机做 `remove` 是灾难性的——状态机可能正在 calculating/uploading，只是 item.status 因时序窗口仍是 waiting。remove 会导致上传中断 + 每轮 processPending 都删除+创建新状态机 → 状态机数量爆炸到保护阈值。修复：(1) 并发槽位统计改用 `StateMachineManager.countByStates(['calculating','uploading'])` 直接读状态机 currentState（transition 内同步更新，唯一可靠真相源），不依赖 item.status 的 EventBus→StoreEventAdapter 更新链；(2) 去掉所有 remove 逻辑，canTransition 失败只 continue；(3) 已有状态机不在 waiting 状态时直接 skip。关键：`transition()` 内部 currentState 在 entry 钩子之前同步更新，`notifyListeners` 是 queueMicrotask 异步
- **第五轮教训（7.2 统一并发槽位口径，2026-06-23）**：`StateChangeHandler.handleUploadingState()` 中的 `while (activeUploads >= MAX)` 等槽 + 手工 `increment/decrement` 与 `startWaiting()` 的 `countByStates` 两套口径并存会导致卡槽、超发、暂停/取消/失败后槽位泄漏。修复：handleUploadingState 不再参与并发控制（删除 while 等槽、删除全部 increment/decrement），槽位释放由状态机状态自然变化实现（uploading→merging/completed/error 后 countByStates 不再统计）。RecoveryCoordinator 和 DebounceController 的 activeUploads 判断也改为 countByStates。activeUploads 字段保留标注 @deprecated，不参与调度。测试注意：UploadCoordinator 使用 @action 装饰器，CRA jest 未启用 decorators（config-overrides 的 addDecoratorsLegacy 只作用于 webpack），测试中提取 startWaiting 核心逻辑为无装饰器辅助函数

---

## 抽屉化历史（参考）

### 抽屉化（仿百度网盘）
- 收起态：底部居中小条（fixed, bottom:0, left:50%, h=40px）
- 展开态：antd Drawer placement="bottom" + 可调高度（240-720px）
- 触发：右上角图标 / 点击小条 / Ctrl+Shift+U

### 抽屉增强（手写拖拽把手 + 闪烁提示）
- DrawerDragHandle 用 `document.addEventListener` 全局监听
- 高度 < 120px 时自动触发收起
- `componentWillUnmount` 必解绑
- MiniBar 闪烁：失败红/完成绿，1.5s 动画，仅收起态闪烁

### 键盘快捷键（KeyboardShortcuts.js，175 行）
- 5 个快捷键：Ctrl+Shift+U/P/R/C + Shift+/
- isInEditableElement() 检测输入控件不响应
- SHORTCUTS 配置化数组
