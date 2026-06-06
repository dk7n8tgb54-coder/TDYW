# 项目记忆

## 项目规范

### 数据库迁移 ⚠️ 重要
**修改 Django 模型后必须执行迁移**：
```bash
# 1. 生成迁移文件
docker exec tdyw python /data/spug/spug_api/manage.py makemigrations document --name xxx

# 2. 执行迁移
docker exec tdyw python /data/spug/spug_api/manage.py migrate document
```

### Docker 路径
- 容器内项目路径: `/data/spug/spug_api/`
- manage.py 位置: `/data/spug/spug_api/manage.py`

### 代码验证流程（post-write-verification skill）
1. Lint 检查: `read_lints(paths=[...])`
2. 语法检查:
   - Python: `docker exec tdyw python -m py_compile <path>`
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

### 技术细节
- spug_web 使用 antd 4.21.5
- spug_api 使用 Django + MySQL
- 租户隔离使用 TenantModelMixin

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
