# 项目记忆

## 运行环境
- Docker 在 WSL 中。容器 `tdyw-test`（镜像 `tdyw:django42-stage2`），项目路径 `/data/spug/spug_api`，Python 3.10
- WSL docker 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py check'`（单引号避免内层双引号 EOF）
- spug_web 使用 **antd 4.21.5**（Modal 用 `visible` 属性）；装饰器 legacy + class properties（mobx `@observable`/`@action`）
- 容器挂载 `/mnt/e/TDYW/spug-3.0/spug_api -> /data/spug/spug_api`，docker exec 新进程能读最新代码；dev server 长驻进程需重启容器
- ⚠️ **named volume 嵌套遮盖 bind mount 陷阱**：compose 里 `tdyw-media:/data/spug/spug_api/media` 等 named volume 会遮盖 spug_api bind mount 的子目录，数据写进 named volume（独立于宿主机），切换 compose 项目名（dev/docker）或重建 volume 即丢失。曾导致签名文件全部丢失。media/storage/logs 应走 bind mount，勿用 named volume 遮盖

## 数据库迁移纪律 ⚠️ 重要
```bash
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations <app> --name <语义化>
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

## 账号签名公共能力（2026-07-17 第一/二阶段完成）
- 模块 `apps/signature/`：AccountSignature（账号当前绑定）+ SignatureUsage（不可变签署快照）
- 第一阶段：超管赋予/替换/停用/启用 + PNG 校验 + 预览令牌 + 账号列表无 N+1（47 测试）
- 第二阶段：apply_signature + 场景注册 + 业务快照规范化 + 历史读取（54 测试）
- **场景注册**：`SIGNATURE_SCENES = frozenset()` 生产空；测试用 `override_settings(SIGNATURE_SCENES_OVERRIDE=...)` 注入
- **apply_signature**：actor 唯一签署人来源；事务内 select_for_update 锁签名 → 重算文件 SHA256 比对 → 创建 Usage + EvidenceEvent（event_type='other'）→ 回填 evidence_event_id
- **幂等**：(tenant_id, request_id) 唯一约束 + request_fingerprint 比对；并发 IntegrityError 后重查
- **业务快照规范化**：`canonicalize_business_snapshot` 用 json.dumps(ensure_ascii=False, sort_keys=True, separators=(',',':'), allow_nan=False)；拒绝 datetime/Decimal/Model/NaN
- **历史读取**：get_usage/get_usages_for_object/get_signature_image_for_render（按固定 attachment_id 读取，禁止按 signer_user_id 查当前签名）
- **mine 接口**：只读，显式拒绝 POST/PUT/PATCH/DELETE，不接受 user_id 参数
- **EvidenceEvent 失败 → 事务回滚 Usage**（record_evidence_event 返回 None 时抛 _SignatureEvidenceError）
- 第三阶段由用户指定业务模块后才接入；部门日检查单始终排除

## 资料库拖拽上传架构（2026-07-17）
- drop 时 `captureUploadTargetContext()` 捕获不可变快照（folderId/isPublic/tenantId/systemFolderCode），Object.freeze
- 快照写入队列项 `systemFolderCode`；后续请求**优先从队列项读**，不依赖全局
- 入口：`handleFileSelect/handleFolderSelect/handleFolderEntries(entries, targetContext=null)`；按钮上传不传→入口兜底捕获
- 关键文件：`components/DocumentDropUploadLayer.js`、`utils/dropUpload.js`（webkitGetAsEntry 递归，MAX_DEPTH=20）

## 角色委派权限边界（2026-07-05）
- 统一授权 `apps/account/role_permissions.py`：`get_assignable_roles`/`validate_assignable_role_ids`/`get_manageable_role`/`flatten_page_perms`
- `Role.tenant_id`（null=平台级）+ `is_system`；`AssignableRoleView` GET `/api/account/role/assignable/?tenant_id=`
- 平台级角色 tenant_id=null 只表示归属平台层，**不等于可分配给任意租户用户**

## 导出功能（2026-06-26）
- `libs/export_utils.py`（Excel）+ `spug_web/src/libs/exportFile.js` + `components/ExportButton.js`
- 统一机制不统一字段；Excel 后端全量；导出上限默认 10000；文件名 RFC 5987 中文编码

## Django 升级路线
- 2.2.28 → 3.2.25（完成）→ 4.2.30（完成验收）→ 5.2 LTS（待做）
- Channels 4.x：consumer `__init__` 不能访问 `self.scope`（用 `init()` 钩子）；routing 用 `Consumer.as_asgi()`

## 生产环境内存分配（8G 服务器）
| 容器 | limit | reservation | 关键项 |
|---|---|---|---|
| tdyw | 2G | 512M | Django+Gunicorn(4×16)+Celery+Nginx |
| tdyw-db | 3G | 1G | innodb_buffer_pool_size=2G |
| kkfileview | 1.5G | 512M | LibreOffice |
- MySQL max_connections 8G 下 800→300

## 权限码配置
- 新功能权限码走 UI：`pages/system/role/codes.js` 加权限码组 → 角色管理勾选 → `PATCH /api/account/role/`。**不要**写 `*.sql` 预置权限。超级管理员 `is_supper` 直接放行无需配置。

## 权限缓存版本校验机制（2026-07-17）
- `User.page_perms` Redis 缓存 `perms_{user.id}`，值=`(version, perms)` tuple，TTL 300s 兜底
- `Role.perms_version`（PositiveIntegerField）：`Role.save()` 检测 page_perms 变化（对比 DB 旧值）时自增，update_fields 透传
- 缓存命中条件：`max(用户各角色 perms_version)` 与缓存 version 一致；不一致或旧格式（set 实例）即重算
- 根治了原 `if data:` 短路 + 空集合失效信号的缺陷：迁移/SQL/竞态等任何漏 clear_perms_cache 路径写入的残缺缓存，靠 version 比对自动失效
- `clear_perms_cache` 改为 `cache.delete`（立即失效优化，向后兼容）；RoleView.patch 必须**先 save 后 clear**（避免清缓存-持久化窗口的竞态）
- migration 0007 历史角色 version 初始化为 1；0 仅表示未 save 新实例
- 遗留：运维 SQL（如 document/permissions.sql）直接改 page_perms 不 bump version，需手动清缓存

## 党建文档逻辑隔离（2026-07-17 已完成）
- DocumentFolderPublic/DocumentFilePublic 全平台共享表（无 tenant_id），党建通过 DocumentSystemFolder 绑定公共根目录实现逻辑隔离
- services/system_scope_validators.py 统一校验（普通/党建对称 + fail-closed）；预览令牌 5 段含 system_folder
- DocumentSystemFolder.folder 唯一约束 migration 0012；移动 TOCTOU 在 transaction.atomic 内重校验
- 搜索隔离：_get_descendant_folder_ids 增加 system_folder 参数；files_query 区分全库搜索/指定目录
- 教训：json_response 的 error 字段总存在（空串=成功），错误断言用 assertTrue(body.get('error'))

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
11. 上传并发：状态机懒创建 + 并发槽位用 `countByStates` 读 currentState
12. 资料库备份/还原：DB 与 documents 同周期；恢复顺序：停业务→恢复DB→清空documents→full→incrementals→启动→检查
13. **测试隔离纪律（血泪教训）**：测试必须 `@override_settings(MEDIA_ROOT=tempfile.mkdtemp())` 隔离文件系统，`@override_settings(CACHES=...)` 或 setUp/tearDown `cache.clear()` 隔离 Redis。dev bind mount 下容器内 `shutil.rmtree` = 删宿主机文件；Redis 不在 Django 事务内，测试写的 `perms_{id}` 缓存永久残留且 version 可能与生产碰撞（test Role perms_version 0→1 == 生产 Role version 1）导致生产用户读到残缺权限。**跑测试前先检查 tearDown 是否动生产文件/缓存**
