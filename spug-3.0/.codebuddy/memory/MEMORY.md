# 项目记忆

## 运行环境
- Docker 在 WSL；`tdyw` 容器（镜像 tdyw:0720）路径 `/data/spug/spug_api`，Python 3.10；**无 bind mount**，改代码需 `docker cp`
- WSL 调用：`wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw python manage.py check'`（单引号护内层双引号）
- spug_web：antd 4.21.5（Modal 用 `visible`）+ legacy 装饰器 + class properties（mobx `@observable`/`@action`）
- ⚠️ named volume 遮盖 bind mount 子目录陷阱：media/storage/logs 走 bind mount
- ⚠️ Docker 内网回调：kkFileView 经 `http://tdyw` 回源，容器名须进 ALLOWED_HOSTS；`.env` 已配 `ALLOWED_HOSTS=...,tdyw` + `ALLOWED_ORIGINS=...,http://tdyw`

## 后端测试（2026-07-20）
- 10 app 有测试(465 全绿)：department_duty_log/radio_license/regulation/signature/logs/setting/account/checksheet(废弃)/interference
- 7 app 冒烟模板(2 each)：contract_agreement/device/duty/home/runlog/upgrade/fault
- 6 app 无测试：document(极复杂待补)/evidence(无 HTTP 入口)/exec/schedule/safety_question_bank
- 辅助 `apps/utils/test_helpers.py`；运行 `docker exec ... tdyw python manage.py test apps.xxx.tests --noinput`

## 压测 locust（2026-07-20/21）
- runner `./locustfile/run_all_locust.sh [--all|--only <name>|--list]`；SLA `locustfile/SLA_THRESHOLDS.md`；共用 `_common.py`（`TokenSharedHttpUser` token 池 + `_get/_post/_patch/_delete` catch_response 块）
- 镜像：`locustio/locust:latest` 本地需存在（Docker Hub 直连超时→`docker save/load` 或 `LOCUST_IMAGE=` 覆盖）；Docker 守护进程仅 WSL 可访问

## 测试编写要点（血泪）
1. access_token 必须 32 字符（中间件 `len!=32` 拒）；2. Role.created_by NOT NULL 必传；3. User.tenant_id 默认 'admin'/AuditLog 'default'；4. make_user 设 version=0；5. json_response 错误时 data=''；6. update_by_dict 过滤 None（`{k:v for...if v is not None}`，已修 9 视图），测试模拟真实部分字段；7. POST 创建+编辑共用 JsonParser 用 required=False+创建手校+编辑过滤 None；8. 中文文件名 RFC2047 编码→`email.header.decode_header`；9. USE_TZ=False 禁 `make_aware` 用 naive；10. 隔离 `@override_settings(MEDIA_ROOT=tempfile.mkdtemp())`+`cache.clear()`；11. test client 路径无 `/api/` 前缀；12. makemigrations 指定 app；13. 不为绿绕过 bug；14. 上传 post 不返回 id，前端 list 按名匹配；15. locust `with...as resp` 块外调 `resp.success()` 必抛 `LocustError`

## 迁移纪律 ⚠️
1. makemigrations 指定 app；2. 一功能一 migration，schema/data 分；3. 唯一约束拆步(加字段→回填→查重→AlterField unique)；4. CharField→Date/DateTime 先洗空串 `filter(col='').update(col=None)`；5. MariaDB10.8.2 不支持部分唯一索引，is_deleted=True 设 NULL；6. db_index 与 Meta.indexes 同字段生成两套索引；7. 租户 TenantModelMixin/Manager/make_tenant_id；8. fresh 库 133 迁移全通过(54 表)

## 批量删除陷阱 ⚠️
- QuerySet 切片惰性重查，删循环绝不用 `range(count)+qs[start:end]`（OFFSET 跳过→残留→on_delete=SET_NULL 散落根目录）；用 `while True: batch=list(qs.exclude(id__in=failed_ids)[:BATCH]); if not batch: break` + max_iterations 安全阀。血案：`_delete_folder` BATCH_SIZE=50 致 >50 文件散落根目录（2026-07-21 修）

## 代码验证流程（post-write-verification skill）
1. `read_lints`；2. py: `docker exec tdyw python -m py_compile <path>`；3. js: `node -e "@babel/parser" (classProperties/decorators-legacy/dynamicImport/jsx)`；4. `git diff`；5. Django 测试必在容器内；6. 遇问题先查 skill 文档而非凭直觉

## 模块架构速查
- 附件 `apps/evidence`（EvidenceAttachment 多态 + AttachmentService + preview_token；路径 `{MEDIA_ROOT}/{module}/{tenant}/{yyyyMM}/{type}_{id}/{name}`）
- 账号签名 `apps/signature`（apply_signature 事务锁→SHA256→Usage+EvidenceEvent；场景 `SIGNATURE_SCENES`）
- 拖拽上传 `captureUploadTargetContext()` Object.freeze；角色委派 `role_permissions.py`；导出 `libs/export_utils.py`
- 党建隔离 `DocumentSystemFolder` + `system_scope_validators`（fail-closed）
- 台站频率批复 `apps/radio_license` 复用 `calculate_license_status` 60 天阈值
- 权限缓存 `User.page_perms` Redis `perms_{id}`=(version,perms)，`Role.perms_version` 变更自增
- kkFileView `OfficePreviewUrlView` 生成 preview_url；`KKFILEVIEW_API_URL`(浏览器)/`KKFILEVIEW_SERVER_URL`(回源)
- 磁盘用量 `DiskUsageView`(disk.py) Redis 缓存 60s（按 is_public+租户分键：`private:all`/`private:{tenant_id}`/`public`，复用 `libs/cache_utils`）；私有文件表覆盖索引 `doc_pri_file_diskusage_idx=(tenant_id,is_deleted,file_size)` 服务聚合 SUM；公共表无索引靠缓存（is_deleted 选择性差）；前端 `useDiskSpace` 30s 轮询

## Celery（2026-07-20）
- 17 `@shared_task` / 5 队列；11 Beat + 6 事件触发
- `retry_clean_pending_files` 是 `is_pending_clean` 唯一消费者（仅 Beat 调度，无 `.delay()`），不可删
- 已修 3 bug：bind self / redis_client ImportError / cleanup_expired_pack_tasks 孤儿任务

## Django 升级路线
- 2.2.28→3.2.25→4.2.30(完成)→5.2 LTS(待做)；Channels4 consumer `__init__` 禁访问 `self.scope`（用 `init()` 钩子）

## 生产内存(8G)
- tdyw 2G/512M（Django+Gunicorn4×16+Celery+Nginx）；tdyw-db 3G/1G(innodb_buffer_pool 2G)；kkfileview 1.5G/512M(LibreOffice)；MySQL max_connections 300

## 权限码
- 新功能走 UI `pages/system/role/codes.js`→角色勾选→`PATCH /api/account/role/`；不写 `.sql` 预置；`is_supper` 放行

## 反思清单（跨会话必遵）
1. 反问质疑立即认错不掩盖；2. 增量>大爆炸+YAGNI+向后兼容；3. 配置化(枚举+集合)>硬编码(同串≥3处抽出)；4. 参考成熟产品+行业惯例；5. 每次修复后全局扫描同类；6. error 字段一致性(正常态无 error)；7. `obj?.method()` 触发 no-unused-expressions→`if(obj)obj.method()`；8. Model.save 签名 `def save(self,*args,**kwargs)`；9. jest 测装饰器模块报错→提取纯函数；10. 嵌套 atomic 仅 savepoint；11. 备份恢复同周期(DB→documents)；12. `from X import Y` 确认 Y 从 X 导出
