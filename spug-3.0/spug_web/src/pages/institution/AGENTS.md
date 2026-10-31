# pages/institution/AGENTS.md - 制度管理模块前端规则

> 2026-10-27 新增。通用规则见 `spug_web/AGENTS.md`；本文件只记录制度管理独有约定。
> **2026-10-29 多文件改造已落地**（对应后端迁移 0003）：草稿工作台/详情页按
> 文件级接口运作，旧单文件接口仅在过渡期由后端委托唯一文件。
> **2026-10-29 文件分工替代章节分工**（对应后端迁移 0005）：分工单位=整份
> 制度文件，负责人/分工说明/提交编制在文件清单行内维护，独立的「章节分工」
> 页签已取消；旧章节记录在文件清单页签底部只读过渡展示（ChaptersTab 已删除）。
> **2026-10-30 发布后修订状态交互已落地**（对应后端迁移 0006）：修订进行中
> 是显式状态，详情以当前生效为主（"已生效，无未发布修改"），日常清单列简化，
> 「开始修订」是真实状态动作，负责人列点击分工 + 勾选批量分工。
> **2026-10-30 变更记录再次跳转修复**：文件变更记录页签保持挂载期间，文件
> 清单行再次「变更记录」的目标由页签内 mobx reaction 消费（此前仅
> componentDidMount 消费，二次跳转不生效）；store 的
> fetchFileVersionHistory/fetchFileLogs 加 reqSeq 守卫防迟到响应覆盖。
> **2026-10-30 文件清单双视图**：文件清单页签内拆「当前生效版本 vN」/
> 「修订草稿」两个内容视图（Segmented 切换、默认按是否有生效版本），
> 版本来源在入口按钮与预览标题持续明确；提交编制的"无历史副本"限制与
> 负责人责任归属语义在视图说明中明确。
> **2026-10-31 生效视图不展示负责人**：「当前生效版本」视图不再渲染
> 负责人列；负责人属修订分工，只在「修订草稿」视图展示与维护（分工
> 入口保留在草稿视图负责人列）。
> **2026-10-31 授权模型改造已落地**（对应后端迁移 0008）：手册级授权由
> 旧角色关联改为「手册所有者（manual.owner/is_owner）+ 制度管理员
> （institution.manual.admin，manual.is_admin）+ 逐本账号授权
> （authorizations：can_view/can_edit/can_publish 三布尔）」；可见性
> 只由 my_roles 与 is_owner/is_admin 决定（utils，模块权限码不再直通），
> 内容编辑按**负责人独占**（can_edit 授权 + assignment.is_mine）；归属
> 字段更名 org_type/org_type_display/org_name，列表过滤参数 org_type；
> 权限配置页签对 config 码/所有者/管理员可见，页签内为 所有者卡 +
> 账号授权卡（AuthorizationCard，替代旧角色关联）+ 编辑密码卡。

## 一、结构

```
pages/institution/
├── index.js / store.js / Table.js / ManualForm.js / CategoryModal.js / utils.js
│   └── Table.js 内含 工作状态列（work_status 文案映射，2026-10-29 交互优化）
├── detail/            # /institution/manuals/:id 详情页
│   ├── index.js       # 头部（DraftStatusSummary + PublishButton 并排）+ 受控页签
│   ├── store.js       # 详情数据 + fileChangeTarget（文件行→变更记录预选）
│   │                  #   + refreshAfterLifecycle（发布/回退/废止统一刷新）
│   ├── FileListTab.js # 【默认页签】统一文件清单（2026-10-29 交互优化：由
│   │                  #   EffectiveFilesTab + DraftWorkspaceTab 合并，只减不增）
│   │                  #   + 文件分工列（负责人/编制提交）与行内分工入口
│   ├── FileAssignmentModal.js # 文件分工弹窗（指定/改派/清空负责人+分工说明）
│   ├── DraftStatusSummary.js # 详情头部整套草稿状态摘要（一致/待发布变化/缺草稿/等待首发/暂不能确认）
│   ├── PublishButton.js # 发布新版本入口（整套待发布状态旁；预检分组确认窗+受阻处理入口）
│   ├── draftStatusShared.js  # draft-status 关系文案与摘要文本映射（Summary/文件清单共用）
│   ├── VersionsTab.js # 版本与发布：发布历史 + 版本文件清单 Modal + 回退/长期保留
│   ├── FileChangeTab.js      # 文件变更记录：originals-overview 全集下拉（含已移除）
│   │                  #   + 按文件发布参与 + 文件级操作记录；清理快照仅元数据
│   ├── oplogShared.js # 操作记录动作文案与详情解析（RecordsTab/FileChangeTab 共用）
│   ├── OriginalsTab.js# 初始来源（高级恢复入口，次级信息）：全文件列表 +
│   │                  #   最初原稿/展开历史/更换来源/重建确认/已清理态
│   ├── RecordsTab.js / ConfigTab.js
│   │                  # ConfigTab（2026-10-31 授权模型）：所有者卡 + 账号
│   │                  #   授权卡 AuthorizationCard.js（逐本账号三布尔授权，
│   │                  #   PUT authorizations 整体替换）+ 编辑密码卡
│   └── PreviewModal.js
└── draft/             # /institution/manuals/:id/draft 草稿工作台（唯一编辑页面）
    ├── store.js       # 文件清单 + 选中文件 + 按文件会话（sessionStorage 持久化）
    │                  #   + 编辑方式切换/本机编辑基线（2026-10-31）
    ├── index.js       # 密码验证门 → 文件清单（多文件）+ 选中文件工作区；支持 ?file= 深链
    ├── EditorArea.js  # 编辑区四态 + 编辑方式切换（Segmented）+ 本机编辑面板
    ├── RecoveryPanel.js # 无草稿恢复面板（2026-10-31 自 index.js 抽出，行为不变）
    ├── finishingShared.js # 保存确认失败语境（finishingErrorKind）文案映射
    ├── ExpandedBar.js / SaveStatusTag.js / FileNav.js / OnlyOfficeEditor.js
```

## 一·补、详情页信息层级（2026-10-29 交互优化版，最重要）

- **页签顺序=信息层级**：文件清单（默认，统一承载主流程）→ 版本与发布 →
  文件变更记录 → 初始来源 → 操作记录（→ 权限配置）。
  「文件清单」由原「当前生效文件」+「草稿工作区」合并（顶层页签只减不增），
  消除"草稿工作区（只读页签）/草稿工作台（编辑页）"命名混淆——草稿工作台
  是唯一编辑页面，文件行「继续编辑」经 `?file=` 深链直达对应文件。
  2026-10-29 文件分工落地后，「章节分工」页签已取消（分工入口在文件清单
  行内，旧章节记录只在文件清单页签底部只读过渡展示，顶层页签数量仍只减不增）。
  rc-tabs 页签内容默认**首次激活才挂载**——各页签的数据拉取写在自身
  componentDidMount，不要在详情入口预取全部页签数据；详情页 Tabs 为
  受控模式（activeKey 在 index.js state），文件清单行「变更记录」经
  `store.fileChangeTarget` + onOpenFileHistory 回调切换页签并预选文件。
- **页签对所有可见者统一渲染**（文件清单对 查看/编制/发布角色 都可见，
  列内容按权限收窄；对应后端 can_view_manual 口径），不再按发布可见权
  切换默认页签。注意 AuthDiv/hasPermission 收窄时会整页不渲染，测试里
  mock 必须放行 `institution.manual.view`。
- **文案三分**：初始来源（原始上传文件）/ 当前草稿（待发布工作内容）/
  当前生效文件（最新发布快照）——文件清单页签说明按权限区分措辞，
  不得让用户把初始来源当成最新文件。
- **头部=状态+发布**：DraftStatusSummary（整套草稿状态摘要）与
  PublishButton（发布新版本入口）并排——发布者无需进入草稿工作台即可
  核对整套变化并发布；发布/回退/废止后统一走
  `store.refreshAfterLifecycle`（详情/版本/日志/草稿状态/当前生效清单）。

## 二、授权与按钮（2026-10-31 授权模型版）

- 页面权限码统一 `institution.manual.*`（树见 `src/pages/system/role/codes.js`，
  含 2026-10-31 新增的 `admin`=制度管理员），路由 `auth: 'institution.manual.view'`。
  页面码只授予功能入口资格；**具体可操作哪本手册由 `my_roles`（授权推导
  view/edit/publish）与 `is_owner`/`is_admin` 决定**，模块级 AuthButton 管
  页面入口；两层都不能省——后端独立校验。
- **可见性口径唯一实现在 `utils.js`**：`canViewPublished` = view 授权 or
  （edit 授权且 manual.editor_can_view_published）or is_admin；`canViewWorkspace`
  = edit/publish 授权 or is_owner or is_admin。**不再以 hasPermission(edit/config)
  直通**（2026-10-31 改造，所有者身份同样不自动可见发布版）。
- **负责人独占编辑**：内容写入口（开始编辑/开始修订/继续编辑/草稿预览下载/
  重建草稿）= my_roles.edit **且** 该文件 `assignment.is_mine`；非负责人的
  编制授权账号不渲染编辑入口，显示「编辑仅限文件负责人」占位提示。
- **分工与文件结构写=所有者或管理员**：文件分工（单/批量）、新增/改名/排序/
  移除/新增文件、更换来源/上传原稿 = `manual.is_owner || manual.is_admin`
  （页面码 draft_edit|upload 原样保留，与后端 @auth+业务门一致）；
  发布 = my_roles.publish（授权推导，owner/admin 不自动可发布）。
- 权限配置页签可见 = `institution.manual.config` 码 or `is_owner` or
  `is_admin`；页签内三卡：手册所有者卡（admin 可指定/接管/移交，候选走
  `owner-candidates/`；owner 只读）、账号授权卡 `AuthorizationCard.js`
  （逐本账号 can_view/can_edit/can_publish 三布尔行 + 「编制授权者可查看
  发布版」Switch，PUT `authorizations/` 整体替换，保存响应含
  `revoked_sessions` 失权撤销会话数；候选走 `account-options/`）、编辑密码卡
  （仅持 config 码渲染表单，否则只读说明）。授权清单/账号候选失败在卡片内
  展示错误+重试（skipErrorNotification，不与拦截器重复弹错）。
- **负责人候选=持本手册编制资格的启用账号**（`assignment-owners/`，
  2026-10-31 起口径）：分工弹窗与新增文件负责人下拉的唯一来源，禁止改拉
  账号管理清单 `/api/account/user/`。

## 三、草稿工作台约定（2026-10-29 多文件版；2026-10-30 交互改造）

- **编辑区放大/还原（2026-10-30）**：编辑器正上方「放大/还原」按钮（图标+
  Tooltip，还原态 Tooltip 注明 Esc），实现拆在 `draft/EditorArea.js`（编辑区
  四态+按钮）与 `draft/ExpandedBar.js`（放大态精简顶栏）、
  `draft/SaveStatusTag.js`（保存状态，状态条与顶栏共用）。放大以 fixed 浮层
  （`EXPANDED_ROOT_STYLE`，zIndex 900：盖过布局头部、低于 antd Modal/Message）
  承载：**切换放大只改容器样式与 OnlyOfficeEditor 的 height prop
  （72vh↔100%），编辑器元素在 React 树中的位置与 key 不变——绝不重新拉
  editor-config、轮换 document key 或销毁重建实例**；浮层内显隐一律
  display:none 或同类型 div 分支（兄弟结构位移会导致编辑器 remount，禁止）。
  放大态收起 文件导航/文件头部/元数据/流程与文件管理行/编辑器下方说明，
  顶栏保留 返回/文件名/修订号/独立保存状态/提交状态/「保存并结束编辑」，
  finishingError 时顶栏呈现 重试保存/不保存并退出（保存确认与未保存保护
  流程在放大态不中断）。Esc 还原（window keydown 随放大态挂/摘，iframe 内
  按键不冒泡）；切换文件/返回详情/结束编辑/不保存退出 显式 exitExpanded；
  编辑器不可用（会话退出等）时 CDU 兜底自动退出放大。行为测试钉死在
  `__tests__/draft.workspace.expand.test.js`（含实例不重建/不重拉配置/
  DOM 节点同一）。
- **2026-10-30 布局**：多文件制度=左侧文件导航（`draft/FileNav.js`：名称
  ellipsis+负责人/修订号/编辑占用/提交状态 Tag，行内 flexWrap 折行防窄屏
  重叠，底部新增文件入口）+ 右侧编辑区主体（Row/Col 响应式，窄屏导航
  折叠到编辑区上方）；单文件不渲染导航，开门即编辑。右侧顶部状态条
  集中展示 当前文件/修订号/**独立的"制度草稿保存状态"**/提交编制状态
  Tag（`FileNav.submissionTagFor`，与详情页同一口径只映射不推断）。
- **独立的"制度草稿保存状态"（2026-10-30 保存确认改造，最重要）**：
  只有服务端确认回调落盘后才显示"已保存到制度草稿：rN、时间"。
  确认中显示"正在请求服务端保存…"；在线编辑有未确认修改
  （`store.editorDirty` 闩锁，由 OnlyOfficeEditor `onDocumentStateChange`
  上报，**false 事件不清除**——DS 的"所有更改已保存"只代表文档服务
  自身缓存）显示警示；在线编辑无确认记录显示"内容尚未经服务端确认
  落盘"；非在线编辑直接呈现服务端草稿数据。确认结果记入
  `store.saveConfirmed`（结束编辑撤销会话时随 clearSession 清除）。
- **流程按钮与次级操作**：开始编辑 → 保存并结束编辑 → 提交编制 为主动
  线；下载/预览/改名/排序/移除/新增收进「文件管理」次级行（单文件制度
  的新增文件入口在次级行，多文件在导航底部）。**负责人持有该文件编辑
  会话（含本账号其他页签）时提交编制按钮禁用**，Tooltip 明确提示先
  「保存并结束编辑」；后端 submit 仍独立校验活跃会话拒绝。
  **2026-10-31 授权模型门控拆分**：「开始编辑」（及会话入口）仅
  负责人独占（my_roles.edit + `assignment.is_mine`）渲染，非负责人
  （含持编制授权未指派者）显示「编辑仅限文件负责人，请先由手册所有者
  指派」；文件管理次级行拆分——下载草稿/预览草稿=负责人（与编辑入口
  同域），改名/上移/下移/移除/新增文件=手册所有者或制度管理员（AuthButton
  页面码原样）。
- **落盘确认链路 = `_confirmForcesave`（2026-10-30 保存确认改造，唯一实现，
  最重要）**：循环"forcesave 受理 → 以响应修订号为基线轮询 `files/<fid>/draft/`
  修订号推进 → **推进后再次 forcesave 复核**"，直到 DS 报告 `no_changes`
  才认定确认成功——他处（如同账号其他页签 multipart 保存）推进的修订号
  **不得冒充本次回调落盘**；轮询超时后做一次最终 forcesave 复核，
  no_changes 仍算确认（回调内容幂等跳过、修订号不推进的情形），仍受理
  即失败。轮询每次响应就地更新清单条目 draft（服务端修订号/保存人/时间）。
  **no_changes 沉降复核（2026-10-31 竞态修复，最重要）**：DS 的
  no_changes 应答只反映命令处理瞬间的缓冲状态，与命令几乎同拍敲入的
  修改可能经事件通道晚于命令注册（dev 实测：DS 误答 no_changes → 前端
  轮换 key 销毁编辑器 → 在途修改随收尾回调被 409 丢弃）。因此 no_changes
  经 `_settleNoChanges` 沉降复核干净才采信：编辑器实时脏态
  （`store.editorLiveState`，onDocumentStateChange 的原始上报 true/false
  都记录，**不受 markSaveConfirmed 清除影响**——确认收尾同拍到达的脏
  事件只有它读得到；editorDirty 闩锁语义不变，仍只服务 UI 保存状态）
  已报脏即判在途；短沉降窗（`confirmSettleMs` 默认 1.2s，一次性复核
  **不属于固定周期轮询**）后再次 forcesave，仍 no_changes 且编辑器不报脏
  才确认；复核改报受理或脏态仍在则重走确认循环。no_changes=确认成功的
  规则不变，只是从"即时采信"收紧为"复核干净才采信"。
- **「保存并结束编辑」**：`store.finishEditing(fileId)` = `_confirmForcesave`
  确认成功后才 exitFileSession 并提示成功。**失败/超时一律保留会话与
  编辑器**（`finishingErrorFileId/finishingError` 只标记归属文件），状态条
  渲染「重试保存 / 不保存并退出」；「不保存并退出」是明确告知可能丢失的
  危险出口，确认弹窗不冒充保存成功。reset/新一次 finish/confirm 递增
  `finishSeq` 使在途轮询失效；确认期间 `finishingFileId` 禁用冲突导航
  （切换/返回给出"正在保存当前文件"提示）与重复提交。
- **切换文件/返回详情必须复用确认链路（2026-10-30，最重要）**：
  `store.confirmFileSave(fileId, context)` = `_confirmForcesave` 确认成功
  但**不撤销会话**（会话按文件保留可切回）；工作台 `handleSelectFile`/
  `handleBackToDetail` 对在线编辑中的当前文件先确认落盘，成功才真正
  切换/跳转（成功提示"已保存到制度草稿"），失败留在当前文件并以
  finishingError 呈现"已取消<context>"与重试入口。**不得仅发起静默
  `requestForcesaveQuiet` 就销毁编辑器**——quiet 只保留给无法拦截的
  页面卸载兜底（componentWillUnmount），配合 beforeunload 与工作页签
  未保存登记（DraftUnsavedGate 不变，"任一有效会话"口径）。既有修复
  针对的丢失场景：离开后重进会轮换 document key，DS 迟到的关闭回调
  被 409 拒绝即内容丢失；确认先行使该回调只会幂等跳过。
- **?file= 深链（2026-10-30 收紧）**：`store.fetchAll(id, requestedFileId)`
  记录深链目标——密码验证**只为指定文件建立会话**（`verifyPassword`
  按 requestedFileId 定向），目标不存在→`deeplinkNotice`"不存在或已
  移除，未建立任何编辑会话"且不验证；目标无草稿→密码门禁用+明确
  提示；绝不静默改开另一份文件的会话。被他人占用由后端验证拒绝。
- **编辑方式切换与本机编辑（2026-10-31 恢复/完善，最重要）**：在线编辑与
  「下载草稿 → 本机 Word/WPS 编辑 → 上传保存」按文件切换（EditorArea
  顶部 Segmented，仅在线编辑真实可用时渲染）；服务未配置/配置加载失败/
  编辑器加载失败恒为本机方式，**本机入口不依赖任何失败上报的可靠性**
  （OnlyOfficeEditor 经 onUnavailable 上报 `store.editorLoadFailed`，
  工作台据此呈现显式「切换到本机编辑」入口；onReady 清除标记；即使
  上报不可靠，Segmented 也独立于它始终渲染）。切换唯一实现
  `store.switchEditMode`：在线切本机先 confirmFileSave（'切换到本机
  编辑'；失败留下重试，`finishingErrorKind='switch_local'` 重试按钮=
  重试切换），确认成功后过**轮换闸门**（2026-10-31 竞态修复：确认返回
  与轮换之间编辑器实时脏态翻 true——确认链最后一次复核之后的敲入——
  必须重走一次确认，干净后才轮换；闸门读 `editorLiveState` 而非已被
  markSaveConfirmed 清除的 `editorDirty` 闩锁，绝不带着脏信号轮换），
  然后才 `rotateEditorKey`——重取 editor-config 即
  轮换 document key（旧编辑实例回调服务端 409），**响应不缓存不渲染**，
  请求失败阻止切换（旧 key 仍有效时切走即留下"迟到回调覆盖本机上传"
  的窗口）；再清 editorConfigs（编辑器随渲染分支卸载销毁）。**会话全程
  保留**——本机上传依赖有效会话。切回在线重新取配置（旧配置 token
  绑定旧修订号，不得复用渲染）。切换文件/返回详情不需要闸门：不轮换
  key，编辑器销毁时 DS 的收尾回调（会话活跃 + key 现行）照常落盘。
  - **下载草稿（handleDownloadDraft，文件管理行与本机面板共用入口）**：
    在线编辑中先走确认链路（kind='download_draft'，确认失败不下载，
    重试按钮=重试下载）；下载前 refreshFiles 读取服务端修订号，
    downloadFile 真实完成后 `recordLocalBaseline` 记录**基线修订号**；
    无会话的查看者仅下载不记录基线。
  - **本机上传（EditorArea 本机面板 → uploadLocalDraft）**：必须携带
    基线修订号（**绝不改用上传前刷新得到的较新修订号**，服务端草稿已
    推进时后端拒绝覆盖、提示重新下载）；.docx 客户端先行校验（.doc
    拒绝，后端独立校验）；成功提示只在真实成功响应后，成功清基线并
    refreshFiles；"草稿已被其他会话更新"=基线过期，清基线要求重新下载，
    **会话保留**（该文案含"会话"一词，uploadLocalDraft 特判不走
    handleSessionRelatedError 清会话规则）；其余错误沿用既有分类
    （会话类清会话、密码类回密码门）。无基线时上传以 message.warning
    阻止并提示先下载。
  - **重试语境**：`finishingShared.js` 的
    finishingErrorTitleOf/finishingRetryLabelOf + `store.finishingErrorKind`
    （''=重试保存（原语义不变）/'switch_local'/'download_draft'），
    工作台文件头部 Alert 与放大态 ExpandedBar 共用，重试分发在
    工作台 handleFinishingRetry。
  - 行为测试：`draft.store.localEdit.test.js`（effectiveEditMode 三态/
    切换=确认→轮换→清配置/确认失败不轮换/轮换失败阻止/基线上传契约/
    状态清理）、`draft.workspace.localEdit.test.js`（Segmented 主动切换/
    未确认阻止与重试切换/未配置直接本机无切换控件/加载失败入口/
    下载基线/上传成功-失败-拒绝）；后端行为钉死在
    test_manual_local_upload.py。
- **一切内容接口按文件走**：`/files/`（有序清单，条目内嵌
  draft+active_session+submission）、
  `files/<fid>/draft/{create,session,save,download,preview-url,editor-config,forcesave}/`、
  `files/<fid>/{rename,move,remove}/`。**不得再调用旧单文件接口**
  （`/draft*`、`/originals/` 列表/上传）——后端对多文件制度一律拒绝。
- 会话按文件：sessionStorage 键 `institution_edit_session_<manualId>_<fileId>`
  （跨页签恢复、离开不清除，退出走显式按钮=服务端 revoke）；已验证密码仅存内存。
  保存失败错误文案含"会话"只清该文件会话（可重开），纯"密码"类才回密码门；
  拦截器已提示，不得二次弹错。
- **编辑中禁止重复 fetchEditorConfig**（轮换 document key 使当前编辑器回调失效）；
  编辑器组件以 `fileId:document_key` 为 key——切换文件/重开会话时销毁重建。
  刷新状态走 `refreshFiles()`（清单内嵌草稿信息，不再单拉文件草稿详情）。
- 文件管理：新增（files/create，multipart，先选文件→分工弹窗可指定
  负责人/分工说明（不传即"未分配"，FormData 携带 owner_id/note），
  `draft_error` 非空=文件已建但草稿未就绪，只警示不算失败）、改名、
  上移/下移（move 传目标序位，成功后从服务端重取清单）、
  移除（Popconfirm；最后一份/有活跃会话会被后端拒绝）。单文件制度不渲染清单侧栏。
- **文件分工（2026-10-29）**：清单行显示 负责人/未分配 Tag；选中文件卡
  Descriptions 展示负责人与分工说明；负责人（`assignment.is_mine`）可
  「提交编制」（确认后 POST `files/<fid>/submit/`，成功提示后
  refreshFiles）——提交后草稿再次保存/重建，提交状态由后端按修订号
  比对自动失效，前端不得据本地状态判断"已完成"。
- 上传控件不得嵌套 file input：统一隐藏 input + ref 程序触发 `click()`
  （originals.upload.test.js 钉死）；新增上传入口照抄该模式。
- 编辑器组件坑：DocsAPI.DocEditor 会把占位 div 替换成 iframe，占位节点必须用 ref
  宿主命令式创建/清理（React 17 卸载已消失节点会崩）；api.js 模块级单例加载。

## 三·补、草稿恢复优先级（2026-10-29，最重要）

- **恢复优先级由后端权威决定，前端不猜恢复来源**：无草稿文件的恢复入口按
  files 清单行下发的 `draft_recovery` 渲染——`source='current_version'`（含
  version_no）显示「从当前生效版本恢复草稿」；`source='original'` 且无
  `requires_confirm` 显示「从初始原稿创建草稿」（仅制度从未发布过版本）；
  `requires_confirm=true`（当前版本不含该文件/已废止）只能走「高级恢复」，
  明确确认后按指定原稿重建。**不得静默调用最近原稿**（draft.recovery.test.js 钉死）。
- 恢复动作统一 POST `files/<fid>/draft/create/`：默认路径空体（后端按
  已有草稿拒绝 > 当前生效版本快照 > 最近原稿 的优先级执行）；高级恢复携带
  `{original_id, confirm: true}`，工作台在密码门之后传已验证密码。
- 无草稿文件的工作区渲染恢复面板（Alert + 按钮），**不得渲染空白编辑器、
  不得出现"草稿已保存"语义**；恢复成功提示带新修订号与来源版本
  （draft 字典的 `base_version_no`，"基于版本"展示同样用它）。
- 草稿详情/会话等接口对无草稿文件返回 HTTP 200 + `error` + 顶层
  `draft_recovery`；注意 http 拦截器 reject 只带 error 字符串，前端要读
  结构化恢复途径必须用 files 清单行，不要指望从 reject 值取字段。

## 四、详情页约定（2026-10-29 交互优化版）

- **四、文件清单页签（FileListTab，默认，2026-10-30 双视图版）**：
  - **页签内两个内容视图（antd Segmented 切换，不新增顶层页签）**：
    「当前生效版本 vN」=最近一次发布的不可变快照清单（行=versions/<vid>/
    files/ 的 items；预览/下载始终打开发布快照，按钮文案「预览当前生效版」、
    预览标题「预览当前生效版 vN：文件名」、下载 Tooltip 均注明版本来源；
    已从待发布移除的文件以行内「已从待发布移除」Tag+顶部提示呈现——取代
    旧独立已移除分区；已移除条目不在 /files/ 中、负责人未知，显示「-」
    绝不显示误导性「未分配」）与「修订草稿」=待发布工作内容（行=/files/；
    列=顺序/文件名/大小/草稿修订 rN/负责人/状态/编制提交/操作；预览/
    下载明确打开待发布草稿「预览草稿 rN」，预览标题「预览待发布草稿
    rN：文件名」，仅持编制角色者渲染——后端草稿预览/下载要求
    draft_edit+can_edit_draft，前端不扩权）。**默认视图**：有生效版本→
    当前生效版本；首次发布前→修订草稿；仅查看角色只有生效视图（无切换
    控件、不请求 draft-status）。**切换视图**：保留「只看我负责的文件」
    筛选并清空行勾选（批量分工属草稿视图操作）；生效视图无 草稿修订/
    状态/编制提交 列（断言列是否存在以 th 文本为准——页签说明文案会
    提到这些词，不能用整页文本 contain/not-contain 判定）。
  - **负责人=责任归属、提交=交接状态（视图说明与 Tooltip 必须表达）**：
    负责人不因负责身份获得或失去编辑权限（编辑=draft_edit+编制角色+
    单写会话，同一文件同一时间仅一人）；「编制提交」是交接标记不代表
    已发布——提交有效=提交时修订号与当前草稿一致（预览草稿即为提交时
    内容），草稿变更后=「提交已失效」；**系统不保存提交时刻的文件副本
    （无历史快照机制）**，该限制必须在说明文案与 Tooltip 中明确，
    绝不把最新草稿冒充"已提交版本"、绝不提供"已提交版本"预览。
    2026-10-31 起生效视图不展示负责人（修订分工属修订草稿视图，分工
    入口保留在草稿视图负责人列；生效视图行的 assignment 关联仅为
    「只看我负责的文件」筛选保留，不得移除）。
  - **版本来源全模块持续明确（2026-10-30）**：PreviewModal 增加可选
    title 属性（缺省回退通用标题），各预览入口必须传说明来源的标题——
    FileListTab 生效视图=预览当前生效版 vN / 草稿视图=预览待发布草稿
    rN；VersionsTab=预览历史版本 vN（版本行/清单 Modal/已移除行按
    previous_version_id+fm.previousVersionNo）；FileChangeTab=预览历史
    版本 vN（r.version_no）；OriginalsTab=预览初始原稿/预览后续来源
    原稿；草稿工作台=预览待发布草稿 rN。不能仅凭颜色、修订号或位置
    暗示来源。
  - **状态列（唯一合并呈现）**：`draftStatusShared.buildFileState(file,
    relation)` 把 服务端内容关系（draft-status 行）+ 修订进行中（
    `file.revision_open`）+ 编辑占用 合成一句可懂短语：修订中 · 有未发布
    修改 / 修订进行中（暂无变化）/ 有未发布修改 / 新增待发布 / 待首次
    发布 / 「某人」编辑中 / 草稿未就绪 / 已生效；未加载/失败显示占位
    「—」，**绝不渲染"一致/无变化/已生效"语义**；renamed 附加「已改名」
    Tag。前端不得自行推断。
  - **行操作按修订状态分叉**：`revision_open=true` → 「继续编辑」直接
    深链 `?file=`（不调接口，直接复用工作副本）；`revision_open=false`
    → 「开始修订」是真实状态动作（先 `store.startRevision` 再深链）；
    返回 `needs_repair` 时弹确认窗明确提示 修复来源=当前生效版本快照
    （绝不改用初始来源），确认后携带 `confirm_repair=true` 重试。
    提交编制（is_mine）与「变更记录」不变；**操作列不再有「文件分工」
    链接（入口在负责人列）**。
  - **文件分工入口在负责人列**：有分工权限者点击姓名/「未分配」直接打开
    FileAssignmentModal；无权限者只读。**权限判定是两层与（2026-10-31
    授权模型修订，与后端写接口完全一致）**：`institution.manual.draft_edit`
    页面权限 **且**（手册所有者 `is_owner` 或制度管理员 `is_admin`）——
    缺 draft_edit 或非所有者/管理员时保存必然"权限拒绝"，入口必须只读，
    不得出现可点击但保存必然被拒的链接/批量栏/勾选列。**批量分工
    （2026-10-30）**：勾选多份文件（仅活动行可勾选）出现批量分工栏
    （已选数量+文件名清单），「批量指定负责人」开批量弹窗（明确作用
    范围、不预填现有负责人）、「清空负责人」需确认；提交经
    `store.batchAssignFiles`（后端全成功或全失败），成功后清空勾选；
    **筛选（只看我负责的文件）切换、刷新、「清除选择」都清空勾选——
    不得对筛选后不可见的文件误操作**。
  - **负责人候选唯一来源（2026-10-31 口径修订，最重要）**：分工弹窗与
    草稿工作台新增文件的负责人下拉一律走
    `GET manuals/<pk>/assignment-owners/`（仅 `id+name` 最小字段，权限与
    分工写路径一致；**候选=持本手册 can_edit 编制授权的启用账号**，
    负责人独占编辑要求被指派账号具备编制资格，无资格指派后端拒绝）；
    **禁止改回账号管理列表 `/api/account/user/`**（要求
    `system.account.view`，无账号查看权的分工用户即"权限拒绝"，候选还被
    吞成空列表——本接口为修复该缺陷而设）。候选请求带
    `skipErrorNotification: true`，**失败在弹窗内展示明确错误与「重试」
    按钮**（错误只展示一次，不得与 HTTP 拦截器重复弹窗），绝不把失败
    静默表现为空候选列表。
  - 行来源/已清理快照/错误重试口径与 2026-10-29 版一致（"已移除"自
    双视图版起在生效视图行内 Tag 呈现，独立分区已取消）。
  - 「只看我负责的文件」继续按服务端 `assignment.is_mine` 过滤。
- **发布（PublishButton，头部整套状态旁）**：点击先拉 `publish-preview/`
  分组预检；确认窗口**重点展示实际变化文件（新增/修改/移除/受阻），未修改
  文件以数量汇总、经自包含组件 UnchangedGroup 展开/收起核对完整清单**
  （Modal.confirm 内容是打开时快照，外层 setState 不会重渲染——展开状态
  必须由内嵌组件自持）；受阻行处理入口与确认禁用同旧版；**`has_changes=
  false 且非首发` 时提示"无需重复发布"并禁用确认**；整套状态无待发布变化
  时（draftStatus.summary.has_current_version && !has_pending_changes）
  发布入口弱化为非主按钮（发布者仍可点开核对）。仅发布角色+手册启用渲染。
- **版本与发布页签（VersionsTab）**：聚焦发布历史；版本行展示文件总数、
  "查看文件清单"Modal 展示该版本完整快照（名称/顺序/大小/哈希/变更标签/
  最近变更版本），`removed_items` 单独分区并可经
  `previous_version_id/previous_snapshot_id` 预览/下载上一版快照；
  行内下载在 `files.length>1` 时仍开清单 Modal；单文件版本保持旧接口直下。
  整套回退（from-version）确认文案=以该版完整清单重建待发布草稿集合
  （会失效进行中的编辑会话），响应 `{restored_files}`。
- **文件变更记录页签（FileChangeTab）**：文件下拉数据源=`originals-overview/`
  聚合全集（**含已移除文件**，选项内标注「已移除」Tag；键为 `file_id` 不是
  id——已踩坑，操作记录分页同样必须传 `selected.file_id`），选中后并行拉
  `files/<fid>/version-history/`（服务端按快照哈希算每版 change_type +
  `is_cleaned`；被移除期间的版本不出现）与 `operation-logs/?file_id=`
  （后端过滤+分页）；**已清理快照行只显示元数据与「已清理」Tag，不渲染
  预览/下载**；无发布可见权时不发 version-history 请求、只展示操作记录并
  说明；操作文案/详情解析共用 `oplogShared.js`；聚合清单失败置
  `originalsOverviewError`+重试（fetch 链必须 .catch）。
  **跳转目标解析统一走 `syncSelection`（幂等）**：页签保持挂载期间再次
  「变更记录」由 CDM 里创建的 mobx `reaction(store.fileChangeTarget)` 消费
  （2026-10-30 修复，勿回退为仅 componentDidMount 消费）；全集加载中或
  加载失败保留目标待重试；目标不在全集回退首个文件（选中与展示始终一致，
  绝不把旧文件记录冒充目标文件）；`selectFile` 切换文件先
  `store.clearFileRecords` 防旧记录残留（同文件重复跳转不清空）；
  `fetchFileVersionHistory/fetchFileLogs` 带 reqSeq 守卫——快速切换文件/
  翻页时较早请求的迟到响应不覆盖当前文件。
- **初始来源页签（OriginalsTab，2026-10-29 改版，最重要）**：挂载即一次拉取
  `originals-overview/` 聚合清单（store.originalsOverview，每份制度文件一行，
  **不得**再渲染逐文件选择下拉、不得为每一行单独调 `files/<fid>/originals/`）。
  行内展示 文件名（已移除加 Tag）/最初原稿的上传人与时间/首次发布版本
  （`first_published_version_no`，原稿保护边界）/预览/下载；多条原稿记录在
  该行展开历史（expandedRowRender），明确区分「最初原稿」与「后续来源」，
  已清理记录只显示"已清理"+清理时间，**不渲染** 预览/下载/重建 按钮。
  失败置 `originalsOverviewError` + 重试，不以空列表冒充成功；0 文件手册
  渲染空态引导，"上传文件（每份各建一个制度文件与草稿）"是唯一内容入口。
- **新增与更换来源严格分开**：「新增制度文件」按钮批量上传，每个所选文件
  逐个走 `files/create`（每份各建一个条目+原稿+草稿，draft_error 只警示），
  绝不把多个文件追加到同一项；「更换来源」是行级受控操作——先选文件，
  再弹确认（明确目标文件名与"不会改动当前草稿（rN）"的影响说明），确认后
  才逐个走 `files/<fid>/originals/upload/`。两者共用一个隐藏 file input
  （ref 程序触发，state.pendingReplace 分支语义），**input 不得嵌套在
  Button/label 内**。
- 「从原始上传文件重建草稿」：主行按钮基于最初原稿，历史行按钮基于该条
  记录；制度**未发布过版本**直接可见（普通确认，携带 original_id）；
  **已发布过版本（manual.has_versions，含已废止）默认隐藏**，收进
  「高级恢复操作」展开项，重建弹窗必须含风险提示（会以原始文件替换当前
  草稿、不可撤销）+ `confirm: true`，丢弃现有草稿且配置了编辑密码时还须
  输入编辑密码（后端独立校验）。原稿已按保留策略清理（`is_cleaned`）时
  重建入口不渲染（后端也拒绝）；清理后可在该行「更换来源」上传新原稿
  恢复重建能力。
- 版本行内「从历史版本回退」（from-version）与「从原始上传文件重建草稿」
  是两个不同语义：前者以历史版本完整快照为基线整套重建，后者以原始上传
  文件为基线单文件重建；文案不得混用。
- **版本保留状态展示（VersionsTab）**：版本行状态列展示「长期保留」
  （long_term_protected）、「文件已按保留策略清理」（cleaned）/「部分文件
  已清理（不可完整回退）」（partial，Tooltip 带 files_clean_error）Tag；
  已清理版本**不渲染** 预览/下载/回退 按钮；「设为/取消长期保留」仅对
  非 current 版本且持 publish 角色渲染，成功后重拉 versions。版本文件清单
  Modal 内已清理快照不渲染预览/下载。

## 四·补、草稿状态摘要与逐份关系（2026-10-29）

- **数据源唯一**：`GET manuals/<pk>/draft-status/`（detail store 的
  `draftStatus/draftStatusError/isFetchingDraftStatus`）——逐份"草稿 vs
  当前生效版本"关系与整套摘要全部由服务端按快照哈希/名称/序位计算，
  **前端不得以修订号或文件名推断内容是否变化**；"存在草稿（rN）"与
  "存在待发布变化"分开表达。接口权限=工作区可见（编制/发布角色或管理
  权限），仅查看角色不渲染也不请求（DraftStatusSummary/各刷新点均以
  `canViewWorkspace` 或 store.`fetchDraftStatusIfAllowed` 守卫，后端独立
  拒绝）。
- **头部摘要（DraftStatusSummary，详情页显眼位置，与 PublishButton 并排）**：
  一致 → 明确显示 "已生效（vN，共 N 份文件），无未发布修改"（2026-10-30
  措辞，不再出现"当前草稿与生效版本一致"的双版本对照语义）；有待发布
  变化 → 逐项罗列（N 份文件有未发布修改/新增/被移除/已改名/顺序已调整/
  缺草稿）；修订进行中 → "N 份文件修订进行中"（与待发布变化分开表达，
  无变化时注明"暂无待发布变化"）；无生效版本 → "等待首次发布"；存在
  unconfirmed（编辑中/草稿文件缺失）→ 显示"暂不能确认"并**绝不显示
  已生效**；加载失败 → 错误+重试，不得以旧状态或"无变化"冒充。文案映射
  集中在 `draftStatusShared.js`（`buildFileState` 是文件清单状态列的唯一
  渲染依据）。
- **文件清单页签**：新增"草稿 vs 生效版本"列（DraftRelationTag；
  renamed 附加"已改名"Tag + 旧名 Tooltip）；状态未加载/加载失败显示
  占位"—"与重试入口，**不得渲染"一致/无变化"语义**；页签挂载即拉取。
- **刷新契约（禁止固定周期轮询）**：详情进入（index.componentDidMount
  → `store.fetchDraftStatusIfAllowed`）、文件清单页签挂载、发布/回退/
  废止（统一走 `store.refreshAfterLifecycle`）后重新拉取；草稿保存、
  ONLYOFFICE 回调、文件增删/改名/排序发生在草稿工作台，返回详情页即
  重新挂载刷新。测试钉死在 `__tests__/draft.status.test.js`、
  `FileListTab.test.js` 与 `detail.store.test.js`（refreshAfterLifecycle
  成功/仅查看不请求/废止清空生效区）。
- **保存状态语义（草稿工作台/文件清单通用）**："最后保存"一律取服务端
  草稿的 last_saved_at（ONLYOFFICE 回调真实落盘后才更新）——回调未完成
  时**不得显示"已保存"**；仅有编辑会话**不得称为"未保存"**（会话≠未
  落盘，未保存拦截只做 beforeunload 不出文案）；加载失败不得显示
  "已同步/无变化"。

## 四、预览与下载

- 预览统一走后端 `preview-url` 端点返回的短时效链接（kkFileView），`detail/PreviewModal.js` iframe 承载；不在 URL 拼 x-token。
- 下载统一走 `utils.downloadFile`（blob），文件名用接口返回的 `file_name`。

## 五、测试

- `__tests__/` 十余个套件：ManualForm 载荷/渲染、Table 渲染（含 work_status
  工作状态列八态（含 revising）与仅查看不下发；2026-10-31 增 归属 org_* 与
  所有者列/未指定提示）、draft store（会话
  按 (manualId,fileId)；含 开始修订/批量分工 的 store 行为；落盘确认
  核心与离开保护拆分至 draft.store.confirm.test.js：复核轮防他处推进
  误判/超时最终复核/confirmFileSave 不撤销会话/editorDirty 闩锁）、
  draft workspace 组件行为（含 新增文件分工弹窗携带 owner_id/note、清单行
  负责人/未分配、is_mine 提交编制；切换/返回离开保护与独立保存状态
  显示拆分至 draft.workspace.leaveGuard.test.js）、draft recovery（无草稿恢复入口三态/
  已有草稿不自动替换/失败不假成功；恢复面板 2026-10-31 拆出
  RecoveryPanel 组件，行为断言不变）、本机编辑（编辑方式切换/确认-轮换/
  基线上传契约/上传成功失败与重试拆分至 draft.store.localEdit.test.js 与
  draft.workspace.localEdit.test.js；OnlyOfficeEditor 失败上报
  onUnavailable/onReady 在 draft.editor.test.js）、detail store（含 版本错误态/
  refreshAfterLifecycle 生命周期统一刷新/originals-overview 聚合与错误态/
  startRevision 携带 confirm_repair/batchAssignFiles 就地更新与失败不动清单；
  2026-10-31 增 逐本账号授权与所有者：fetchAuthorizations/saveAuthorizations
  （PUT 全量 items+editor_can_view_published，透传 revoked_sessions）/
  account-options·owner-candidates skipErrorNotification/owner POST 与回退
  刷新/reset 清理）、ConfigTab.authorization（2026-10-31 授权模型：所有者卡
  admin 指定/移交与 owner 只读、授权行三布尔与删除/添加账号候选过滤/
  保存载荷与 revoked_sessions 提示/清单与候选失败卡片内重试/config-only
  只读说明/密码卡按 config 码收窄；页签可见性钉死在 detail.index.tabs）、
  FileListTab（修订状态版：状态列合并短语/旧主列不出现/开始修订与继续编辑
  分叉/needs_repair 确认修复/批量分工勾选与清空/筛选清空勾选/行合并/新增
  与已移除呈现/清理快照/深链/废止；2026-10-31 增 负责人独占：负责人行
  编辑入口与非负责人「编辑限负责人」占位/仅发布角色无编辑入口）、
  fileAssignment（文件清单分工：负责人列
  点击弹窗/无「文件分工」按钮/编制提交三态、只看我负责的筛选、批量弹窗
  数量与范围/勾选清空、提交编制 is_mine 行、旧章节只读过渡面板；
  2026-10-30 增补：无 draft_edit 只读无批量入口/2026-10-31 起
  draft_edit+所有者或管理员可点击）、draft.workspace（2026-10-31 增
  负责人独占与文件管理门控拆分：非负责人无开始编辑/下载预览仅负责人/
  改名移除新增限所有者或管理员/密码门未指派提示）、
  FileAssignmentModal（分工回填与 owner_id 显式提交/未分配=null/批量模式
  数量范围不预填；2026-10-30 增补：候选走 assignment-owners 且抑制拦截器
  弹错/候选失败弹窗内错误+重试成功）、draft.workspace（2026-10-30 增补
  新增文件候选失败与重试同口径）、PublishButton（分组预检确认窗：变化突出+未修改折叠展开/
  无变化禁用确认/负责人与提交状态行/受阻处理入口+确认禁用/失败不清数据/
  角色可见性+无待发布变化弱化入口）、originals.upload（聚合清单
  无下拉/批量新增逐文件建项/更换来源受控确认/已清理记录不可用按钮/展开历史最初
  与后续区分/高级恢复确认链；2026-10-31 增 更换来源/新增限所有者或管理员、
  重建草稿=文件负责人独占）、FileChangeTab（originals-overview 全集下拉含已移除/
  清理快照仅元数据/预选 fileChangeTarget/失败重试/**页签保持挂载时再次跳转
  A→B→A 与同文件稳定/全集加载中保留目标/目标缺失回退首文件/操作记录翻页传
  file_id**）、detail.fileChange.jump（真实 detail/index+FileListTab+
  FileChangeTab+真实 store 的全链路跳转集成测试，钉死已挂载页签二次跳转回归）、
  VersionsTab 渲染（版本文件
  清单变更状态+removed_items/失败不清数据/重试/保留策略状态与长期保留标记/
  已清理版本关闭预览下载回退）、draft.status（DraftStatusSummary 摘要八态：
  已生效/修订进行中/变化/首发/暂不能确认/缺草稿/失败重试/仅查看）等。
  注意：antd Modal 经 portal 渲染到 document.body，断言须查 document 而非局部容器；
  Select 预填值要等 owners 异步加载后（flush）才显示昵称。
- libs mock 必须含 `Permission: {isSuper: false, permissions: []}`（AuthButton 解构依赖）；
  `hasPermission` 用 mockImplementation 精确控制码值，避免误放行；**jest.clearAllMocks
  不恢复 mockImplementation**——收窄权限或失败注入的用例必须在 beforeEach 显式复位，
  否则泄漏到后续用例（FileListTab/FileChangeTab 套件已踩坑并钉死）。
- 运行：`cd spug_web && CI=true npx react-app-rewired test --watchAll=false --testPathPattern "src/pages/institution"`。
- 坑：mock 数据里的时间值不要用"今天"附近（如 expires_at=今天中午），会随运行时刻变成时间炸弹；store mock 返回的是实例本身，`require('../store')` 无 `.default`；antd 两字中文按钮仅在**非 link 型**插空格（"重 试"），按钮查找要归一化空白；部分 mock antd 时用 `jest.requireActual` 展开（message 用 Object.assign 覆写以便断言成功提示）；originals-overview 行键是 `file_id` 不是 `id`。
