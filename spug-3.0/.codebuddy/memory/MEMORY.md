# 项目记忆

## 运行环境
- Docker 在 WSL 中。容器 `tdyw-test`（镜像 `tdyw:django42-stage2`），项目路径 `/data/spug/spug_api`，Python 3.10
- WSL docker 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check'`（单引号避免内层双引号 EOF）
- spug_web 使用 **antd 4.21.5**（Modal 用 `visible` 属性）；装饰器 legacy + class properties（mobx `@observable`/`@action`）

## 数据库迁移纪律 ⚠️ 重要
```bash
# 生成（指定 app + 手动命名，避免 0006_auto_xxx）
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations <app> --name <语义化>
# 执行
docker exec tdyw python /data/spug/spug_api/manage.py migrate <app>
```
1. 一个功能 PR 尽量只产生一个 migration；schema/data migration 分开
2. **`makemigrations` 不指定 app 会扫描全部 app 污染迁移历史**，误生成立即删除
3. 加唯一约束拆步：先加非唯一字段 → 回填 → 检查重复 → 再 AlterField 加 unique
4. **CharField→Date/DateTimeField 迁移必须先清洗空串** `filter(col='').update(col=None)`
5. **MariaDB 10.8.2**：不支持部分唯一索引 WHERE 条件；`unique_key` 字段（MD5）+ is_deleted=True 时设 NULL 规避
6. `db_index=True` 与 `Meta.indexes` 同字段会生成两套索引；手写 migration 的 Index name 必须与 model 一致
7. 租户隔离用 `TenantModelMixin` / `TenantModelManager` / `make_tenant_id`

## 代码验证流程（post-write-verification skill）
1. `read_lints(paths=[...])`
2. Python 语法：`docker exec tdyw-test python -m py_compile <path>`（容器无 node）
3. JS 语法：`cd spug_web && node -e "const p=require('@babel/parser');p.parse(code,{sourceType:'module',plugins:['classProperties','decorators-legacy','dynamicImport']});"`
4. `git diff` 确认变更；针对性测试脚本（专用，验证完清理）
5. 依赖 Django 的测试**必须在 Docker 容器内执行**，Windows 本地有编码/依赖问题
6. 遇问题第一反应回查 skill 文档，而非凭直觉绕过

## 附件功能架构（2026-07-10 公共化）
- 后端 `apps/evidence/`：`EvidenceAttachment`（module+object_type+object_id 多态）+ `AttachmentService` + `attachment_preview_token.py`
- 各模块写薄接口（参考 `apps/upgrade/views/upload.py`）：校验业务对象 + 模块权限码 + 转调 AttachmentService
- 物理路径：`{MEDIA_ROOT}/{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}/{file_name}`
- 前端 `components/AttachmentManager.js` + `AttachmentUploadArea.js`（FIFO 串行队列）+ `AttachmentCountBadge.js`
- preview_token 双轨（document / attachment 按路径自动选验证器）；preview-file 端点无 @auth 靠 preview_token；middleware 用 fnmatch
- 加附件标准流程：复制 upload.py 改 MODULE/权限码 → 加 preview-url/file 视图 → 业务删除调 `soft_delete_by_object` → 前端 import AttachmentManager

## 资料库拖拽上传架构（2026-07-17）
- drop 时 `captureUploadTargetContext()` 捕获不可变快照（folderId/isPublic/tenantId/systemFolderCode），Object.freeze
- 快照写入队列项 `systemFolderCode`；后续 transfer/upload/chunk/merge 请求**优先从队列项读**，不依赖全局
- 入口：`handleFileSelect/handleFolderSelect/handleFolderEntries(entries, targetContext=null)`；按钮上传不传→入口兜底捕获
- `handleFolderEntries` 接受 `{file, relativePath, rootName}[]`，与 `handleFolderSelect` 共用 `_processFolderUpload`
- 关键文件：`components/DocumentDropUploadLayer.js`、`utils/dropUpload.js`（webkitGetAsEntry 递归，MAX_DEPTH=20）、`FolderStructureBuilder.build`
- 踩坑：traverseEntry 顶层 initialPath 必须空

## 角色委派权限边界（2026-07-05）
- 统一授权 `apps/account/role_permissions.py`：`get_assignable_roles`/`validate_assignable_role_ids`/`get_manageable_role`/`flatten_page_perms`
- `Role.tenant_id`（null=平台级）+ `is_system`；`AssignableRoleView` GET `/api/account/role/assignable/?tenant_id=`
- 平台级角色 tenant_id=null 只表示归属平台层，**不等于可分配给任意租户用户**

## 导出功能（2026-06-26）
- `libs/export_utils.py`（Excel）+ `spug_web/src/libs/exportFile.js` + `components/ExportButton.js`
- 统一机制不统一字段；Excel 后端全量；导出上限默认 10000；文件名 RFC 5987 中文编码

## Django 升级路线
- 2.2.28 → 3.2.25（完成）→ 4.2.30（完成验收）→ 5.2 LTS（待做）
- Channels 4.x：consumer `__init__` 不能访问 `self.scope`（用 `init()` 钩子）；routing 用 `Consumer.as_asgi()`；asgi.py 用 `from spug.routing import application`

## 生产环境内存分配（8G 服务器）
| 容器 | limit | reservation | 关键项 |
|---|---|---|---|
| tdyw | 2G | 512M | Django+Gunicorn(4×16)+Celery+Nginx |
| tdyw-db | 3G | 1G | innodb_buffer_pool_size=2G |
| kkfileview | 1.5G | 512M | LibreOffice |
- MySQL max_connections 8G 下 800→300

## 权限码配置
- 新功能权限码走 UI：`pages/system/role/codes.js` 加权限码组 → 角色管理勾选 → `PATCH /api/account/role/`。**不要**写 `*.sql` 预置权限。超级管理员 `is_supper` 直接放行无需配置。

## 党建文档逻辑隔离加固（2026-07-17）

**架构前提**：DocumentFolderPublic/DocumentFilePublic 是全平台共享表（无 tenant_id），党建文档通过 DocumentSystemFolder 绑定公共根目录实现逻辑隔离，**非租户级隔离**。如需每租户独立党建区，须另设计 tenant_id+code 绑定。

**统一作用域校验（services/system_scope_validators.py 重写）**：
- 核心原则：**普通模式与党建模式对称校验 + fail-closed**
- 普通公共模式执行**反向隔离**（reject 系统作用域对象），不只党建正向
- 函数：validate_file_source_scope / validate_folder_source_scope / validate_target_folder_scope / validate_file_move_scope / validate_folder_move_scope / validate_upload_target_scope / validate_transfer_scope
- validate_file_operation_scope 是 validate_file_source_scope 的向后兼容别名
- log_scope_denial 结构化安全日志（user/tenant/action/obj/scope，不含 token/路径）

**document_auth fail-closed**：非空但非法的 system_folder 直接拒绝，不回落 document.document.*

**预览令牌绑定 system_folder**：令牌载荷 `file_id:user_id:tenant_id:is_public:system_folder`（5段），旧4段令牌按更严格策略处理（视为普通模式，视图层校验文件实际作用域）

**传输记录作用域闭环**：
- TransferOwnershipValidator.validate 增加 system_folder 参数，校验客户端与记录一致
- TransferRecordValidator/ResumeUploadValidator 按 system_folder 过滤查询
- 各 transfer 视图（cancel/progress/status/delete/batch）调用 validate_transfer_request_scope
- 批量操作按请求 system_folder 过滤 transfer_ids
- 合并任务创建最终文件前 _revalidate_target_scope 重读 transfer 作用域

**DocumentSystemFolder.folder 唯一约束**：migration 0012（含重复数据预检 RunPython）；apps/document/checks.py 系统检查（code冲突/目录删除/保护状态）

**移动 TOCTOU**：file/move + folder/move 在 transaction.atomic 内写入前重校验目标作用域

**测试**：tests/test_document_scope_isolation.py（43 测试，校验器单元 + HTTP IDOR + 令牌 + 列表排除 + 搜索隔离 10 个）

**搜索隔离补充修复（2026-07-17）**：
- FolderSearchView._get_descendant_folder_ids 增加 system_folder 参数：党建模式不调用 exclude_system_folder_scope（否则排除自身后代），普通模式继续排除
- files_query 根层文件逻辑按上下文区分：只有"原始 folder_id 为空的全库搜索 + 非党建模式"才加 Q(folder_id=None)；党建/指定目录搜索只用 folder_id__in
- 关键：保存 original_folder_id（_validate_search_scope 规范化前），党建空 folder_id 会被规范化为党建根目录 ID
- 前端 SearchBox 增加 systemFolderCode prop 显式传 system_folder；DocumentIndex 党建模式传 PARTY_BUILDING_DOCUMENTS_CODE
- 教训：json_response 的 error 字段总存在（空串=成功），错误断言用 assertTrue(body.get('error'))

**修改文件清单**：29 个 .py（models/apps/document_auth/preview_token/system_scope_validators/checks/migration 0012 + 全部 file/folder/transfer/upload 视图 + tasks/merge + validators/chunk_checker）+ 1 测试文件 + 搜索隔离 3 文件（search.py/SearchBox.js/index.js）

## 反思清单（跨会话必遵）
1. 用户用反问句质疑时立即承认错误，不用话术掩盖
2. 增量改进 > 大爆炸；每轮独立可回滚、向后兼容；YAGNI > 抽象复用
3. 配置化（枚举+集合）> 散落硬编码：同字符串出现 3 处以上必须抽出
4. 参考成熟产品+行业惯例驱动设计；不预先做全套 UI 改进
5. 每次修复后主动全局扫描同类问题
6. error 字段一致性：正常状态不应有 error 字段（避免 React.memo 陈旧重渲染）
7. ESLint `no-unused-expressions` 陷阱：`obj?.method()` 报错 → 改 `if (obj) obj.method();`
8. Django `Model.save()` 签名必须 `def save(self, *args, **kwargs)`；ErrorBoundary 不暴露 error.message
9. jest 测试含装饰器模块：import `@observable` Store 触发语法错误 → 提取纯函数测试
10. 嵌套 `transaction.atomic()` 只是 savepoint，外层回滚标记丢失
11. 上传并发：状态机懒创建 + 并发槽位用 `countByStates` 读 currentState；保护阈值只做兜底
12. 资料库备份/还原：DB 与 documents 同周期；恢复顺序：停业务→恢复DB→清空documents→full→incrementals→启动→检查
