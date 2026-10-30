# apps/institution/AGENTS.md - 制度管理模块后端规则

> 2026-10-27 新增。通用规则见 `spug_api/AGENTS.md`；本文件只记录制度管理独有的例外与状态机。
> **2026-10-29 多文件改造已落地**（迁移 0003）：一项制度可含多份 Word 文件，
> 文件级编辑/会话/修订，发布形成整套不可变快照；旧单文件接口进入过渡委托期。
> **2026-10-29 文件分工已落地**（迁移 0005）：分工单位=整份制度文件，字段在
> `ManualFile` 上；"提交编制"记录提交时草稿修订号、按计算式失效；旧
> `ManualChapter`（章节分工）为遗留只读数据，写接口全部关闭，记录供人工核对。
> **2026-10-30 发布后修订状态已落地**（迁移 0006）：修订进行中是显式持久状态
> `ManualFile.revision_open`，发布成功才对发布清单内文件关闭；发布失败不触碰
> 任何状态；无内容/结构变化拒绝重复发布；批量文件分工落地（改派/清空负责人
> 即重置提交编制）。

## 〇、生产延迟上线门控（2026-10-28）

- 制度管理在 `spug/settings.py` 的 `RELEASE_PENDING_APPS` 门控清单内：命中时 app 摘出
  `INSTALLED_APPS`（不建表、migrate 跳过），路由经 `spug/urls.py` 的 `_pending_app_urls`
  延迟注册（与 coop_task / equipment_lifecycle 同一机制，**不得**把 institution 路由放回
  无条件 urlpatterns）。
- 门控开启时无任何跨模块 FK 指向本模块，`manage.py check` 无需 SILENCED_SYSTEM_CHECKS
  豁免；回归测试在 `spug_api/tests/test_release_pending_gating.py`（含 EL+institution 双门控
  与 check 通过用例）。
- 前端入口（routes.js 三条 institution 路由）保持权限驱动，不做运行时探测：门控期间普通
  用户不可见，超管因 `hasPermission` 对 isSuper 短路仍会看到菜单（与 equipment_lifecycle
  门控生产行为一致）；**门控期间不得在角色管理中授予 `institution.manual.*` 权限码**，
  否则入口可见但 API 全部 404。


## 一、模块边界

- 制度管理（Word 手册）与规章管理（`regulation`，规章台账）是两个并列模块：手册正文的草稿/版本语义归本模块，规章台账及其附件仍归 regulation，互相不引用附件。
- 预览复用 kkFileView + evidence 的 `attachment_preview_token`（module='institution'）。
- 在线编辑接入 ONLYOFFICE Docs（2026-10-27 定型）：后端 `onlyoffice_jwt.py`（HS256 最小实现，无 PyJWT 依赖）+ `editor_services.py` + `views_draft.py` 的 `EditorConfigView / OoEditorFileView / OoEditorCallbackView`。配置经 `ONLYOFFICE_DOCS_URL / ONLYOFFICE_JWT_SECRET / ONLYOFFICE_PUBLIC_BASE_URL / ONLYOFFICE_ALLOWED_URL_HOSTS` 注入，secret 未配置时 `editor_available=false` 整体降级（下载→本机编辑→上传 multipart `draft/save/` 仍可用且共用会话+修订号保护）。
- **DS 中文字体（2026-10-29）**：原版 `onlyoffice/documentserver:8.1` 镜像零中文字体（此前容器内的宋体等系手工塞入，重建即丢，表现为编辑视图与 WPS 渲染不一致复发）。dev compose 已把 `dev/onlyoffice-fonts/`（17 个常用中英文字体，不入 Git，目录内 README 有清单与步骤）只读挂载到 `/usr/share/fonts/custom`；字体索引（AllFonts.js/font_selection.bin）写在 `/var/www/onlyoffice/documentserver/`、不在 onlyoffice-data 卷，**增删字体或容器重建后必须重跑 `documentserver-generate-allfonts.sh`**（结尾自动重启 ds:docservice/ds:converter；supervisord 服务名带冒号 `ds:docservice`）。生产接入 institution 时，生产 compose 的 onlyoffice 服务必须带同样挂载与索引生成步骤。
- **后端转换容器的 LibreOffice 与字体（2026-10-29）**：`.doc→.docx` 转换跑在 tdyw 后端容器。dev 镜像 `tdyw:django42-stage2` 原构建配方已失传，现由容器 `docker commit` 固化（2026-10-29 容器内补装 `libreoffice-writer + fonts-noto-cjk` 后 commit；旧镜像备份标签 `tdyw:stage2-backup-20261029`）——**用旧镜像或删容器重建会同时丢 LibreOffice 与中文字体，`soffice` 缺失时 .doc 上传直接走降级报错分支**。字体走 `dev/onlyoffice-fonts/` 挂载（与 onlyoffice 共用目录），后端无需 AllFonts.js 等价物。生产镜像按 `docker/Dockerfile` 构建（已含 fonts-noto-cjk + libreoffice-writer），发布前须确认生产镜像实际包含两者。真实手册样本的版式保真（页眉页脚/复杂表格/域/批注/修订/分页）仍属待真实样本验证项，字体齐备只保证不出方框与度量接近，不承诺复杂版式一致。

## 二、授权模型（最重要的不变量）

1. **业务授权完全按"账号角色 ∩ 手册关联角色"判定，`tenant_id` 不参与任何归属/可见/编辑判断**（tenant_id 仅按全局约定保留在模型上）。跨租户持角色可见是预期行为，测试已钉死（test_manual_crud.test_list_visibility_by_roles_not_tenant）。
2. 两层权限独立生效：页面级 `@auth('institution.manual.<action>')` + 手册级 `services.can_view_published / can_edit_draft / can_publish`。后端每个入口分别校验，不信任前端按钮。
3. 管理操作（手册元数据、类别、角色关联、密码）走模块权限码（edit/config/add/delete）；内容操作（草稿、发布）必须持有对应手册角色。
4. 权限码清单：view/add/edit/delete/config/upload/download/draft_edit/publish，定义在 `spug_web/src/pages/system/role/codes.js` 的 `institution.manual` 组。平台级角色（tenant_id=''）仅超管可维护/分配（RoleOptionsTests 已钉死）。

## 三、密码与会话

- `Manual.password_hash` 只存 Django 密码哈希器结果；接口/日志/序列化一律不回传（详情只给 `has_password`）。
- 连续错 5 次锁 15 分钟（`PASSWORD_MAX_FAILS/PASSWORD_LOCK_MINUTES`）；重置密码使全部有效编辑会话失效（`set_manual_password → revoke_manual_sessions`）。
- 单写约束：`ManualEditSession` 每手册同一时间一个活跃会话；同账号复用同一会话（多标签），他人开启被拒；保存时实时重校验会话+角色+修订序号。**（2026-10-29 多文件改造后按文件生效：见第七节第 2 条）**
- 修订序号 `ManualDraft.revision` 单调递增（创建/保存/回退各 +1），迟到回调、旧标签页、过期会话凭旧修订号一律拒绝。**（2026-10-29 起按文件递增）**

## 四、文件与转换

- 存储根 `storage/institution/{originals,drafts,versions}/manual_<id>/<yyyymm>/`，相对路径不含 `institution/` 前缀（`resolve_absolute_path` 负责拼根+防穿越）。**新增文件类别必须同步 `build_relative_path` 与 `safe_delete_manual_dir`**。
- **显示名与存储名分离（2026-10-29）**：三张文件表的 `original_name` 一律存用户可读显示名（`storage.display_name`），`file_path` 存带唯一后缀的存储名（`build_stored_name`），序列化 `file_name` 与下载/预览文件名取显示名。ONLYOFFICE 回调协议不带文件名，回调保存以 `手册名.docx` 为显示名；发布沿用草稿显示名，遇系统生成名（`callback_`/`oo_cb_` 前缀的历史脏数据）回退为手册名并顺带治愈草稿。禁止再把 `os.path.basename(存储路径)` 当显示名写入。
- 原稿永不覆盖：每次上传新 `ManualOriginal` 行 + 新文件；发布版文件复制到 `versions/` 独立存储，SHA256 入库，发布后绝不改写；废止只置 `is_effective=False` + `manual.current_version=None`；回退=以旧版本为来源重建草稿，再发布产生新版本号。
- **保留策略（2026-10-29，重要）**：原稿本体与版本快照文件不再绝对"永不删除"，但**业务流程（编辑/保存/发布/回退/重建）仍然绝不删除**——物理删除只能经 `retention_services.py` 的保留策略入口（`cleanup/preview/` 只读预检、`cleanup/execute/` 可控幂等执行，均 `@auth institution.manual.config`，无定时任务）。不变量见第九节。
- `.doc → .docx` 转换用 LibreOffice headless（`services.ensure_docx_workfile`）。三个已踩坑点必须保持：① 必须显式 `-env:UserInstallation=<profile URI>`，URI 用 `Path.as_uri()` 生成（手工拼 `file://<path>` 在 Windows/含空格路径下必然失效）；② 源文件必须先复制为 ASCII 名 `input.doc` 再转（容器 locale 下中文文件名无法加载）；③ 源文件形参名为 `src_abs_path`（曾因误写 `src_abs` 触发 NameError 使 .doc 转换整体 500）。生产镜像已加 `libreoffice-writer`（docker/Dockerfile），缺失时转换报业务错误并降级（预览/下载不受影响）。
- 手册删除：有发布版本时拒绝（提示归档）；无版本删除遵循第十二节——先 `safe_delete_manual_dir` 清文件树，成功后才删数据库记录，清理失败直接拒绝（重试幂等），绝不先删库再 on_commit 删文件。
- 草稿替换（保存/原稿重建/版本回退共用 `_create_draft_record`）：旧草稿物理文件在事务提交后清理（`transaction.on_commit`），回滚则保留旧文件与旧记录一致；`drafts/manual_<id>/` 不得无界增长（forcesave 回调每次都产新文件）。
- 本模块 8 个模型均显式声明 `objects = TenantModelManager()`：mixin 上的 manager 会被 Django 自动补的默认 Manager 遮蔽（只对模型自身 classdict 里的 Manager 做 add_to_class），省略即静默退化为原生 Manager，新增模型必须带上（TenantManagerDeclarationTests 钉死）。

## 五、preview-file 与 ONLYOFFICE 专用通道约束

- **forcesave 落盘确认端点（2026-10-30）**：`POST manuals/<pk>/files/<fid>/draft/forcesave/`
  （`views_editor.FileDraftForcesaveView`，`transaction.non_atomic_requests` 注册——
  视图内有对 DS 的出站 HTTP 调用；权限= draft_edit + can_edit_draft + 该文件
  `get_active_session` 有效会话）是"保存并结束编辑"落盘确认的唯一服务端入口。
  实现 `editor_services.request_forcesave(session)`：POST DS Command Service
  `{c: forcesave, key: session.current_doc_key}`（JWT 以 body token +
  Authorization Bearer 双通道携带，载荷含 c/key）；端点自动适配
  `/command`（DS 8.2+）与 `/coauthoring/CommandService.ashx`（8.1 等
  旧版，404 即回退并缓存探测结果）。响应语义：`error 0`→
  `{'forcesave': 'requested', 'revision': 请求时刻修订号}`（前端轮询
  修订号越过该基线确认回调落盘）；`error 4`→`{'forcesave': 'no_changes'}`
  （DS 无修改，可安全结束）；`error 1`（key 不存在，如编辑器已关闭/DS
  重启）与其他码→业务错误，**绝不冒充成功**。基址推导
  `command_base_url()`：显式 `ONLYOFFICE_COMMAND_BASE_URL` >
  `ONLYOFFICE_DOCS_URL` 为绝对地址 > `ONLYOFFICE_PUBLIC_BASE_URL` +
  相对路径；不可推导返回空并整体拒绝。forcesave 只是触发：真实落盘
  仍走既有回调链路（status 2 → save_file_draft 推进修订号），会话撤销
  永远发生在轮询确认之后（撤销先于落盘则回调被 403 拒绝、内容不落盘，
  test_manual_forcesave 钉死）。

- 通用 preview-file 路由（`<kind>-<id>`）不加 `@auth`，由中间件按 `*/attachments/*/preview-file/*` + preview_token 认证；视图内必须二次校验 token 的 module/object_type/object_id 绑定 + 手册角色（角色撤销后旧令牌取文件被拒，有测试）。
- **attachment_preview_token 载荷固定 6 段冒号分隔，object_id 内不能再用冒号**；editor 令牌复合键用 `-` 连接（session_key 为纯 hex）。
- ONLYOFFICE 专用通道 `attachments/oo-editor-file/`（GET，query `token`）与 `attachments/oo-editor-callback/`（POST JSON）**不含 preview-file 段**，靠 `AUTHENTICATION_EXCLUDES` 的正则豁免中间件认证（带 `/api` 前缀与不带两种路径都要登记），由视图自校验：
  - oo-editor-file：`build_editor_token`（editor_draft 类型，object_id=`<manual>-<revision>`，TTL `ONLYOFFICE_EDITOR_TOKEN_TTL_SECONDS` 默认 1h）；修订号变化即 409，DS 须重取配置。
  - oo-editor-callback：官方 JSON 回调协议。校验链 = JWT（Authorization Bearer 优先、body.token 兜底；`hmac.compare_digest` 恒时比较、拒绝非 HS256、header/payload 段必须为 JSON 对象）→ **载荷必须含 `status`**（DS 对整个回调 body 签名，真实回调载荷必含；编辑配置 token 等非回调签名重放即 403）→ **权威回调内容（status/key/url/users）一律取自 JWT 载荷**，未签名 body 仅用于 status 冲突检测（冲突 400），不得回退读 body → `users` 数组（`uid-` 前缀剥离）归属账号 → 手册编制角色 + 活跃编辑会话 + 手册未归档 → **回调 `key` 必须等于会话 `current_doc_key`**（迟到/旧编辑实例回调 409 拒绝；同会话重取配置即轮换 key）→ 内容哈希与当前草稿一致则幂等跳过（重复回调不虚增修订号）→ `save_draft_file` 行锁下二次复核修订号 → 回调 `url` 仅允许 `ONLYOFFICE_ALLOWED_URL_HOSTS` 白名单主机（http/https，防任意 URL 取回/SSRF），大小受 `MAX_FILE_SIZE`（超限/失败路径临时文件与连接必须清理）。响应恒 `{"error": N}`（0=成功），非 0 时 DS 会重试。
- **document.key 格式 `oo-<manual_id>-f<file_id>-r<revision>-<uuid8>`**（2026-10-29 多文件改造加入文件段）：签发时写入 `ManualEditSession.current_doc_key`；它是 DS 文档缓存键也是迟到回调的比对基准，改格式须同步 `DOC_KEY_RE` 与 `parse_document_key`。editor_token object_id 为 `<manual>-<file>-<revision>`；OO 取文件/回调路由均挂在 `files/<fid>/attachments/` 下。

## 六、测试约定

- `tests/characterization/` 全部走 test client 真实请求链路；文件系统 patch 到临时目录（`patch.object(storage, 'get_institution_storage_base', ...)`）。
- ONLYOFFICE 行为测试在 `test_manual_editor.py`：JWT 攻防（篡改/换密钥/alg=none）、config 组装与 key 轮换、editor_token 绑定、回调协议全链路（本地 `ThreadingHTTPServer` 桩模拟 DS 缓存文件源，`requests` 真实下载）、越权/单写/迟到/重复/白名单。forcesave 落盘确认链路在 `test_manual_forcesave.py`（15 例：端点会话/角色校验、命令 JWT 双通道、error 0/4/1 语义、端点回退与缓存、基址推导、受理→回调落盘→修订号推进全链路、撤销先于落盘则回调拒绝）。旧 multipart 编辑服务契约（原 test_manual_publish.EditorContractTests）已随协议接入删除，勿恢复 `editor-draft|editor-callback/preview-file` 旧路由。
- 多文件行为测试在 `test_manual_multi_files.py`（文件管理/并行编辑/越权/整套发布回滚/旧接口委托）；草稿恢复优先级行为测试在 `test_manual_draft_recovery.py`（21 例：默认优先级三档/已有草稿拒绝/多版本取当前版本/部分快照明确报错/历史回退/重建确认密码会话防线/失败补偿/留痕/快照不可变）；文件历史与按文件操作记录在 `test_manual_file_history.py`；保留策略（初始来源聚合/保护边界/候选/预检只读/整套清理/部分失败重试/清理后拒绝）在 `test_manual_retention.py`（26 例，`override_settings` 注入期限/数量/缓冲期配置，时间旅行直改版本 published_at）；存量迁移验证在 `tests/test_multi_file_migration.py`（TransactionTestCase 内 `migrate institution 0002` 双向往返 + 原始 SQL 播种旧形态数据，勿改成 ORM 造数）。
- 运行：`docker exec tdyw-test sh -c "cd /data/spug/spug_api && python manage.py test apps.institution --settings=spug.settings_test_isolated --noinput"`。**不要并行跑两个测试进程**（同名隔离测试库会互相销毁，表现为大面积 error）。**测试运行期间不得修改仓库文件**（容器挂载活代码，建库阶段改文件会污染整个 run，表现为与任何代码状态都对不上的 schema 假错，重跑即消）。**全量重建 test_spug_isolated 偶发 DDL 瞬态**：极少数 run 出现 149 例级别的 `IntegrityError`（如 `Column 'deleted_by_id' cannot be null`，与任何代码状态都对不上）；单套件复跑正常即确认是库重建污染，直接重跑全量即可，不要据此改代码。
- .doc 转换测试用 RTF 内容冒充 .doc（LibreOffice 内容嗅探可转换），损坏文件走真实失败路径。
- 测试夹具建制度文件一律走 `POST files/create/`（条目+原稿+草稿一步就绪，草稿修订号从 1 起）；旧两步"originals/upload → draft/create"仅在测过渡委托语义时使用。

## 七、多文件模型不变量（2026-10-29，最重要）

1. **文件级越权防线**：`services.get_manual_file(manual, file_id)` 是所有文件级入口的第一道校验（文件必须属于 URL 中的制度）；`preview-file` 的 draft/vfile 类别以对象自身的 file/version 链反查手册。跨制度文件 ID 一律业务错误，不泄露目标存在性。
2. **单写以文件为单位**：`ManualEditSession` 绑定 (manual 冗余, file, user)；同一文件同时仅一个活跃会话，不同文件可并行（不同账号）；保存实时复核 会话+角色+该文件修订号。`start_edit_session` 行锁在 `ManualFile` 上。
3. **document.key / editor_token 全链路文件级**：key 格式 `oo-<manual_id>-f<file_id>-r<revision>-<uuid8>`（`DOC_KEY_RE` 同步），editor_token object_id=`<manual>-<file>-<revision>`，回调路由 `files/<fid>/attachments/oo-editor-callback/` 且与 key 解析出的 (manual, file) 交叉核对；AUTHENTICATION_EXCLUDES 只登记文件级四条正则，旧手册级 OO 路由已删除。迁移 0003 已把存量活跃会话整体失效并清空 current_doc_key——新旧协议不复用。
4. **整套发布三段式**（`publish_whole_set`，视图以 `non_atomic_requests` 注册）：行锁校验固化清单（≥1 文件、每文件有有效草稿、无活跃编辑会话、物理文件存在；**已有生效版本且无内容/结构变化时拒绝——口径与发布预检 `version_compare.has_pending_publish_changes` 一致，首次发布除外**）→ 事务外逐份复制快照（失败清理已复制文件）→ 行锁内复核清单/修订号未漂移后写 版本+ManualVersionFile 快照+切 current_version（落库段独立为 `_commit_publish`）；任一步失败旧生效版保持完整。`ManualVersion` 旧单文件列保留为首快照兼容镜像（两处都发布时一次写入、绝不改写）。**发布收尾（落库事务内）**：发布清单内文件 `revision_open=False`（本轮修订结束）+ 清除 `submission_revision/submitted_at/submitted_by`（提交随本版被消费）；草稿 `base_version` 指向新版本、`source_original` 置 None（解除对初始来源原稿的保留策略引用）；工作副本一律保留。**发布失败不触碰修订状态、草稿与旧生效版本**。
5. **整套回退**（`rollback_to_version`）：按版本快照清单重建待发布集合——属于该版本的文件以快照重建草稿（base_version=该版本、被移除的重新纳入），不属于的启用文件退出待发布集合；先失效手册全部活跃会话；不覆盖历史版本，重发产生更大版本号。
6. **文件条目永不物理删除**：`ManualFile.is_removed` 软移除（退出待发布集合，原稿/历史快照/ID 保留，回退可重新纳入）；最后一份启用文件不可移除；有活跃会话的文件不可移除。`ManualVersionFile.manual_file` PROTECT。
7. **过渡期旧单文件接口**（`manuals/<pk>/draft|originals/...`、`versions/<vid>/download|preview-url`）：委托唯一启用文件/唯一快照；零个或多个一律明确报错（'该制度包含多份文件，请使用文件级接口…'），绝不默默操作第一份。文件管理视图在 `views_files.py`（门禁行数拆分），共享助手 `_file_from_request/_can_view_workspace/_session_payload` 从该模块导入（单向依赖 views_draft → views_files，勿反向）。
8. **显示名归属**：发布快照显示名取 `ManualFile.display_name`（创建时来自上传名，rename 接口可改），与草稿 `original_name`（回调会写成系统名）彻底分离——草稿脏名不影响版本清单；迁移 0003 存量主文件名按 草稿名>最新版本名>最早原稿名>手册名.docx 派生（系统前缀治愈），带历史存储后缀的名字需人工经 rename 接口清理。
9. 操作记录涉及具体文件的动作必须带 `file=` 外键 + detail JSON `file_id`/`file_revision`/`file_name`；`log_operation(manual, user, action, version=None, file=None, **detail)`。
10. **版本变更状态与发布预检（2026-10-29）**：`version_compare.py` 是变更状态的唯一计算点，全部字段服务端按相邻版本快照 SHA256 比较，前端不得以文件名推断——`compute_version_changes` 产出 change_type（added/modified/unchanged）与 `latest_changed_version_no/latest_changed_at`（截至该版本逐版回溯，首版即视为变化），本版本移除的文件不进 items、单独出 `removed_items`（附 `previous_version_id/previous_snapshot_id`，可据此预览/下载上一版快照，绝不静默隐藏）；`GET /manuals/<pk>/versions/<vid>/files/` 响应含 `version_id/previous_version_no/items/removed_items`，items 行内嵌 computed 字段（`to_version_dict` 内嵌 files 快照不含这些字段，完整状态以该端点为准）。`GET /manuals/<pk>/publish-preview/`（view 权限 + `can_publish`，归档拒绝）返回发布计划分组 `changed/unchanged/added/removed/blocked`（草稿哈希 vs 生效版快照哈希；blocked=无草稿/草稿文件缺失/活跃编辑会话，含 reason 与 message）；**预检不是放行凭证**，发布权威校验仍在 `publish_whole_set` 行锁内复核。
11. **草稿恢复严格优先级（2026-10-29，最重要）**：`FileDraftCreateView`（文件级 `draft/create/`）默认路径（不传 original_id）按固定优先级执行——①已有草稿（有 file_path）一律拒绝（'当前文件已有草稿，请继续编辑或明确执行重建'），绝不无提示覆盖；②无草稿但有 `manual.current_version` → `services.restore_draft_from_current_version` 从该版本中此文件的 `ManualVersionFile` 快照恢复（base_version=来源版本、source_original 不记录、恢复前失效该文件会话、修订号新起；**当前版本不含该文件快照（后加入文件）时明确报错，绝不静默改用原稿补齐**；服务在行锁内复核并发已建草稿即放弃）；③无草稿且 `has_published_versions` 为假（从未发布过任何版本）→ 才从该文件最近原稿创建。已废止（有历史版本、无生效版本）同样拒绝默认回原稿。**原稿重建（original_id）是明确的高级操作**：发布过版本（含废止）必须 `confirm=true` 二次确认；丢弃现有草稿且配置了编辑密码时必须先过 `verify_manual_password`；该文件有活跃编辑会话一律拒绝；重建成功后 base_version 清除（来源由 source_original 表达），操作日志（`create_draft`）必含 `rebuild_from_original/source_original_id/previous_revision/current_version_no`。**草稿缺失的可恢复状态**：`_draft_or_error` 失败分支返回顶层 `{error, draft_recovery}` 的 HTTP 200 响应（detail/session/save/download/preview/editor-config 六入口共用，调用方直接 `return err`，不得再包 json_response）；files 清单行对无草稿文件下发 `draft_recovery`（`build_draft_recovery_hint`：current_version/original(+requires_confirm)），前端恢复入口以它渲染。恢复/重建全程"文件先行、失败补偿"——复制失败不动库、落库失败清理已复制文件；业务流程绝不改写删除历史快照与原稿（行为钉死在 `tests/characterization/test_manual_draft_recovery.py` 21 例；物理删除仅限第九节保留策略入口）。
12. **文件变更记录数据源（2026-10-29 详情页信息层级改造）**：`GET manuals/<pk>/files/<fid>/version-history/`（@auth view + `can_view_published`，跨制度文件 ID 拒绝）由 `version_compare.compute_file_version_history` 计算——每行一次"包含该文件的发布"，change_type 与相邻上一发布版本同文件快照哈希比较（上一版不含=added，覆盖移除后重新纳入；未参与的版本不出现，不是伪装成一行），**行内 `is_cleaned` 标记该次快照物理文件是否已按保留策略清理**（清理后前端必须关闭预览/下载，后端同样拒绝）；`GET manuals/<pk>/operation-logs/?file_id=` 支持按文件过滤操作记录（非法值明确报错，不过滤=原全量口径）。详情页信息层级（文件清单默认页签/文件变更记录/初始来源）的页签可见性口径见前端 AGENTS.md；测试钉死在 `tests/characterization/test_manual_file_history.py` 与 `test_work_status.py`（已移除文件经 originals-overview 全集仍可选、清理快照带 is_cleaned）。
13. **初始来源聚合与"更换来源"（2026-10-29）**：`GET manuals/<pk>/originals-overview/`（@auth view + `can_view_manual`）一次返回全部制度文件行（含已移除条目）——`first_original`=该文件最早一条原稿（永不因清理改变归属，已清理仍带元数据 `is_cleaned/cleaned_at`）、`history` 完整原稿历史（新→旧）、`first_published_version_no/at`（原稿保护边界展示）、`has_usable_original`；草稿来源信息仅对 `_can_view_workspace` 通过者下发（与 files/ 清单口径一致）。"为已有文件更换来源"=`POST files/<fid>/originals/upload/`（目标文件在 URL 中明确，只追加原稿记录，绝不改动当前草稿），与"新增制度文件"（`files/create`，每个上传文件各建一份条目）语义严格分开，前端入口亦分开。
14. **草稿状态总览（2026-10-29）**：`GET manuals/<pk>/draft-status/`（@auth view + `_can_view_workspace`：编制/发布角色或管理权限；仅查看角色一律拒绝，不得经它泄漏草稿信息）是"草稿工作区逐份状态 + 详情页整套摘要"的唯一数据源，计算唯一实现 `version_compare.build_draft_status`——内容关系一律按 草稿哈希 vs 当前生效版快照哈希 比较（unchanged/modified/added/awaiting_first_publish，发布后保留的草稿自动归 unchanged），前端不得以修订号或文件名推断；整套待发布变化包含 结构性三项：`removed_items`（生效版存在、已移除）/ 行内 `renamed`+`current_name`（名称与生效快照不同）/ `summary.reordered`（双方共有文件相对次序）。异常状态：`no_draft` 行附 `draft_recovery`；编辑会话占用（含未完成同步/保存回调）与草稿物理文件缺失 = `unconfirmed`（附 reason/message/session.is_mine），**绝不冒充无变化**；`summary.consistent` 仅在 可确认+无缺草稿+无任何待发布变化 时为真。与 publish-preview 的分工：编制者查状态用 draft-status（publish-preview 是 can_publish 域的发布预检，编制者调用必然被拒）；两者都不是放行凭证，发布权威校验仍在 `publish_whole_set` 行锁内。刷新契约：详情进入/文件清单页签挂载/发布/回退/废止 后重新拉取，禁止固定周期轮询。测试钉死在 `tests/characterization/test_draft_status.py`（16 例：首发/发布后一致/再发布/修改/同内容重存/新增/移除/改名/排序/结构变化发布后复位/缺草稿/会话占用/文件缺失/占用优先/编制与发布可读/仅查看拒绝）。
15. **制度列表工作状态（2026-10-29 交互优化，2026-10-30 增补 revising）**：`GET /manuals/` 行内新增 `work_status`（`serializers.to_manual_list_item` 第 4 参下发，缺省 None）——唯一计算实现 `version_compare.build_manuals_work_status`（批量预取 快照/文件/草稿/会话 各一次查询），与 `build_draft_status` **共享同一套比较口径与 summary 字段**（一致性由 test_work_status 钉死，改状态语义必须两处同步验证）。status 枚举：synced=已生效无未发布修改 / awaiting_first_publish=待首次发布 / pending_changes=有待发布变化（含 移除/改名/排序 结构项）/ **revising=修订进行中（无待发布变化但修订轮开启；pending_changes 优先于它）** / editing=编辑中（会话占用，含未完成同步，优先于其他不可确认原因）/ missing_draft=缺少草稿 / unverifiable=状态无法确认（草稿文件缺失等非会话原因）/ no_files=未上传文件；判定优先级 no_files > editing > unverifiable > missing_draft > awaiting_first_publish > pending_changes > revising > synced。**可见性逐手册判定**：管理权限或持该手册编制/发布角色（角色 id 从 prefetch 缓存对象就地取值，不得用 Role 对象集合与 id 集合求交）；仅查看角色行内恒为 None，不得经列表泄漏草稿信息。列表接口响应中行内旧 `draft`（首文件草稿摘要）仅对管理者保留，**不得作为任何状态展示依据**。测试钉死在 `tests/characterization/test_work_status.py`（18 例：八态判定/与 draft-status 摘要一致/编制发布可读/仅查看不下发/已移除文件仍可发现/清理快照 is_cleaned）。

## 七·之补、修订状态与开始修订（2026-10-30，迁移 0006，最重要）

1. **修订进行中是显式持久状态**：`ManualFile.revision_open`（默认 True）。**绝不凭"草稿哈希 == 生效快照哈希"推断修订已结束**——哈希口径只回答"有无待发布变化"，修订轮由本字段回答。四个概念严格区分：初始来源（ManualOriginal）/ 持续保留的草稿工作副本（ManualDraft，发布后保留）/ 进行中的修订（revision_open）/ 不可变发布快照（ManualVersion*）。
2. **状态机（唯一写点）**：开启=新文件创建默认 True；`revision_services.start_file_revision`（真实状态动作）；任何草稿内容变更（保存/恢复/回退/原稿重建）经 `services._create_draft_record` 单字段 update 置回 True（工作副本健康时"开始修订"原样复用现有工作副本，不复制新快照）；废止当前版本后全部启用文件置 True（生效集合已不存在）。**关闭=仅整套发布成功**（`_commit_publish` 对发布清单内文件批量置 False）；发布失败（预检拒绝/快照制作失败/落库复核失败）不触碰。移除文件与整套回退会把退出文件的休眠草稿 `base_version/source_original` 置空（休眠草稿不保护历史文件；回退按快照整体重建，不依赖休眠草稿）。
3. **开始修订端点**：`POST manuals/<pk>/files/<fid>/revision/start/`（@auth draft_edit + `can_edit_draft`，手册须启用；发布者不需要也不应该开启修订）。幂等：修订已开启返回 `resumed=true`；工作副本健康返回 `started=true`；工作副本缺失/损坏/与当前生效基线不一致返回 **HTTP 200 + `needs_repair=true`**（reason=draft_missing/draft_corrupt/baseline_mismatch、message、draft_recovery），调用方明确提示后携带 `confirm_repair=true` 重试，经 `services.restore_draft_from_current_version(force_repair=True)` 从当前生效版本快照修复——**绝不静默改用初始来源，绝不静默覆盖可能与基线不同的工作副本**；修复会失效该文件编辑会话并推进修订号（草稿行被删过时修订号从 1 重起）。视图在 `views_files.py`（门控行数拆分），服务在 `revision_services.py`（单向依赖 services，勿反向）。
4. **无意义发布拒绝**：`_commit_publish` 前置 `version_compare.has_pending_publish_changes`（发布端与预检端同口径）：已有生效版本且 内容哈希全同+无新增/移除/改名/排序 时拒绝（'当前没有内容或结构变化，无需重复发布'）；修订开启但内容未变不是发布理由；首次发布（无生效版本，含废止后再发布）不受限。
5. **draft-status / work_status 增量**：逐份行新增 `revision_open`；summary 新增 `revising`（修订进行中计数）且 `consistent`（已生效、无未发布修改）要求 `revising==0`——修订开启但内容未变既不是一致也不计入待发布变化。publish-preview 行新增 `renamed/current_name`，顶层新增 `reordered/renamed/first_publish/has_changes`，`can_publish = 无受阻 且（首发或 has_changes）`。
6. **存量迁移 0006（保守回填）**：AddField default=True 全量置"进行中"，RunPython 仅对「当前生效版本快照中存在 + 草稿有效且哈希一致 + 无活跃编辑会话」的文件翻转为 False（迁移模块函数 `_backfill_revision_open`，测试用真实 apps 直接调用验证）；其余一律保持进行中，不丢失可能尚未发布的修改或编辑会话。回滚=RemoveField（值可由发布动作重建）。
7. 行为测试：`tests/characterization/test_revision_state.py`（发布结束修订/失败保持原状/无变化拒发/开始修订复用/幂等/三种修复路径/修复不碰初始来源/修复失效会话/权限/废止重开/批量分工原子性/改派清空重置提交/发布消费提交/回填规则）。

## 七·补、文件分工与提交编制（2026-10-29，迁移 0005）

1. **分工单位=整份制度文件**：负责人（owner/owner_name）、分工说明（assign_note）、最近分工（assigned_at/assigned_by）与提交编制（submission_revision/submitted_at/submitted_by）都在 `ManualFile` 条目上——每份文件至多一名负责人，**结构上不存在同一文件多条互相冲突的"当前分工"**；owner 为空即"未分配"。owner_name/submitted_by_name 等账号名快照在账号删除后仍可读（SET_NULL + 落库快照，序列化优先快照、回退关联账号昵称）。
2. **接口**：`files/create/` 接受可选 multipart `owner_id`/`note`（新增时即可指定）；`POST files/<fid>/assignment/` 指定/改派/清空（owner_id 必须显式携带，null=清空；note ≤500 字）；**`POST files/batch-assignment/`（2026-10-30）批量分工**（file_ids 非空整数列表 + owner_id 显式携带 + note；`_validate_batch_assignment` 逐文件校验归属，任一文件不属于该制度整批拒绝，事务内全成功或全失败；逐文件 `assign_file_owner(batch=True)` 写 file_assign 操作记录 + 单条模块审计事件）；`POST files/<fid>/submit/` 提交编制。前两者权限=`@auth draft_edit` +（管理权限或手册编制角色），`assignment` 与 `rename/move/remove` 同口径；`submit` 页面权限=view（负责人可能仅持查看权限），业务放行=**文件负责人 或 管理权限 或 手册编制角色**（沿用旧章节进度的负责人放行口径——提交是状态交接而非编辑操作）。所有入口先经 `_file_from_request` 校验文件归属，跨制度文件 ID 一律拒绝。
   - **负责人候选接口（2026-10-30，最重要）**：`GET manuals/<pk>/assignment-owners/`（`AssignmentOwnerOptionsView`）是分工弹窗与新增文件负责人下拉的**唯一候选来源**——`@auth draft_edit|upload`（与两条携带 owner 的写路径对齐）+（管理权限或手册编制角色）；候选=全部启用账号（`is_active=True`，与 `_resolve_owner` 的"有效账号"口径一致；本模块授权按账号角色判定、tenant_id 不参与归属，**跨租户账号可作负责人是预期行为**，测试钉死）；只回传 `id+name`（昵称，空则账号名）最小字段。**禁止改回拉账号管理列表 `/api/account/user/`**（GET 要求 `system.account.view`，无账号查看权的分工用户打开弹窗即"权限拒绝"且候选被吞成空列表——本接口为修复该缺陷而设），也不得以放宽账号接口权限为替代方案。
3. **指定负责人不授予任何权限**：编辑仍要求 模块权限+手册编制角色+密码会话；`assignment.is_mine` 只是责任标记（`_assignment_payload` 按请求者计算），不得据此放行任何写操作。
4. **提交编制的限制**（`services.submit_file_compilation`）：手册未归档；该文件有有效草稿（记录存在、`resolve_absolute_path` 合法、物理文件存在）；无活跃编辑会话。可重复提交（以提交时最新修订号覆盖）。记录 `submission_revision`+`submitted_at`+`submitted_by`，操作记录 action=`file_submit`（file 外键+detail JSON）。
5. **提交状态为计算式失效（最重要）**：`services.file_submission_state` 是唯一判定实现——`submission_revision == 当前草稿 revision` 且草稿有效 = submitted；否则 stale（"提交已失效"，绝不显示"已完成"）。草稿所有变更路径（multipart 保存、ONLYOFFICE 回调保存、原稿重建、版本回退、恢复）都经 `_create_draft_record` 推进 revision，提交状态随之自动失效，**不依赖任何写路径清除提交**；新增会改草稿修订号的路径必须保持经 `_create_draft_record`。**显式清除（2026-10-30，回到"未提交"而非 stale）**：① `assign_file_owner` 在 owner 变化（改派/清空；负责人未变仅改说明不清）时清除提交记录——旧负责人的交接随负责人变更失效；② 整套发布成功时对发布清单内文件清除——提交随本版被消费，绝不误显示为下一轮的待交接。历史交接保留在操作记录（file_assign detail 带 submission_reset，file_submit 记录不动）。
6. **下发口径**：`files/` 清单行对所有可见者带 `assignment`（负责人是责任信息，含 is_mine）；`submission` 属草稿域信息，仅对 `_can_view_workspace` 通过者下发（与 draft/active_session 同口径），序列化在 `to_manual_file_dict` 按传参附加。
7. **发布核对只增信息、不加阻断**：`build_publish_plan` 各分组行（除 removed=生效快照行构造，无文件条目）携带 `owner_name` 与 `submission`（`_plan_row_base`），供发布者在确认窗口核对交接状态；`can_publish` 与 `publish_whole_set` 的整套发布校验保持不变（第一阶段无任何新阻断）。
8. **旧章节分工（ManualChapter）遗留只读**：表与记录一律不动（旧记录只关联制度、无法按章节名称猜测所属文件，人工核对完成前不删不改）；`GET manuals/<pk>/chapters/` 继续开放供过渡展示；`chapters/create|<cid>|<cid>/progress/` 全部写接口返回 `LEGACY_CHAPTER_READONLY_ERROR`（urls 保留，路由不删以免 404 语义含混）。前端过渡展示在文件清单页签底部（ChaptersTab 组件已删除）。
9. 行为测试：`tests/characterization/test_manual_file_assignment.py`（分工/改派/未分配/越权/提交/失效三路径/发布预检携带/多文件并行/旧章节保留；`AssignmentOwnerOptionsTests` 钉死候选接口的权限匹配/最小字段/跨租户口径/停用账号排除，并固化根因=账号管理清单仍按 system.account.view 拒绝）；`test_manual_chapters.py` 已改写为遗留只读语义。


## 八、发布版本快照与旧接口清理状态（2026-10-29 保留策略配套）

- `ManualVersionFile.cleaned_at` 标记单份快照物理文件已按保留策略清理；`ManualVersion.files_cleaned_at`（任一快照清理即置位=整版不可完整使用）/`files_clean_status`（''/partial/cleaned）/`files_clean_error`（失败说明，可重试）。版本号、发布人/时间、变更说明与快照行（含哈希）在清理后永久保留。
- 清理后防线（后端独立校验，前端同时关闭入口）：`rollback_to_version` 对 `files_cleaned_at` 非空的版本直接拒绝；快照/旧单文件版本的下载与预览对已清理快照拒绝（'该文件已按保留策略清理…'）；preview-file 通道对已清理的 original/version/vfile 同样拒绝；已清理原稿的下载/预览/重建拒绝（`storage.ORIGINAL_CLEANED_ERROR`）。
- `serializers.to_version_dict/to_version_file_dict/to_original_dict` 已带清理状态字段；新增涉及版本/原稿/快照的接口时不得把已清理对象当作可用文件返回。

## 九、文件生命周期保留策略（2026-10-29，唯一物理删除入口）

- **自动清理不启用**：无定时任务、无 Celery beat 项。物理删除只能经 `retention_services.execute_cleanup`（`POST cleanup/execute/`）；`INSTITUTION_VERSION_RETENTION_DAYS<=0`（默认）时预检不产出候选、执行直接业务错误拒绝。三个配置全部在 `spug/settings.py`（`INSTITUTION_VERSION_RETENTION_DAYS`/`INSTITUTION_VERSION_RECENT_KEEP_COUNT`/`INSTITUTION_ORIGINAL_CLEAN_BUFFER_DAYS`，环境变量注入）。
- **原稿保护边界**：该文件"首次进入成功发布的版本"（`get_first_published_version` 按 ManualVersionFile 快照回溯）之前原稿本体永久受保护；首次发布并超过缓冲期后才可成为候选。候选另需同时通过：草稿来源引用（`ManualDraft.source_original` 仍指向该原稿时阻止——注意编辑器保存/恢复/回退会清空该字段，**2026-10-30 起整套发布成功同样解除该引用**（修订轮结束、基线改为生效版本，来源历史由原稿记录与操作日志承载），原稿重建会重新建立）、活跃编辑会话、共享路径引用（`count_other_path_references` 跨 原稿/草稿/版本镜像列/版本快照 四表核对，删除前排除自身）。
- **版本保护集合**：当前生效版本永久受保护；`long_term_protected` 标记（`versions/<vid>/protect/`，@auth publish + can_publish，发布域操作不走管理权限码）排除；最近 N 个版本（按 version_no）排除；发布时间未超期限排除；`ManualDraft.base_version` 仍引用（业务引用）排除。`is_effective=False` 绝不参与候选判定。
- **整套语义与幂等**：候选按整版评估、逐快照删除并逐份记录成功/失败；任一失败整版标 partial（`files_clean_error` 记录、快照行不动、可重试），全部成功才置 cleaned；已清理项二次执行跳过（幂等）。删除与落库之间不包显式长事务（单条更新自原子），由候选评估+共享引用核对+下游存在性检查兜底。预检（`build_cleanup_preview`）完全只读且不是执行凭证。
- 长阻塞文件 IO 不得包进 ATOMIC_REQUESTS：`cleanup/execute/` 若将来改造成批量大删除，参照 `publish/` 用 `transaction.non_atomic_requests` 注册。
