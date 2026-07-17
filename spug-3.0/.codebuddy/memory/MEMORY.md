# 项目记忆

## 附件功能架构（2026-07-10 公共化改造完成）

**架构**：后端 evidence 通用底座 + 前端公共组件 + kkFileView 在线预览

**后端**：
- `apps/evidence/models.py` 的 `EvidenceAttachment`：通用表（module+object_type+object_id 多态关联）
- `apps/evidence/attachment_service.py`：通用 AttachmentService（upload/list/download/soft_delete/soft_delete_by_object/get_preview_url/preview_file_response/count）+ AttachmentConfig + PREVIEWABLE_EXTENSIONS
- `apps/evidence/attachment_preview_token.py`：附件预览令牌（绑定 attachment_id/user_id/tenant_id/module/object_type/object_id，5分钟时效）
- 各模块写薄接口（参考 `apps/upgrade/views/upload.py`），负责：校验业务对象存在 + 校验模块权限码 + 转调 AttachmentService
- evidence 不提供 views/urls（无法感知各模块权限码）

**物理路径规范**：`{MEDIA_ROOT}/{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}/{file_name}`

**前端**：`components/AttachmentManager.js`（上传/列表/下载/删除/预览，路径/权限全参数化）+ `components/AttachmentCountBadge.js`（列表页附件数量徽标）

**AttachmentManager 增强（2026-07-17）**：
- 新增公共上传区 `components/AttachmentUploadArea.js`（按钮/拖拽、FIFO 串行队列、临时状态列表、失败重试/移除、卸载保护）
- AttachmentManager 新增 Props: uploadMode(button默认)/multiple(false默认)/maxFilesPerBatch(20)/uploadHint/downloadPerm/五类请求适配器(listRequest/uploadRequest/deleteRequest/downloadRequest/previewRequest)/normalizeAttachment/renderExtraActions
- 适配器优先级 > 旧 URL Props；未传适配器走旧 URL 逻辑，旧调用方完全兼容
- 预览优先级：传入 previewRequest 时图片/PDF 也走 previewRequest（不绕下载接口）；支持 preview_type: native/image/pdf/kkfileview
- 文件名点击权限：可预览+canPreview→预览；否则 canDownload→下载；都无→纯文本
- 规章管理已迁移到增强后的 AttachmentManager（uploadMode="dragger" multiple），删除了 Form.js 重复附件实现；规章后端 _serialize_attachment 追加 file_size/uploaded_by_name/created_at（加法式无 migration）

**后续模块加附件标准流程**：① 复制 `apps/upgrade/views/upload.py` 改 MODULE/OBJECT_TYPE/权限码/Config；② 新增 preview-url 和 preview-file 视图；③ 业务对象删除时调用 `AttachmentService.soft_delete_by_object(module=..., object_type=..., object_id=...)`；④ 前端 `import { AttachmentManager } from 'components'`。无需新建附件表/service。

**技术要点**：preview_token 双轨（document 令牌 / attachment 令牌按请求路径自动选验证器）；preview-file 端点无 @auth 纯靠 preview_token 鉴权；middleware 用 fnmatch 模式匹配；kkFileView URL 全源 URL base64 编码；MEDIA_ROOT 支持环境变量覆盖；下载鉴权 `x-token`、预览鉴权 `preview_token`；软删除保留物理文件和 DB 记录。

## Django 升级路线（2026-06-27 进行中）
- 总路线：2.2.28 → 3.2.25（完成）→ 4.2.30（完成验收）→ 5.2 LTS（待做）
- 容器 `tdyw-test`（镜像 `tdyw:django42-stage2`），项目路径 `/data/spug/spug_api`，Python 3.10
- Channels 4.x 升级三要素：consumer `__init__` 不能访问 `self.scope`（改 `init()` 钩子）；routing 用 `Consumer.as_asgi()`；asgi.py 用 `from spug.routing import application`
- 遗留：settings.py 的 CELERY_TASK_ROUTES 任务名与资料库 cleanup 重构后路径不一致（非阻断）

## 项目规范

### 数据库迁移纪律 ⚠️ 重要（2026-06-28 约定）
```bash
# 生成（指定 app + 手动命名，避免 0006_auto_xxx）
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations <app> --name <语义化>
# 执行
docker exec tdyw python /data/spug/spug_api/manage.py migrate <app>
```
1. 一个功能 PR 尽量只产生一个 migration（同 PR 模型改动合并）
2. migration 文件手动 `--name` 语义化命名
3. schema migration 与 data migration 尽量分开
4. CI：`makemigrations --check --dry-run`（有未提交模型变更则失败）；`migrate --plan`
5. **`makemigrations` 不指定 app 会扫描全部 app 污染迁移历史，误生成立即删除**
6. 加唯一约束必须拆步：先加非唯一字段 → 回填 → 检查重复 → 再 AlterField 加 unique
7. **CharField→Date/DateTimeField 迁移必须先清洗空串** `filter(col='').update(col=None)`，否则 ALTER 失败或产生 `0000-00-00`
8. **`db_index=True` 与 `Meta.indexes` 同字段单列索引会生成两套索引**（Django 不去重）；`Meta.indexes` 只用于复合/自定义命名
9. **手写 migration 的 Index name 必须与 model `Meta.indexes` 的 name 一致**，否则 Django 生成 rename index 迁移

### Docker / WSL
- 容器内项目路径 `/data/spug/spug_api/`
- WSL docker 调用（本机 docker 在 WSL 中）：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check'`（单引号避免内层双引号 EOF）

### 代码验证流程（post-write-verification skill）
1. `read_lints(paths=[...])`
2. Python 语法：`docker exec tdyw-test python -m py_compile <path>`（容器是 Python 容器，无 node）
3. JS 语法（ES Module + 装饰器 + classProperties）：`cd spug_web && node -e "const p=require('@babel/parser');p.parse(code,{sourceType:'module',plugins:['classProperties','decorators-legacy','dynamicImport']});"`
4. `git diff` 确认变更
5. 针对性测试脚本（专用，验证完清理）

### antd / 前端
- spug_web 使用 **antd 4.21.5**（Modal 用 `visible` 属性，不是 antd5 的 `open`）
- 装饰器用 legacy decorators + class properties（mobx `@observable`/`@action`）

### 数据库 / 技术约束
- **MariaDB 10.8.2**：不支持部分唯一索引 WHERE 条件，`UniqueConstraint(condition=Q(...))` 静默跳过。解决方案：`unique_key` 字段（MD5 哈希），is_deleted=True 时设为 NULL（MySQL 中 NULL 不参与唯一索引）
- 租户隔离用 `TenantModelMixin` / `TenantModelManager` / `make_tenant_id`

### 重构方法论（用户偏好）
- 渐进式重构 > 大爆炸；修 P1 > 重构架构；YAGNI > 抽象复用；关注点分离 > DRY；测试驱动 > 凭直觉
- 用户倾向：先给完整方案写入 MD，认可后再实施；每次修复后主动全局扫描同类问题

## 角色委派权限边界（2026-07-05）
- 问题：普通管理员可看到并分配超管创建的高权限角色 → 越权授权
- 统一授权方法 `apps/account/role_permissions.py`：`get_assignable_roles` / `validate_assignable_role_ids`（超管校验租户角色与目标租户一致性）/ `get_manageable_role` / `flatten_page_perms` 等子集校验
- `Role` 增加 `tenant_id`（null=平台级）+ `is_system`；`to_dict()` 显式输出
- 账号可分配角色下拉 `GET /api/account/role/assignable/?tenant_id=`（`AssignableRoleView`，`PERM_MAP={'GET':'system.account.view}`）
- 平台级角色 `tenant_id=null` 只表示归属平台层，**不等于可分配给任意租户用户**；`get_assignable_roles_for_target` 收紧为不返回平台级普通角色

## 导出功能架构（2026-06-26）
- 公共工具：`libs/export_utils.py`（Excel）、`spug_web/src/libs/exportFile.js`、`spug_web/src/components/ExportButton.js`
- 原则：统一导出机制不统一业务字段；Excel 后端全量导出；PDF 保留专用模板；导出上限默认 10000
- 文件名 RFC 5987 中文编码（`filename*=UTF-8''`）

## 生产环境内存分配（8G 服务器，2026-06-29）
| 容器 | memory limit | reservation | 关键项 |
|---|---|---|---|
| tdyw | 2G | 512M | Django+Gunicorn(4×16)+Celery+Nginx |
| tdyw-db | 3G | 1G | innodb_buffer_pool_size=2G |
| kkfileview | 1.5G | 512M | LibreOffice |
- MySQL `max_connections` 8G 下 800→300；16G 服务器可恢复原配置

## 反思清单（2026-06-06 固化，跨会话必遵）

1. **用户用反问句质疑时立即承认错误**，不用漂亮话术掩盖（宁可承认错 5 次）
2. **增量改进 > 大爆炸式重写**：每轮独立可回滚、向后兼容
3. **配置化（枚举+集合）> 散落硬编码**：同一字符串/状态出现 3 处以上必须抽出来
4. **参考成熟产品 + 行业惯例驱动设计**（消除"过度设计"）：新需求前先问"百度/阿里/Dropbox 怎么做"
5. **不要预先做全套 UI 改进**：用户没问的绝不主动加；推进顺序：确认→实施→验证→等下一反馈
6. **每次修复后主动全局扫描同类问题**（这是"还有其他吗"的标准答案）
7. **error 字段一致性**：正常状态不应有 error 字段，错误状态才设置（避免 React.memo 陈旧重渲染）
8. **MD5 是内部技术细节不该暴露**（"计算中"→"准备上传"+tooltip）；但"合并中"必须显示（耗时长、无 progress）
9. **错误分类决定 UX**：权限/配额错误无重试按钮；网络错误有重试按钮
10. **手写拖拽用 `document.addEventListener` 且 `componentWillUnmount` 必解绑**；高度 < 120px 触发收起
11. **键盘快捷键不响应输入控件**：`isInEditableElement()` 检测 input/textarea/select/contenteditable；Mac 用 `e.ctrlKey || e.metaKey`；`useEffect` 单一挂载点
12. **Skill 流程 > 个人直觉**：遇问题第一反应回查 skill 文档；依赖 Django 的测试必须在 Docker 容器内执行
13. **ESLint `no-unused-expressions` 陷阱**：`obj?.method()` 视为表达式语句报错 → 改 `if (obj) obj.method();`
14. **Django `Model.save()` 签名必须 `def save(self, *args, **kwargs)` 不丢 `*args`**；ErrorBoundary 不暴露 error.message
15. **jest 测试含装饰器的模块**：import 含 `@observable` 的 Store 会触发 `decorators` 语法错误（jest babel 不含装饰器插件）→ 提取纯函数到独立模块测试
16. **jsdom sessionStorage mock**：直接赋值 `sessionStorage.getItem = jest.fn()` 可能不生效 → 用 `setItem`/`clear` 替代

## 资料库拖拽上传架构（2026-07-17 实现完成）

**功能**：资料库（普通文档 + 党建文档）支持拖拽上传多文件/文件夹/混合，复用现有上传队列，状态只展示在现有 MiniBar/UploadPanel。

**核心机制 — 目标上下文固化（targetContext）**：
- drop 时 `uploadCoreStore.captureUploadTargetContext()` 捕获不可变快照（folderId/isPublic/tenantId/systemFolderCode），Object.freeze 保护
- 快照写入每个队列项 `queueItem.systemFolderCode`
- 后续 transfer create / file upload / chunk upload / merge / merge_status / folder create 请求**优先从队列项读 systemFolderCode**，不依赖全局 `systemFolderContext`（党建任务离开党建路由后仍携带正确上下文）
- 纯函数提取：`stores/upload/core/captureUploadTargetContext.js`（便于测试，避免装饰器 babel 问题）

**入口扩展（向后兼容）**：
- `handleFileSelect(files, targetContext=null)` / `handleFolderSelect(files, targetContext=null)` / `handleFolderEntries(entries, targetContext=null)`
- 按钮上传不传 targetContext → 入口兜底捕获；拖拽上传显式传入
- `handleFolderEntries` 接受 `{file, relativePath, rootName}[]`（拖拽 webkitGetAsEntry 路径），与 `handleFolderSelect`（File[] 带 webkitRelativePath）共用 `_processFolderUpload`

**systemFolderCode 双轨**：队列项有值用队列项（拖拽固化），无值回退全局 systemFolderContext（按钮上传老逻辑）

**关键文件**：
- `components/DocumentDropUploadLayer.js` — 投放层（深度计数、遮罩、禁用提示）
- `utils/dropUpload.js` — DataTransfer 递归解析（webkitGetAsEntry，循环 readEntries，MAX_DEPTH=20，MAX_ENTRIES=5000）
- `FolderStructureBuilder.build(filesOrEntries, rootTargetId, isPublic, systemFolderCode)` — 支持两种格式 + 显式 system_folder

**踩坑**：traverseEntry 顶层目录 initialPath 必须为空（isDirectory 分支会拼 entry.name，非空会导致 'root/root' 重复）

## 关键教训（来自具体修复）
- **迁移加唯一约束必须拆步**（先非唯一→回填→查重→加 unique）
- **嵌套 `transaction.atomic()` 只是 savepoint**，外层回滚时标记会丢失，注释须如实说明
- **冲突检查要和约束规则一致**（公共空间 unique_key 不含 created_by，冲突检查也不能按 created_by 过滤）
- **上传并发**：状态机懒创建 + 并发槽位用 `countByStates` 读状态机 currentState（唯一可靠真相源），不依赖 item.status；保护阈值只做异常兜底
- **资料库备份/还原一致性**：DB 与 documents 同周期；恢复顺序：停业务→恢复DB→清空documents→full→incrementals→启动→一致性检查
- **PowerShell 环境**：`npx`/`head` 不可用；`node --check` 不支持 ESM `import`；C:\temp 写入受限改工作区根目录
- **权限码配置走 UI 而非 SQL**：新功能只需在 `pages/system/role/codes.js` 加权限码组，`角色管理-功能权限`弹窗(`PagePerm.js` 遍历 codes 渲染勾选树)即出现该组,超级管理员勾选保存经 `http.patch('/api/account/role/', {page_perms})` 写回角色。**不要**为角色预置权限写 `*.sql`(如误建的 `home/permissions.sql` 已删)。`document/radio_license` 的 `permissions.sql` 只是后期补权限的手动 convenience 脚本,不被部署引用,非新功能范本。超级管理员(`is_supper`)在所有 `hasPermission` 判断直接放行,无需配置即见菜单。
