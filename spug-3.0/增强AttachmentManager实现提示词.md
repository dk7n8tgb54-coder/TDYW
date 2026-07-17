# 增强 AttachmentManager 实现提示词

> 使用方式：将以下完整内容交给编码 Agent，并要求其同时阅读项目根目录的 `文档与附件拖拽上传设计方案.md`。  
> 本提示词只实施“增强公共 AttachmentManager + 规章管理迁移”，暂不实施资料库/党建文档整页拖拽上传。

---

## 角色与任务

你是一名资深前端/全栈工程师，需要在现有 Django + React 16 + MobX + Ant Design 4 项目中，增强公共附件组件 `AttachmentManager`，使其：

1. 保持现有调用方完全向后兼容；
2. 支持按钮上传和拖拽上传两种模式；
3. 支持多文件串行上传、逐文件状态和部分失败重试；同一页面一次只上传一个附件，多个账号之间由后端自然并发；
4. 支持不同业务模块通过请求适配器接入不同形状的附件 API；
5. 支持上传、删除、下载、预览分别配置权限；
6. 将规章管理当前独立实现的附件列表、上传、下载、预览和删除迁移到增强后的 `AttachmentManager`；
7. 不改变规章附件独立数据模型、独立存储目录和现有后端鉴权边界。

完整设计背景见项目根目录：

```text
文档与附件拖拽上传设计方案.md
```

请先阅读当前源码和设计方案，再开始编辑。不要只根据本提示词猜测现有实现。

---

## 一、项目技术栈与工作约束

### 1.1 前端技术栈

- React `16.13.1`；
- Ant Design `4.21.5`；
- MobX 5 / `mobx-react` 6；
- JavaScript，不迁移 TypeScript；
- `Modal` 使用 `visible`，不能使用 Ant Design 5 的 `open`；
- 图标使用现有 `@ant-design/icons`；
- HTTP 继续使用项目的 `http` 封装和 `X_TOKEN`，不要引入新的请求库。

### 1.2 必须保护现有工作区

- 当前仓库可能存在大量未提交修改，先执行 `git status --short` 了解状态。
- 不回退、不覆盖、不格式化与本任务无关的用户修改。
- 只修改本提示词列出的相关文件及确有必要的测试文件。
- 不做全仓库格式化、目录重构或依赖升级。

### 1.3 兼容性总原则

公共组件已经被合同协议、无线电执照、升级工作台、系统公告等页面调用。**旧调用方不传任何新增 Props 时，界面和行为必须保持现状：按钮上传、默认单文件、旧 URL 拼装规则继续可用。**

不得为了适配规章管理而强制修改其他业务模块的后端接口。

---

## 二、实现前必须核对的当前代码

### 2.1 公共组件

完整阅读：

```text
spug_web/src/components/AttachmentManager.js
spug_web/src/components/index.js
```

当前公共组件的重要行为：

- `AttachmentToolbar` 使用 Ant Design `Upload` + `customRequest`；
- 上传默认 `POST uploadUrl`；
- 删除默认 `DELETE ${deleteUrl}?id=${attachment.id}`；
- 下载默认拼接 `${downloadUrlPrefix}${id}/download/?x-token=...`；
- 预览 URL 默认拼接 `${previewUrlPrefix}${id}/preview-url/`；
- 图片/PDF 当前绕过 `preview-url`，直接请求下载地址的 `inline=1`；
- 只有 `uploadPerm`、`deletePerm`、`previewPerm`，没有 `downloadPerm`；
- 使用单一 `uploading: boolean`，无法准确表达多个文件的等待、上传和失败状态；
- 默认表格字段为 `file_name`、`file_size`、`uploaded_by_name`、`created_at`。

### 2.2 规章管理前端

完整阅读：

```text
spug_web/src/pages/regulation/Form.js
spug_web/src/pages/regulation/store.js
```

当前 `Form.js` 自行维护：

```text
attachments
uploading
previewVisible
previewUrl
previewFileName
previewType
fetchAttachments
handleUpload
handleDownload
handleDeleteAttachment
handlePreview
closePreview
```

迁移完成后，上述附件专用状态和方法应从规章表单删除，由 `AttachmentManager` 统一维护；规章元数据表单、详情展示、编辑和废止逻辑不得受影响。

### 2.3 规章管理后端

完整阅读：

```text
spug_api/apps/regulation/urls.py
spug_api/apps/regulation/views.py
spug_api/apps/regulation/models.py
spug_api/apps/regulation/storage.py
spug_api/apps/regulation/tests.py
```

现有附件接口：

```text
GET    /api/regulation/<regulation_id>/attachments/
POST   /api/regulation/<regulation_id>/attachments/upload/
GET    /api/regulation/<regulation_id>/attachments/<attachment_id>/download/
GET    /api/regulation/<regulation_id>/attachments/<attachment_id>/preview-url/
GET    /api/regulation/<regulation_id>/attachments/<attachment_id>/preview-file/
DELETE /api/regulation/<regulation_id>/attachments/<attachment_id>/
```

权限边界：

| 能力 | 权限码 |
|---|---|
| 列表/预览 | `document.regulation.view` |
| 上传/删除 | `document.regulation.upload` |
| 下载 | `document.regulation.download` |

规章附件限制：

- 单文件默认最大 200MB；
- 允许 PDF、Word、Excel、PPT、文本、Markdown 和常见图片；
- 后端 `storage.py` 的 `ALLOWED_EXTENSIONS` 与 `MAX_FILE_SIZE` 是安全边界；
- 前端 `accept` 和大小校验只用于提前反馈，不能替代后端校验；
- 规章附件使用独立 `RegulationAttachment` 表和 `storage/documents/regulation/` 目录，不迁移到通用附件表。

当前 `_serialize_attachment()` 只返回：

```json
{
  "id": 1,
  "file_name": "example.pdf",
  "previewable": true
}
```

为了让公共附件表格完整展示，需要在不删除现有字段的前提下追加标准字段：

```json
{
  "file_size": 123456,
  "uploaded_by_name": "张三",
  "created_at": "2026-07-17 10:00:00"
}
```

其中 `created_at` 映射模型的 `uploaded_at`。这是加法式兼容修改，不改数据库，不生成 migration。

---

## 三、目标组件结构

建议拆成两个层次：

```text
AttachmentManager
  ├─ AttachmentUploadArea       上传按钮/拖拽、多文件队列
  ├─ AttachmentTable            可保留在同文件内，不强制拆文件
  └─ AttachmentPreviewModal     可保留在同文件内，不强制拆文件
```

新增公共组件：

```text
spug_web/src/components/AttachmentUploadArea.js
```

并在：

```text
spug_web/src/components/index.js
```

中导出。不要为了拆分而创建过多文件；只有上传区因具备独立队列和可复用价值，建议单独成文件。

---

## 四、AttachmentUploadArea 详细要求

### 4.1 Props 合同

至少支持：

```js
{
  mode: 'button' | 'dragger',       // 默认 button
  multiple: boolean,               // 默认 false
  accept: string,
  maxFileSizeMB: number,
  maxFilesPerBatch: number,        // 默认 20
  disabled: boolean,
  request: (file, context) => Promise<any>,
  onFileSuccess: (result, file) => void,
  onFileError: (error, file) => void,
  onBatchSettled: (summary) => void,
  buttonText: string,              // 默认“上传附件”
  hint: ReactNode,
}
```

`summary` 至少包含：

```js
{
  total,
  successCount,
  failedCount,
  results,
  errors,
}
```

### 4.2 上传模式

#### `mode="button"`

- 保持现有小按钮布局；
- 默认 `multiple=false`；
- 未传新 Props 的旧调用方视觉和行为不得变化。

#### `mode="dragger"`

- 使用 Ant Design 4 的 `Upload.Dragger`；
- 显示上传图标、清晰的投放文本及类型/大小提示；
- 支持点击选择文件；
- `multiple=true` 时支持一次选择或拖入多个文件；
- 不支持文件夹，业务附件没有目录语义；
- 卡片高度应紧凑，适合放入 760px/900px 的 Modal，禁止使用大面积营销式上传区。

### 4.3 校验

入队前校验：

1. 文件数量不超过 `maxFilesPerBatch`；
2. 单文件大小不超过 `maxFileSizeMB`；
3. 按 `accept` 对扩展名进行不区分大小写的预校验；
4. `disabled=true` 时不接受点击或拖入；
5. 文件为空、扩展名缺失或浏览器 MIME 不可靠时，给出明确提示，但不要用 MIME 作为唯一依据。

前端校验失败必须正确调用 Ant Upload 的失败/忽略机制，不能让文件永久停留在“上传中”。

### 4.4 串行队列和局部状态

- 不允许继续使用单一 `uploading: boolean` 表示整个批次；
- 同一个 `AttachmentUploadArea` 使用 FIFO 串行队列，任意时刻只执行 1 个 `request`；
- 不做浏览器之间的全局并发协调。不同账号在各自浏览器上传时，由 Django/Gunicorn、数据库和存储层自然处理跨账号并发；
- 每个任务用 Ant Upload `uid` 或内部稳定 ID 标识，不能只用文件名；
- 一个任务失败不终止后续任务；
- 批次全部完成后调用一次 `onBatchSettled`；
- 失败项可以单独重试，重试不得重复添加已成功项；
- 组件卸载后不得继续 `setState`；如果请求支持取消则清理取消句柄，不能因为本次改造破坏现有请求。

状态只显示在当前附件区域内，不建设全局传输列表：

```text
附件拖拽区
本次上传
  文件A.pdf    上传中
  文件B.docx   等待上传
  文件C.xlsx   上传失败  [重试] [移除]
正式附件表格
```

显示规则：

- “等待上传”和“上传中”显示在拖拽区下方的临时列表；“上传中”默认使用旋转图标，不强制实现百分比进度条；
- 上传成功后立即加入正式附件表，并从临时列表移除，不长期保留“成功”任务；批次汇总 message 负责成功反馈；
- 上传失败的任务保留在临时列表，提供重试和移除；
- 临时列表不跨页面、不跨 Modal、不写入持久化 Store；
- 不提供全局入口、暂停、恢复、断点续传或后台传输能力，因此它不是资料库的传输中心。

规章首期使用：

```text
multiple=true
maxFilesPerBatch=20
```

### 4.5 反馈规则

- 单文件按钮模式继续显示现有“上传成功/失败”反馈；
- 多文件模式不要为每个成功文件弹出一条全局 message，避免刷屏；
- 批次结束显示一次汇总，例如“8 个附件上传成功，2 个失败”；
- 失败列表保留文件名和后端返回的明确错误；
- 后端错误优先使用 `error.message`，没有时回退到“上传失败”。

---

## 五、增强 AttachmentManager 的 Props 与适配器

### 5.1 必须保持的旧 Props

以下旧 Props 继续支持，含义不变：

```text
module
objectType
recordId
listUrl
uploadUrl
deleteUrl
downloadUrlPrefix
previewUrlPrefix
readOnly
uploadPerm
deletePerm
previewPerm
maxFileSize
accept
previewableExtensions
emptyText
onCountChange
```

### 5.2 新增上传 Props

```text
uploadMode="button" | "dragger"，默认 button
multiple=false
maxFilesPerBatch=20
uploadHint
```

### 5.3 新增权限 Props

新增：

```text
downloadPerm
```

权限计算：

```js
canUpload  = !readOnly && (!uploadPerm || hasPermission(uploadPerm))
canDelete  = !readOnly && (!deletePerm || hasPermission(deletePerm))
canPreview = !previewPerm || hasPermission(previewPerm)
canDownload = !downloadPerm || hasPermission(downloadPerm)
```

要求：

- 没有下载权限时不显示下载按钮；
- 文件名点击不能绕过下载权限；
- 如果可预览则文件名点击预览；不可预览但可下载才执行下载；二者都无权限时文件名显示为普通文本或无操作文本；
- `readOnly` 只禁止上传和删除，不应自动禁止有权限的预览/下载。

### 5.4 新增请求适配器

增加以下可选 Props：

```js
listRequest: () => Promise<Attachment[]>
uploadRequest: (file, context) => Promise<Attachment>
deleteRequest: (attachment) => Promise<any>
downloadRequest: (attachment) => Promise<any>
previewRequest: (attachment) => Promise<{
  preview_url,
  file_name,
  preview_type,
}>
normalizeAttachment: (raw) => Attachment
renderExtraActions: (attachment, context) => ReactNode
```

优先级统一为：

```text
请求适配器 > 旧 URL Props 默认实现
```

例如：传了 `deleteRequest` 就不再读取 `deleteUrl`；未传则继续使用旧的 `DELETE ${deleteUrl}?id=${id}`。

适配器设计要求：

- 组件不硬编码 `regulation`；
- 不在公共组件里写 `/api/regulation/...`；
- `context` 可包含 Ant Upload 回调、进度回调等，但不能要求所有旧模块修改；
- `normalizeAttachment` 同时应用于列表响应和上传响应；
- 默认 `normalizeAttachment` 为原值透传；
- 适配器抛出的错误沿用项目现有错误展示方式。

### 5.5 预览优先级修复

当前公共组件对图片/PDF直接使用下载接口 `inline=1`。这对规章不成立，因为规章预览只要求 `view` 权限，而下载要求独立的 `download` 权限。

必须调整为：

1. 如果传入 `previewRequest`，所有可预览文件都优先调用它，不得绕到下载接口；
2. 未传 `previewRequest` 时，保持旧逻辑：图片/PDF 可使用旧下载前缀 inline，其他类型使用旧 `previewUrlPrefix`；
3. 支持后端返回 `preview_type: native | image | pdf | kkfileview`；
4. `native/pdf/kkfileview` 可用 iframe，`image` 可用 img；
5. 关闭预览时释放组件自己创建的 Blob URL；外部 URL 或后端短期 token URL不应错误 revoke。

### 5.6 下载适配

如果传入 `downloadRequest`：

- 点击下载时完全交给该函数；
- 公共组件只负责 loading/错误反馈，不再拼接 URL；
- 必须避免重复弹出错误提示：适配器和组件约定由组件统一提示，或明确采用一种单一职责。

未传时继续使用现有 `X_TOKEN` URL 下载方式。

### 5.7 删除和附件状态更新

- 删除成功后从本地 `attachments` 移除，避免无必要地重新拉取整表；
- 上传成功返回标准附件对象时加入列表；
- 多文件批次按成功结果更新列表，不能因一个失败丢弃其他成功结果；
- `onCountChange` 每次接收最终准确数量；
- 避免闭包旧状态导致连续上传时覆盖刚加入的附件。

---

## 六、规章管理迁移要求

### 6.1 前端替换目标

在规章详情 Modal 的附件区域改为增强后的 `AttachmentManager`。建议配置结构如下，具体代码按项目现状调整：

```jsx
<AttachmentManager
  module="regulation"
  objectType="regulation"
  recordId={info.id}
  listUrl={`/api/regulation/${info.id}/attachments/`}
  uploadUrl={`/api/regulation/${info.id}/attachments/upload/`}
  deleteRequest={attachment => (
    http.delete(`/api/regulation/${info.id}/attachments/${attachment.id}/`)
  )}
  downloadRequest={attachment => downloadRegulationAttachment(info.id, attachment)}
  previewRequest={attachment => (
    http.get(`/api/regulation/${info.id}/attachments/${attachment.id}/preview-url/`)
  )}
  readOnly={false}
  uploadPerm="document.regulation.upload"
  deletePerm="document.regulation.upload"
  downloadPerm="document.regulation.download"
  previewPerm="document.regulation.view"
  maxFileSize={200}
  accept={ALLOWED_ACCEPT}
  uploadMode="dragger"
  multiple
  maxFilesPerBatch={20}
/>
```

下载适配器应复用当前 `Form.js` 已验证可工作的 Blob 下载方式：

- `responseType: 'blob'`；
- 从响应 `content-type` 构造 Blob；
- 文件名使用 `attachment.file_name`；
- 创建临时 `<a>` 下载；
- 点击后移除元素并 `URL.revokeObjectURL`；
- 失败时把错误抛给公共组件统一提示。

### 6.2 删除规章重复附件代码

迁移成功后，从 `Form.js` 删除不再需要的：

- `attachments`、`uploading` 和附件预览相关 state；
- 附件列表 `useEffect` 请求；
- `fetchAttachments`；
- `handleUpload`；
- `handleDeleteAttachment`；
- `handlePreview`、`closePreview`；
- 规章页面自己渲染的附件 `Table`；
- 规章页面自己渲染的预览 `Modal`；
- 不再使用的 `Upload`、`Table`、`Popconfirm`、图标等 imports。

下载 helper 可以移到文件外的纯函数，也可以通过适配器保留，但不能继续维护第二套附件 UI 状态。

### 6.3 新建/编辑边界

- 只有 `info.id` 存在时渲染 `AttachmentManager`；
- 新建规章时不允许先上传临时附件；
- 规章元数据创建/编辑成功流程保持现状；
- 本任务不增加临时上传 token；
- 本任务不增加主附件功能，因为当前模型和接口没有 `is_primary` 能力；公共组件只预留 `renderExtraActions` 扩展点。

### 6.4 后端序列化增强

只修改 `_serialize_attachment()`，追加：

```python
'file_size': att.file_size,
'uploaded_by_name': att.uploaded_by.nickname if att.uploaded_by else '',
'created_at': att.uploaded_at,
```

上传人显示字段必须先检查本项目 `User` 模型和其他 serializer 的惯例。如果用户姓名实际字段不是 `nickname`，使用项目真实字段或已有安全辅助函数，不能凭空假设。无上传人时返回空字符串。

不要修改数据库模型，不生成 migration。

---

## 七、明确不做的事项

本次禁止扩张到以下范围：

- 不实施资料库和党建文档的 `DocumentDropUploadLayer`；
- 不改资料库分片上传、断点续传或上传队列；
- 不把规章附件迁移到 `EvidenceAttachment` 或其他通用附件表；
- 不修改规章物理存储目录；
- 不新增主附件字段或接口；
- 不默认给合同、公告、执照、升级工作台开启拖拽模式；
- 不改公共组件旧调用方的 API URL；
- 不升级 React、Ant Design、Axios 或其他依赖；
- 不顺手重构整个规章表单。

---

## 八、测试要求

### 8.1 公共组件测试

如项目已有可运行的 Jest/React 测试惯例，增加聚焦测试；如果没有成熟组件测试基础，至少完成前端构建和人工验收，并明确说明测试缺口。

至少覆盖：

1. 未传新增 Props 时渲染旧按钮模式；
2. `uploadMode="dragger"` 渲染拖拽区；
3. `multiple=false/true` 行为正确；
4. 超出文件大小、类型或批次数量时不发请求；
5. 同一个上传区任意时刻最多一个附件请求，多个文件严格按入队顺序上传；
6. 一个文件失败不阻断其他文件；
7. 批次结束只调用一次 `onBatchSettled`；
8. `downloadPerm` 不通过时不出现下载入口，文件名也不能触发下载；
9. 传入 `deleteRequest/downloadRequest/previewRequest` 时优先调用适配器；
10. 未传适配器时继续使用旧 URL 逻辑；
11. 规章图片/PDF预览调用 `previewRequest`，不能调用需要下载权限的下载接口；
12. 连续上传多个文件不会因旧闭包覆盖附件列表；
13. 临时状态只出现在当前拖拽区下方，成功项进入正式附件表，失败项可重试；
14. 组件卸载后不产生 state update warning。

### 8.2 规章后端测试

在现有 `spug_api/apps/regulation/tests.py` 中补充或调整测试，至少验证：

- 列表和上传响应仍包含 `id/file_name/previewable`；
- 新增返回 `file_size/uploaded_by_name/created_at`；
- 上传、预览、下载、删除权限边界保持不变；
- 只有 view 权限、没有 download 权限的用户仍能通过 `preview-url` 预览；
- 跨规章附件访问继续被拒绝；
- 删除继续是软删除并从列表隐藏。

### 8.3 人工验收

#### 规章管理员

- 打开已有规章详情，能看到紧凑拖拽区；
- 点击选择和拖入单个文件都能上传；
- 一次拖入多个文件，按顺序逐个上传；
- 成功附件展示文件名、大小、上传人、上传时间；
- 可预览、下载、删除；
- 某文件失败时其他文件继续上传，失败项可重试。

#### 权限组合

- 只有 `view`：能看列表和预览，不能上传、删除、下载；
- `view + download`：能预览和下载，不能上传、删除；
- `view + upload`：能预览、上传、删除，但没有下载权限时不能通过按钮或文件名下载；
- 完整权限：所有操作正常。

#### 旧模块回归

至少打开或静态核对：

```text
合同协议
无线电执照
升级工作台
系统公告
首页公告详情
```

确认未传 `uploadMode` 时仍为原按钮式上传，不出现意外拖拽大区域；只读页面不出现上传/删除入口。

#### 多账号并发

- 使用至少 2 个账号在不同浏览器会话中同时上传附件；
- 每个账号自己的批次保持串行，不互相读取或覆盖临时状态；
- 两个账号的后端请求可以同时执行，上传结果分别归属正确业务对象；
- 文件名相同也不能发生物理文件覆盖、附件串号或权限串用；
- 本任务不建设跨账号共享的前端队列或传输列表。

---

## 九、WSL Docker 验证要求

Docker daemon 运行在 WSL 中。Windows 侧 Docker CLI 可能无法连接 `dockerDesktopLinuxEngine`，不要把该错误误判为项目容器故障。

先从 Windows PowerShell 确认 WSL 发行版：

```powershell
wsl -l -v
```

随后进入实际运行 Docker 的发行版：

```powershell
wsl -d <发行版名称>
```

WSL 内项目路径通常为：

```bash
cd /mnt/e/TDYW/spug-3.0
docker ps
docker compose -f docker/docker-compose.yml ps
```

当前 Compose 主应用服务和容器名为 `tdyw`。后端测试建议：

```bash
docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
  python manage.py test apps.regulation

docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw \
  python manage.py check
```

前端验证建议在源码环境执行：

```bash
cd /mnt/e/TDYW/spug-3.0/spug_web
npm run build
```

如果实际容器名、镜像或源码挂载方式不同，先使用 `docker ps`、`docker inspect tdyw` 核对，不要擅自删除卷、重建数据库或执行 `docker compose down -v`。

---

## 十、建议实施顺序

1. 阅读全部参考文件，列出当前 `AttachmentManager` 调用方和接口假设。
2. 新增 `AttachmentUploadArea`，完成按钮/拖拽模式、串行队列和局部临时状态。
3. 在 `AttachmentManager` 中接入该上传区，确保默认旧行为不变。
4. 增加 `downloadPerm`，修复文件名点击的权限绕过可能性。
5. 增加五类请求适配器和 `normalizeAttachment`，保留旧 URL fallback。
6. 修复预览优先级，保证传入 `previewRequest` 时图片/PDF不走下载接口。
7. 增强规章附件 serializer 的标准展示字段。
8. 用增强后的 `AttachmentManager` 替换规章页面重复附件实现。
9. 补充测试，运行规章后端测试、Django check、前端 build。
10. 检查 `git diff`，确认没有无关格式化和旧模块行为变化。

---

## 十一、完成标准

以下条件全部满足才算完成：

- `AttachmentManager` 旧 Props 和旧调用方式可继续工作；
- 默认仍是按钮式单文件上传；
- 新增拖拽、多文件串行队列和部分失败处理；
- 上传/删除/预览/下载四种权限互不混用；
- 规章附件完全由 `AttachmentManager` 渲染和管理，不再保留第二套表格/预览状态；
- 规章仍使用原独立附件表、存储和 API；
- 规章图片/PDF预览不要求下载权限；
- 规章列表显示文件大小、上传人和上传时间；
- 合同、公告、执照、升级等旧调用方未被默认切换为拖拽模式；
- 后端测试、Django check 和前端 build 通过，或明确报告不可执行的环境原因；
- 没有 migration、依赖升级和无关代码改动。

---

## 十二、最终交付说明格式

完成后请按以下格式汇报：

```text
实现结果
- 公共组件新增了什么
- 规章管理如何迁移
- 向后兼容如何保证

修改文件
- 文件路径：主要改动

验证结果
- 后端测试命令及结果
- Django check 结果
- 前端 build 结果
- 人工验收覆盖情况

剩余风险
- 未覆盖的浏览器/多账号并发/权限场景
- 仍需后续实施的资料库/党建拖拽上传
```

不要只给出代码片段或实施建议；请直接在仓库中完成实现、验证，并报告实际结果。
