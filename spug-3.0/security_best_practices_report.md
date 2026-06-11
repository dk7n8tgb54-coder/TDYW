# 资料库模块安全最佳实践审计报告

审计日期：2026-06-11

## 执行摘要

本次审计范围为资料库模块，重点检查 `spug_api/apps/document` 后端、`spug_web/src/pages/document` 前端，以及与该模块相关的认证、预览、上传、下载、异步任务和健康检查入口。项目后端是 Django，自定义 `x-token` 鉴权；前端是 React/JavaScript。

主要结论：资料库模块已经在多处做了租户过滤、文件名校验和路径安全检查，但仍存在若干会影响文件保密性和任务隔离的高优先级问题。最需要优先处理的是异步打包下载只校验 `task_id`、预览链路把 `x-token` 放进 URL，以及部分上传/传输记录更新没有在服务层绑定当前用户。

## Critical

本次未发现可直接证明为 Critical 的问题。

## High

### H-1 异步文件夹打包结果只凭 task_id 下载，缺少当前用户/租户绑定校验

Rule ID: DJANGO-AUTHZ-001 / DJANGO-PATH-001

Severity: High

Location:
- `spug_api/apps/document/views/folder/download.py:313`
- `spug_api/apps/document/views/folder/download.py:324`
- `spug_api/apps/document/views/folder/download.py:383`
- `spug_api/apps/document/views/folder/download.py:394`
- `spug_api/apps/document/tasks/pack.py:77`
- `spug_api/apps/document/tasks/pack.py:82`

Evidence:

```python
task = AsyncResult(form.task_id, app=pack_folder_to_zip.app)
...
result = task.result
zip_path = result.get('zip_path')
...
response = StreamingHttpResponse(
    self._file_iterator(zip_path, chunk_size=65536),
    content_type='application/zip'
)
```

```python
final_path = os.path.join(PACK_TASKS_DIR, f'pack_{folder_id}_{user_id}_{self.request.id}.zip')
return {
    'status': 'success',
    'zip_path': final_path,
    'zip_size': zip_size,
    'folder_name': folder.name,
    'task_id': self.request.id
}
```

Impact:

如果用户获取、猜测、日志泄露或前端暴露了其他用户的 Celery `task_id`，即可调用 `folder/download/ready/?task_id=...` 下载对方已打包完成的 ZIP 文件。因为下载端没有校验任务结果中的 `user_id`、`tenant_id`、`folder_id` 或 `is_public` 是否属于当前用户，这属于典型对象级授权缺失。

Fix:

异步打包任务返回结果中加入 `user_id`、`tenant_id`、`folder_id`、`is_public`，`FolderDownloadStatusView` 和 `FolderDownloadReadyView` 在读取 `task.result` 后必须比较当前 `request.user`。例如普通用户必须满足 `result.user_id == request.user.id` 且私有空间 `result.tenant_id == request.user.tenant_id`；管理员例外也应明确限制策略。`zip_path` 还应使用 `is_safe_path(PACK_TASKS_DIR, zip_path)` 复核。

Mitigation:

缩短 Celery result TTL 和打包文件保留时间；避免在前端、日志、错误消息中暴露完整 `task_id`；下载成功后立即清理 ZIP。

False positive notes:

如果 Celery task id 有额外网关级一次性绑定机制，当前代码中不可见，需要在运行环境验证。就代码证据而言，下载端只依赖 `task_id`。

### H-2 预览 URL 将长期 x-token 放入查询参数，容易通过日志、Referer、第三方预览服务泄露

Rule ID: REACT-CONFIG-001 / REACT-NET-001 / DJANGO-LOG-001

Severity: High

Location:
- `spug_web/src/pages/document/PreviewModal.js:278`
- `spug_web/src/pages/document/PreviewModal.js:375`
- `spug_web/src/pages/document/PreviewModal.js:384`
- `spug_web/src/pages/document/PreviewModal.js:398`
- `spug_api/apps/document/views/file/preview.py:420`
- `spug_api/libs/middleware.py:43`

Evidence:

```javascript
src={`/api/document/preview/?id=${file.id}&x-token=${X_TOKEN}&is_public=${isPublic}`}
```

```python
params = {
    'id': file.id,
    'x-token': request.META.get('HTTP_X_TOKEN', ''),
    'is_public': str(form.is_public).lower(),
}
file_url = f"{kkfileview_server_url}/api/document/preview/?{urlencode(params)}"
```

```python
access_token = request.headers.get('x-token') or request.GET.get('x-token')
```

Impact:

`x-token` 是用户访问令牌，当前实现允许放在 URL 查询参数中。URL 会进入浏览器历史、反向代理访问日志、第三方 Office 预览服务请求记录，并可能通过 iframe/资源请求 Referer 外泄。令牌泄露后，攻击者可在有效期内以该用户身份访问接口。

Fix:

预览接口不要接受 `GET x-token` 作为常规认证方式。图片、音视频、PDF 预览可改用短期一次性预签名 preview token，绑定 `file_id`、`user_id`、`tenant_id`、`is_public`、过期时间和用途；服务端验证后再流式返回文件。Office 预览给 kkFileView 的 URL 同样应使用一次性服务端令牌，而不是用户 `x-token`。

Mitigation:

立即降低 URL token 有效期，过滤访问日志中的 `x-token`，给预览响应增加 `Referrer-Policy: no-referrer` 或至少 `same-origin`，并清理前端中所有 `?x-token=` 拼接点。

False positive notes:

如果部署层保证所有访问日志脱敏且 kkFileView 完全受信任，此风险会降低，但 URL 中承载长期用户令牌仍不符合安全最佳实践。

## Medium

### M-1 上传完成/合并流程中的 transfer_id 服务层更新缺少当前用户约束

Rule ID: DJANGO-AUTHZ-001

Severity: Medium

Location:
- `spug_api/apps/document/services/file_upload_service.py:120`
- `spug_api/apps/document/services/file_upload_service.py:139`
- `spug_api/apps/document/services/file_upload_service.py:228`
- `spug_api/apps/document/views/upload/merge.py:207`
- `spug_api/apps/document/views/upload/merge.py:209`
- `spug_api/apps/document/views/upload/merge.py:365`

Evidence:

```python
transfer = DocumentTransfer.objects.filter(id=int(transfer_id)).order_by().first()
if transfer:
    transfer.status = TransferStatus.COMPLETED.value
    transfer.file_path = file_path
```

```python
transfer = DocumentTransfer.objects.select_for_update().filter(id=transfer_id).order_by().first()
if transfer:
    result = _build_result_from_transfer(transfer)
```

```python
DocumentTransfer.objects.filter(id=transfer_id).update(
    celery_task_id=task_id,
    status=TransferStatus.MERGING.value
)
```

Impact:

调用方传入的 `transfer_id` 在这些服务/合并路径里没有始终绑定 `request.user` 和 `tenant_id`。攻击者如果知道其他人的传输记录 ID，可能更新其状态、写入自己的文件路径，或通过幂等查询读取他人的合并状态。虽然部分入口在上传分片阶段做了用户过滤，但服务层本身没有防线，容易被后续新入口复用时引入 IDOR。

Fix:

将 `transfer_id` 查询统一封装为 `get_owned_transfer(transfer_id, user, for_update=False)`，所有读写都要求 `user_id` 和 `tenant_id` 匹配，管理员例外显式处理。`mark_transfer_completed`、`check_idempotency`、`save_task_id_to_transfer` 都应接收 `user` 并在 SQL 过滤条件中加入 `user=user` 与私有空间 `tenant_id=user.tenant_id`。

Mitigation:

加入回归测试：用户 A 不能通过用户 B 的 `transfer_id` 更新、查询、取消、删除或复用传输记录。

False positive notes:

如果前端永远只传自己的 `transfer_id`，正常流程不会触发越权。但安全边界必须在后端强制。

### M-2 未认证健康检查端点暴露数据库/Celery 状态和异常细节

Rule ID: DJANGO-LOG-001 / DJANGO-AUTHZ-001

Severity: Medium

Location:
- `spug_api/spug/settings.py:281`
- `spug_api/spug/settings.py:285`
- `spug_api/apps/document/views/health.py:25`
- `spug_api/apps/document/views/health.py:44`
- `spug_api/apps/document/views/health.py:66`
- `spug_api/apps/document/views/health.py:267`

Evidence:

```python
AUTHENTICATION_EXCLUDES = (
    ...
    re.compile('/document/health/.*'),
    re.compile('/api/document/health/.*'),
)
```

```python
response_data = {
    'status': 'error' if has_error else 'ok',
    'checks': checks,
}
```

```python
return {
    'status': 'error',
    'error': str(e)
}
```

Impact:

任何未登录访问者都可以读取资料库健康检查、数据库连通性和 Celery 状态。当异常发生时，响应可能包含底层数据库错误字符串。这些信息可辅助攻击者判断系统组件、故障窗口、依赖服务状态或内网配置。

Fix:

将公开健康检查拆成极简 `/healthz`，只返回 `ok`/`error` 和 HTTP 状态；详细组件状态必须加认证或限制为内网/监控网段。异常响应不要返回 `str(e)` 给未认证用户。

Mitigation:

在 Nginx/网关层限制 `/api/document/health/*` 来源 IP；生产日志和响应中避免暴露数据库错误细节。

False positive notes:

如果这些端点仅在内网监控网络可访问，风险降低。当前代码层面未体现访问来源限制。

### M-3 自定义 Origin 检查对缺失 Origin/Referer 放行，不能等价替代 Django CSRF 中间件

Rule ID: DJANGO-CSRF-001

Severity: Medium

Location:
- `spug_api/spug/settings.py:77`
- `spug_api/spug/settings.py:81`
- `spug_api/libs/csrf_protection.py:41`
- `spug_api/libs/csrf_protection.py:53`
- `spug_api/libs/csrf_protection.py:67`

Evidence:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'libs.middleware.AuthenticationMiddleware',
    'libs.csrf_protection.OriginCheckMiddleware',
    ...
]
```

```python
if not origin and not referer:
    return True
```

```python
if settings.DEBUG:
    ...
    return None
```

Impact:

项目没有使用 Django 原生 `CsrfViewMiddleware`，而自定义 Origin/Referer 校验在缺失两个头时直接放行。若认证方式未来引入 Cookie，或浏览器/代理场景导致来源头缺失，状态变更接口的 CSRF 防护会不完整。当前主要使用自定义 `x-token` 头，浏览器跨站表单难以带该头，风险低于 Cookie 会话，但实现容易让后续维护者误以为已具备完整 CSRF 防护。

Fix:

明确认证模型：如果完全使用非 Cookie 的 `x-token` Header，可在文档中说明 CSRF 威胁边界，并禁止 GET token 认证。若存在 Cookie/同站凭据，启用 Django `CsrfViewMiddleware` 或实现同步令牌/双提交令牌。生产环境对状态变更请求缺失 Origin/Referer 应审慎拒绝或要求 CSRF token。

Mitigation:

为所有 POST/PUT/PATCH/DELETE API 写一组安全测试：无 `X-Token`、跨 Origin、缺失 Origin/Referer 的行为必须符合预期。

False positive notes:

该项是防护完整性风险，不代表当前所有状态变更接口都能被 CSRF 利用。

## Low / Informational

### L-1 公共空间无租户隔离——敏感文件不应放入公共空间

Rule ID: DJANGO-AUTHZ-001

Severity: Low / Informational

Location:
- `spug_api/apps/document/views/file/download.py:42`
- `spug_api/apps/document/views/file/preview.py:97`
- `spug_api/apps/document/views/folder/views.py:91`
- `spug_api/apps/document/views/folder/views.py:95`

Evidence:

```python
file_query = FileModel.objects.filter(pk=form.id)
if not form.is_public:
    file_query = apply_tenant_filter(file_query, request.user, strict_mode=True)
```

```python
folders_query = FolderModel.objects.filter(parent__isnull=True, is_deleted=False)
if not is_public:
    folders_query = apply_tenant_filter(folders_query, request.user, strict_mode=True)
```

Impact:

公共空间是**所有租户共享**的空间，没有租户隔离——这是设计意图。任何具备 `document.document.view` 权限的登录用户均可读取/下载/预览公共空间中的文件和目录，无论其属于哪个租户。写操作多处限制为创建者或管理员。代码中 `is_public` 时跳过 `apply_tenant_filter` 的逻辑是正确的。

当前行为符合设计，但需注意：如果用户误将敏感文件放入公共空间，其他租户用户即可访问。建议在 UI 和文档中明确标注公共空间的跨租户可见性。

Fix:

无需代码修改。建议：
1. 在公共空间上传界面或目录页增加提示，明确标注"此空间所有租户可见，请勿上传敏感文件"。
2. 在产品文档和权限模型中明确公共空间的定义和适用场景。
3. 如未来需要按租户隔离公共空间，则需在所有读路径（列表、搜索、下载、预览、打包、回收站）增加租户过滤，但这与当前设计意图冲突。

Mitigation:

在 UI 中对公共空间增加醒目的跨租户可见性提示，避免用户误上传敏感文件。

False positive notes:

这不是漏洞，而是设计意图的记录。公共空间无租户隔离是产品定义，代码实现正确。

## 正向观察

- 文件路径读写多处使用 `is_safe_path()`，例如下载、预览、打包和分片目录，能降低路径遍历风险。
- 文件/目录名禁止 `..`、斜杠、反斜杠、冒号等危险字符。
- 私有空间多处通过 `apply_tenant_filter(... strict_mode=True)` 做租户过滤。
- 公共空间是所有租户共享空间（无租户隔离），读操作对所有登录用户开放是设计意图；写操作多处使用 `check_public_space_permission()` 限制创建者或管理员。
- 前端资料库模块未发现明显的 `dangerouslySetInnerHTML`、`eval`、`innerHTML` 注入类高危 sink。

## 建议修复顺序

1. 修复 H-1：异步打包下载必须绑定当前用户/租户，并复核 ZIP 路径。
2. 修复 H-2：移除 URL 中的用户 `x-token`，改为短期预签名预览 token。
3. 修复 M-1：统一 `DocumentTransfer` 归属校验服务层，补 IDOR 回归测试。
4. 收敛 M-2：公开健康检查最小化，详细状态加认证或网段限制。
5. 明确 M-3 策略并补安全测试；L-1 为设计意图记录，建议 UI 增加公共空间跨租户可见性提示。
