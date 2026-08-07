# spug_web/AGENTS.md - 前端工程规则

> 本文件覆盖 `spug_web/src/` 下所有前端模块的共同规则。模块级特殊规则见各模块目录下的 `AGENTS.md`（目前仅 `src/pages/document/`）。

---

## 一、技术栈与目录结构

```
spug_web/
├── src/
│   ├── routes.js          # 路由 + 菜单定义（含权限编码 auth 字段）
│   ├── App.js             # 根组件（Layout + 路由渲染）
│   ├── index.js           # 入口（MobX Provider + Router）
│   ├── gStore.js          # 全局 Store（HistoryStore 等）
│   ├── pages/             # 业务页面
│   │   ├── home/          # 工作台
│   │   ├── dataAnalysis/  # 数据分析
│   │   ├── departmentDutyLog/ # 部门值班日志
│   │   ├── radioLicense/  # 无线电台执照
│   │   ├── stationFrequencyApproval/ # 台站频率批复
│   │   ├── contractAgreement/ # 合同协议
│   │   ├── document/      # 资料库/文档管理（含党建）
│   │   ├── regulation/    # 规章管理
│   │   ├── runlog/        # 跨日事项跟踪
│   │   ├── device/        # 设备台账/履历
│   │   ├── upgrade/       # 系统升级
│   │   ├── exec/fault/    # 故障管理
│   │   ├── interference/  # 干扰管理
│   │   ├── duty/          # 值班日志
│   │   ├── system/        # 系统管理（账户/角色/设置/登录日志/审计/告警/租户）
│   │   ├── reminder/      # 提醒事项
│   │   └── welcome/       # 欢迎页
│   ├── components/         # 公共组件
│   │   ├── AuthButton.js  # 权限按钮（无权限返回 null）
│   │   ├── AuthCard.js    # 权限卡片
│   │   ├── AuthDiv.js     # 权限容器
│   │   ├── AuthFragment.js # 权限片段
│   │   ├── AttachmentManager.js # 附件管理器
│   │   ├── AttachmentUploadArea.js # 附件上传区域
│   │   ├── AttachmentCountBadge.js # 附件计数徽章
│   │   ├── ExpirationReminderNotification.js # 到期提醒通知
│   │   ├── SearchForm.js  # 搜索表单
│   │   ├── FilterBar.js   # 过滤栏
│   │   ├── TableCard.js   # 表格卡片
│   │   ├── ExportButton.js # 导出按钮
│   │   ├── Breadcrumb.js  # 面包屑
│   │   ├── Link.js / LinkButton.js # 链接组件
│   │   ├── StatisticsCard.js # 统计卡片
│   │   ├── ACEditor.js    # 代码编辑器
│   │   ├── Action.js      # 操作按钮组
│   │   └── NotFound.js    # 404
│   └── libs/              # 公共工具
│       ├── http.js        # Axios 实例 + 拦截器
│       ├── history.js     # 路由 history
│       ├── router.js      # 路由工具
│       ├── functools.js   # 权限判断、X_TOKEN、日期工具
│       ├── systemFolderContext.js # 党建 system_folder 上下文
│       └── index.js       # 统一导出
├── package.json
└── webpack.config.js
```

### 关键约束

- **antd 4.21.5**：Modal/Drawer 用 `visible`（非 `open`）；Form 用 `Form.useForm()`；message 用 `message.error()` / `message.success()`。
- **MobX legacy decorators**：`@observable` / `@action` / `@computed`，Babel 需 `@babel/plugin-proposal-decorators`（`legacy: true`）+ `@babel/plugin-proposal-class-properties`。
- **React 17**：无 Automatic Runtime JSX，需 `import React from 'react'`。

---

## 二、路由与权限

### 路由定义

路由在 `src/routes.js` 中定义，每条路由包含：
- `path`：URL 路径
- `component`：对应的页面组件
- `auth`：权限编码（与后端 `page_perms` 一致）
- `icon` / `title`：菜单图标和标题
- `child`：子路由（嵌套菜单）

### 权限编码映射

| 前端路由 | auth 权限编码 | 后端应用 |
|---|---|---|
| `/home` | `dashboard.dashboard.view` | home |
| `/data-analysis` | `data_analysis.*.view`（多选） | data_analysis |
| `/department-duty-log` | `department_duty_log.department_duty_log.view` | department_duty_log |
| `/radio-license` | `radio_license.license.view` | radio_license |
| `/station-frequency-approval` | `radio_license.approval.view` | radio_license |
| `/contract-agreement` | `contract_agreement.agreement.view` | contract_agreement |
| `/document` | `document.document.view` | document |
| `/document/party-building-documents` | `document.party_building_document.view` | document |
| `/regulation` | `document.regulation.view` | regulation |
| `/runlog` | `runlog.runlog.view` | runlog |
| `/device/device_resume` | `device.device_resume.view` | device |
| `/device/device_history` | `device.device_history.view` | device |
| `/upgrade` | `upgrade.upgrade.view` | upgrade |
| `/exec/fault/record` | `fault.faultrecord.view` | fault |
| `/exec/fault/part` | `fault.faultpart.view` | fault |
| `/interference` | `interference.interference.view` | interference |
| `/duty` | `duty.duty.view` | duty |
| `/system/announcement` | `home.announcement.view` | home |
| `/reminder` | `home.reminder.view` | reminder |
| `/maintenance/audit` | `system.audit.view` | logs |
| `/maintenance/alert` | `system.alert.view` | alert |
| `/system/account` | `system.account.view` | account |
| `/system/role` | `system.role.view` | account |
| `/system/setting` | `system.setting.view` | setting |
| `/system/login` | `system.login.view` | account |
| `/system/tenant` | `system.tenant.view` | account |

### 权限规则

1. **routes.js 的 `auth` 字段必须与后端权限编码完全一致**。
2. **权限支持 `|`（或）和 `&`（与）组合**：`'a.b.view|c.d.view'` 表示满足任一即可，`'a.b.view&c.d.view'` 表示都需满足。
3. **`hasPermission(strCode)`**（`libs/functools.js`）：前端权限判断，超级用户直接返回 `true`。
4. **权限控制不能只隐藏按钮**：`AuthButton` / `AuthCard` / `AuthDiv` 仅做前端展示控制，后端必须独立校验。
5. **权限数据来源**：`sessionStorage` 中的 `permissions`（JSON 数组），登录时从后端获取。
6. **新增路由必须同步**：routes.js + 后端权限定义 + 数据库角色权限分配。

---

## 三、HTTP 层与请求规则

### http.js 设计

1. **Axios 实例**：全局拦截器自动处理认证和错误。
2. **请求拦截器**：
   - `/api/` 开头的请求自动注入 `X-Token` header。
   - 党建 `system_folder` 上下文激活时，自动为 `/api/document/*` 请求注入 `system_folder` 参数。
3. **响应拦截器**：
   - HTTP 401：跳转登录页。
   - HTTP 200 + `error` 字段：自动 `message.error()` 提示。
   - HTTP 200 + `data` 字段：返回 `data`（空字符串 `''` 转为 `{}`）。
   - 二进制响应（arraybuffer/blob）：检查 content-type，JSON 错误解析后提示，二进制数据透传。
   - 网络错误/超时：友好化提示。
4. **错误去重**：`showErrorOnce()` 2 秒内相同错误消息只显示一次。

### 请求规则

1. **同一个错误只能提示一次**：HTTP 拦截器已提示的错误，业务代码不得重复 `message.error()`。
2. **HTTP 200 + `error` 不是成功**：业务代码不得将含 `error` 的响应当作成功处理。
3. **成功提示必须等待后端真实成功结果**：不乐观更新 UI。
4. **表单提交防重复**：提交时设 `loading=true`，完成后恢复（`finally` 块）。
5. **错误状态恢复**：请求失败时恢复表单/按钮状态，不能卡在 loading。
6. **`skipErrorNotification`**：调用方可设 `config.skipErrorNotification=true` 抑制错误弹窗（用于空间切换等过期请求场景）。

---

## 四、状态管理

### MobX Store

1. **全局 Store**（`gStore.js`）：`HistoryStore` 等跨页面共享状态。
2. **页面级 Store**：各业务页面通常有对应的 `.store.js` 文件（如 `document.store.js`）。
3. **装饰器语法**：`@observable` 标记可观察状态，`@action` 标记修改方法。
4. **Store 注入**：通过 `App.js` 的 `<Provider>` 注入。

### 状态同步规则

1. **页面状态、URL 和 Store 必须同步**：路由参数变化时更新 Store，Store 变化时更新 UI。
2. **组件卸载后不得回写状态**：异步请求/定时器在 `componentWillUnmount` / `useEffect` cleanup 中清理。
3. **防止旧请求覆盖新页面状态**：分页/搜索切换时，旧请求的响应不得覆盖新数据。使用请求版本号或 AbortController。

---

## 五、组件规则

### 公共组件使用

| 组件 | 用途 | 关键约束 |
|---|---|---|
| `AuthButton` | 权限按钮 | 无权限返回 `null`（不渲染），非 disabled |
| `AuthCard` / `AuthDiv` / `AuthFragment` | 权限容器 | 同上 |
| `AttachmentManager` | 附件管理器 | 使用 evidence 附件系统，新建阶段用临时 UUID |
| `AttachmentUploadArea` | 附件上传区域 | 同上 |
| `SearchForm` / `FilterBar` | 搜索过滤 | 与后端分页参数配合 |
| `TableCard` | 表格卡片 | 封装了分页、loading、空数据 |
| `ExportButton` | 导出按钮 | 二进制下载，需处理错误 |
| `ExpirationReminderNotification` | 到期提醒 | 合同/执照到期通知 |

### 组件修改规则

1. **修改公共组件必须搜索所有调用方**：`components/` 下的组件被多模块引用，修改后需全量检查。
2. **禁止移除组件的现有 props**：只能新增可选 props，保证向后兼容。
3. **新增公共组件需在 `components/index.js` 导出**。

---

## 六、列表与表单

### 列表操作

1. **增删改后必须刷新列表**：成功后调用 `fetchData()` 重新加载。
2. **分页边界**：删除最后一页的最后一条记录后，页码应回退到前一页。
3. **搜索重置**：重置搜索条件时同时重置页码到第 1 页。
4. **loading 状态**：请求期间显示 loading，完成后恢复。

### 表单操作

1. **提交防重复**：`loading` 状态控制按钮 `disabled`。
2. **编辑回填**：打开编辑弹窗时从后端获取最新数据回填，不信任列表中的缓存数据。
3. **表单校验**：使用 antd Form 的 `rules` 校验，自定义校验用 `validator`。
4. **关闭弹窗重置**：Modal 关闭后 `resetFields()`，下次打开为干净状态。

---

## 七、党建文档 system_folder 上下文

1. **`libs/systemFolderContext.js`**：管理 `system_folder` 激活状态。
2. **自动注入**：`http.js` 请求拦截器在 `system_folder` 激活时自动为 `/api/document/*` 请求注入参数。
3. **GET/DELETE**：注入到 query params。
4. **POST/PUT**：multipart 注入 FormData，JSON 注入 body。
5. **路由判断**：`shouldUseSystemFolder(pathname)` 决定是否注入。

---

## 八、测试规则

1. **禁止以读取源码字符串代替行为测试**。
2. **禁止用正则匹配源码的伪测试**。
3. 测试必须执行组件渲染、hook 调用、store 变更和请求行为。
4. Mock 请求需使用真实的响应格式（包含 `data` 或 `error` 字段）。
5. 测试必须覆盖：加载状态、成功响应、错误响应、权限控制、空数据。

---

## 九、JS 语法验证

项目使用 legacy decorators + class properties，`node --check` 不支持 ESM `import`：

```bash
# 必须用 @babel/core 脚本验证
# 必须加 @babel/plugin-proposal-decorators (legacy: true)
# 必须加 @babel/plugin-proposal-class-properties
# Windows PowerShell 下需把 stdout 重定向到文件再读取（避免控制台乱码）
```

---

## 十、常见反模式（禁止）

1. **乐观更新**：未等后端返回就更新 UI 状态。
2. **重复提示**：HTTP 拦截器已提示后业务代码再 `message.error()`。
3. **卸载后回写**：组件卸载后异步请求回调仍 `setState`。
4. **旧请求覆盖新状态**：分页/搜索切换时旧请求覆盖新数据。
5. **权限仅前端**：只隐藏按钮不做后端校验。
6. **Modal 用 `open`**：antd 4.x 用 `visible`。
7. **Form 不 resetFields**：编辑弹窗关闭后不重置，下次打开残留旧数据。
8. **loading 不恢复**：请求失败时 `loading` 卡在 `true`。
