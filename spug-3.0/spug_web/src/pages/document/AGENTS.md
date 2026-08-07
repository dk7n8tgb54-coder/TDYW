# pages/document/AGENTS.md - 资料库模块前端规则

> 本文件仅记录资料库前端模块**独有**的、不能放在 `spug_web/AGENTS.md` 上层的规则。通用前端规则见上层文件。

---

## 一、目录结构

```
pages/document/
├── index.js                    # 主入口（普通模式 + 党建模式）
├── PartyBuildingDocumentsIndex.js  # 党建文档入口
├── Explorer/                   # 文件浏览器
│   ├── index.js                #   主组件
│   ├── components/             #   子组件
│   ├── hooks/                  #   12 个自定义 hook
│   └── utils.js
├── components/                 # 模块级公共组件
│   ├── UploadPanel.js          #   上传面板（抽屉模式）
│   ├── UploadConflictModal.js  #   冲突处理弹窗
│   ├── KeyboardShortcuts.js    #   键盘快捷键
│   ├── DocumentErrorBoundary.js #  错误边界
│   ├── DocumentDropUploadLayer.js # 拖拽上传层
│   ├── SearchBox.js            #   搜索
│   ├── DiskStatus.js           #   磁盘状态
│   ├── TransferItem.js         #   传输列表项
│   └── ...
├── stores/                     # MobX Store
│   ├── index.js                #   统一导出
│   ├── navigation/             #   导航状态
│   ├── upload/                 #   上传系统（56 文件）
│   │   ├── core/               #     上传核心逻辑（49 文件）
│   │   ├── ui/                 #     上传 UI 状态
│   │   └── index.js
│   └── constants/              #   常量定义
├── hooks/                      # 模块级 hooks
├── utils/                      # 工具函数
├── FolderTree.js               # 文件夹树
├── PreviewModal.js             # 预览弹窗
└── *.module.less               # CSS Modules
```

---

## 二、模式切换

1. **普通模式**（`mode='normal'`）：默认资料库，支持完整导航和文件夹操作。
2. **党建模式**（`mode='partyBuildingDocuments'`）：锁定 `system_folder` 根目录，不调用 `restoreFromUrl()` 防止越界到公共库。
3. **`setSystemFolder(code)` / `clearSystemFolder()`**：激活/清除党建上下文，`http.js` 自动注入 `system_folder` 参数。
4. **`PARTY_BUILDING_DOCUMENTS_CODE`**：党建文档的固定 system_folder 编码。

---

## 三、上传系统

### 架构

上传系统是前端最复杂的子系统（`stores/upload/` 56 文件），分为：

- **`core/`**：上传核心逻辑（分片、MD5、合并、断点续传、状态机）
- **`ui/`**：上传 UI 状态（抽屉、Tab、进度条、闪烁提示）

### 上传流程

1. 文件选择/拖拽 -> 冲突检查 -> 加入队列
2. 计算 MD5（`calculating` 状态）-> 检查已上传分片 -> 分片上传 -> 合并请求
3. 合并轮询（`MERGE_STATUS_TIMEOUT=300s`）-> 完成/失败

### 状态机

前端传输状态与后端 `TransferStatus` 一致。状态转换矩阵见后端 `apps/document/AGENTS.md`。

### 上传链关键约束

1. **XHR 回调必须检查 `operationVersion`**：过期回调（暂停/取消后的旧请求）不得覆盖新状态。
2. **`queueMicrotask` 竞态**：有额外检查缓释，但修改时需注意。
3. **合并中（MERGING）必须显示**：合并耗时最长 5 分钟，Celery 无 progress，进度条卡 100% 时用户会以为卡死。
4. **MD5 是内部技术细节**：前端文案用"准备上传"而非"计算中"，Tooltip 解释"计算文件指纹以加速上传（断点续传）"。
5. **error 字段一致性**：正常状态（waiting/calculating/uploading/merging）不应有 error 字段，错误状态才设置。

### 抽屉模式（仿百度网盘）

1. **收起态**：底部居中小条（`MiniBar`，`fixed, bottom:0, h=40px`），不挡视野。
2. **展开态**：antd `Drawer placement="bottom"` + 可调高度（240-720px）。
3. **触发**：右上角图标 / 点击小条 / `Ctrl+Shift+U` 快捷键。
4. **自动隐藏**：无任务时不渲染 MiniBar。
5. **拖拽把手**：`document.addEventListener('mousemove'/'mouseup')` 全局监听，`componentWillUnmount` 必解绑，高度 < 120px 自动收起。
6. **闪烁提示**：失败闪红（`#ff4d4f`）、完成闪绿（`#52c41a`），1.5s 动画，仅收起态闪烁。

### 键盘快捷键

| 快捷键 | 功能 |
|---|---|
| `Ctrl+Shift+U` | 打开/关闭抽屉 |
| `Ctrl+Shift+P` | 全部暂停 |
| `Ctrl+Shift+R` | 全部开始/继续 |
| `Ctrl+Shift+C` | 清空已完成 |
| `?` / `Shift+/` | 显示快捷键帮助 |

快捷键实现约束：
- 输入控件聚焦时（`input/textarea/select/contenteditable`）不响应。
- `e.ctrlKey || e.metaKey` 兼容 macOS。
- `preventDefault + stopPropagation` 阻止浏览器默认行为。

---

## 四、Explorer 文件浏览器

1. **视图模式**：列表视图 / 网格视图（`viewMode` state）。
2. **多选模式**：`multiSelectMode` state 控制批量操作。
3. **搜索**：`searchState` 包含 `isSearching`/`keyword`/`scope`/`results`，支持当前目录搜索和全局搜索。
4. **URL 一致性**：导航路径同步到 URL，刷新可恢复。党建模式不走 `restoreFromUrl()`。
5. **手动刷新**：`refreshing` state 只让刷新按钮显示 loading，列表不显示整表遮罩。

### hooks

Explorer 目录下有 12 个自定义 hook，修改时需注意：
- hook 间的依赖关系和执行顺序。
- `useEffect` cleanup 必须清理定时器和事件监听。
- 异步请求需防止卸载后回写。

---

## 五、预览

1. **`PreviewModal.js`**：文件预览弹窗。
2. **kkFileView 集成**：浏览器用 `KKFILEVIEW_API_URL`，回源用 `KKFILEVIEW_SERVER_URL`。
3. **`preview_token`**：短时效预览令牌，优先于 `x-token` 认证。
4. **二进制响应处理**：`http.js` 拦截器检查 content-type，JSON 错误解析后提示，二进制数据透传。

---

## 六、Store 架构

### navigation store

- `restoreFromUrl()`：从 URL 恢复导航路径（党建模式不调用）。
- `navigateTo(folder)`：导航到文件夹，同步 URL。

### upload core store

- `uploadCoreStore`：上传核心状态管理。
- 分片上传、MD5 计算、合并轮询、断点续传逻辑。
- 修改时注意 `operationVersion` 版本控制。

### upload ui store

- `uploadUIStore`：抽屉开关、Tab 切换、进度条、闪烁提示。
- 与 `uploadCoreStore` 分离，避免 UI 重渲染影响上传逻辑。

---

## 七、测试

- `__tests__/` 目录下有测试文件。
- 测试必须覆盖：上传状态机、冲突处理、断点续传、快捷键、权限控制。
- 禁止以读取源码字符串代替行为测试。
