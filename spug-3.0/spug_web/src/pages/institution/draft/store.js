/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台 store（多文件模式，2026-10-29）：
 * - 待发布文件清单（GET files/，后端按 sort_order 升序返回）为工作区数据源，
 *   每个条目自带 draft（草稿信息）与 active_session（编辑占用）。
 * - 编辑会话按 (manualId, fileId) 存 sessionStorage（键
 *   institution_edit_session_<manualId>_<fileId>），跨页签恢复、离开页面
 *   不清除，退出会话必须走显式按钮（服务端 revoke）。
 * - 编辑配置按文件缓存：编辑中禁止重复 fetchEditorConfig（重新取配置会
 *   轮换 document key，使当前编辑器实例的保存回调失效）；clearSession
 *   时清除该文件缓存，新会话（切换文件/重新开启）允许重新取。
 * - 旧单文件接口（/draft、/draft/session 等）多文件制度返回 error，
 *   本 store 一律使用文件级接口。
 * - 保存确认（2026-10-30）：ONLYOFFICE 的"所有更改已保存"只代表文档
 *   服务自身缓存，不代表制度草稿落盘；本 store 以"forcesave 受理 →
 *   轮询草稿修订号推进 → 再次 forcesave 复核到 no_changes"为唯一确认
 *   链路（_confirmForcesave），"保存并结束编辑"（finishEditing）与
 *   离开保护（confirmFileSave：切换文件/返回详情，确认成功但不撤销
 *   会话）共用；editorDirty 闩锁 + saveConfirmed 驱动工作台独立的
 *   "制度草稿保存状态"展示，未确认落盘绝不显示"已保存"。
 * - no_changes 沉降复核（2026-10-31 竞态修复）：DS 对 forcesave 的
 *   no_changes 应答只反映命令处理瞬间的缓冲状态，与命令几乎同拍敲入的
 *   修改可能经事件通道晚于命令注册（dev 实测保存丢失：DS 误答
 *   no_changes → 前端轮换 key 销毁编辑器 → 在途修改随收尾回调被
 *   409 丢弃）。因此 no_changes 不即时采信：编辑器实时脏态
 *   （editorLiveState，onDocumentStateChange 的原始上报，不受
 *   markSaveConfirmed 清除影响）已报脏即判在途；短沉降窗后再次
 *   forcesave 复核，仍 no_changes 且编辑器不报脏才确认；
 *   switchEditMode 在确认返回与轮换之间编辑器翻脏则重走一次确认。
 * - 本机编辑（2026-10-31 恢复/完善）：编辑方式按文件切换
 *   （switchEditMode：在线 ⇄ 本机）。用户主动切到本机前必须先经落盘
 *   确认链路，再以重取编辑配置轮换 document key，让旧编辑实例的回调
 *   在服务端失效（会话保留供本机上传使用）；下载草稿成功时记录基线
 *   修订号（localBaselines），上传保存必须携带该基线（uploadLocalDraft，
 *   绝不改用上传前刷新得到的较新修订号），服务端草稿已推进时后端拒绝
 *   覆盖。服务未配置/配置加载失败/编辑器加载失败的文件恒为本机方式，
 *   本机入口不依赖任何失败上报的可靠性。
 */
import { observable, action, computed } from 'mobx';
import { http } from 'libs';

const SESSION_STORAGE_KEY_PREFIX = 'institution_edit_session_';

class DraftStore {
  fetchSeq = 0;
  @observable id = null;
  @observable manual = null;
  // 待发布文件条目数组（{id, name, sort_order, draft, active_session, ...}）
  @observable files = [];
  @observable selectedFileId = null;
  @observable isFetching = false;
  @observable error = '';
  // 每文件本地会话：{ [fileId]: {sessionKey, expiresAt} }
  @observable sessions = {};
  // 每文件编辑配置缓存：{ [fileId]: editor-config 响应 }
  @observable editorConfigs = {};
  // 每文件编辑配置加载失败信息（会话类失败不记，走清会话逻辑）
  @observable editorErrors = {};
  // 正在加载编辑配置的文件 id（同时只指示一个文件，仅用于局部 Spin）
  @observable editorLoadingId = null;
  @observable verifying = false;
  // 密码门验证失败原因（拦截器已弹错，此处仅用于门内 Alert 常驻展示）
  @observable verifyError = '';
  @observable saving = false;
  // 本次访问已通过验证的编辑密码（仅内存，不落 sessionStorage）；
  // 工作区内「开始编辑此文件」用它开启会话，密码失效时清空回密码门。
  @observable verifiedPassword = '';
  // 是否已通过密码门（本次访问）。本地恢复了任一文件会话时同样放行。
  @observable passwordVerified = false;
  // ?file= 深链指定的文件 id：密码验证只针对它建立会话，
  // 目标不存在/无草稿时不回退到其他文件（deeplinkNotice 说明原因）
  @observable requestedFileId = null;
  @observable deeplinkNotice = '';
  // 「保存并结束编辑」进行中的文件 id 与失败后的可重试状态说明。
  // 失败时保留会话与编辑器，仅置 finishingError 供该文件界面呈现重试入口；
  // finishingErrorFileId 标记错误归属文件，切换文件不串显。
  // 离开保护（切换文件/返回详情）复用同一状态：确认期间禁用冲突导航。
  @observable finishingFileId = null;
  @observable finishingErrorFileId = null;
  @observable finishingError = '';
  // 在线编辑器"有未确认修改"闩锁（{ [fileId]: true }）：OnlyOfficeEditor
  // onDocumentStateChange(true) 置位；false 事件不清除——DS 的"所有更改
  // 已保存"只代表文档服务自身缓存，服务端确认落盘成功才清除（markSaveConfirmed）。
  @observable editorDirty = {};
  // 编辑器实时脏态（{ [fileId]: true|false }）：onDocumentStateChange 的
  // 原始上报，true/false 都记录。与 editorDirty 闩锁并行、语义不同：
  // 闩锁只在服务端确认落盘成功（markSaveConfirmed）时清除，而确认成功
  // 判定本身需要知道"此刻编辑器是否仍报未保存修改"——DS 的 no_changes
  // 应答只反映命令处理瞬间，修改可能晚于命令注册（dev 实测 2026-10-31
  // 保存丢失），实时脏态不受 markSaveConfirmed 清除影响，是确认链
  // 沉降复核与 switchEditMode 轮换闸门的判据。编辑器实例就绪复位为
  // false（markEditorReady），随会话/页面复位清除。
  @observable editorLiveState = {};
  // 服务端确认落盘记录（{ [fileId]: {revision, at, by} }）：只有 forcesave
  // 确认链路成功后写入，供保存状态显示"已保存到制度草稿：rN、时间"。
  @observable saveConfirmed = {};
  // 每文件编辑方式（'online' | 'local'，缺省 'online'）：仅当在线编辑
  // 配置可用时生效，服务未配置/配置加载失败/编辑器加载失败一律回落本机
  @observable editModes = {};
  // 在线编辑能力标记（{ [fileId]: true }）：editor-config 返回可用时置位。
  // 切到本机时配置缓存被清除（旧配置不得被再次渲染使用），能力标记保留，
  // 供本机面板继续提供「切回在线编辑」入口
  @observable onlineAvailable = {};
  // 编辑器脚本/文档加载失败标记（{ [fileId]: true }，OnlyOfficeEditor
  // 上报，编辑器就绪或重新取配置后清除）：工作台据此提供切换到本机的
  // 显式入口；即使该上报不可靠，编辑方式切换控件也独立于它始终渲染
  @observable editorLoadFailed = {};
  // 本机编辑基线修订号（{ [fileId]: revision }）：下载草稿成功时记录，
  // 上传保存必须携带该基线（绝不改用上传前刷新得到的较新修订号）；
  // 上传成功（基线已消费）或服务端草稿已推进（基线过期）后清除
  @observable localBaselines = {};
  // 保存确认失败后的重试语义（''=重试保存并结束编辑 | 'switch_local'
  // =重试切换到本机 | 'download_draft'=重试下载草稿），驱动工作台重试
  // 按钮的文案与分发
  @observable finishingErrorKind = '';
  // 落盘确认轮询参数（生产默认 2s×15 次≈30s；测试可调小加速）
  pollIntervalMs = 2000;
  pollMaxAttempts = 15;
  // 落盘确认的 forcesave 复核轮数上限：每轮"受理→轮询修订号推进→再次
  // forcesave 复核"，只有 DS 报告 no_changes 才认定完成（见 _confirmForcesave）
  confirmMaxRounds = 3;
  // no_changes 沉降复核窗口（生产默认 1.2s）：给与 forcesave 命令几乎
  // 同拍敲入的修改留出"经事件通道注册 + documentState 事件到达"的时间，
  // 之后再次 forcesave 复核（一次性沉降复核，不属于固定周期轮询）；
  // 测试可调小（见 _settleNoChanges）
  confirmSettleMs = 1200;
  // finish 序号：reset/新一次 finish/confirm 使旧的轮询与收尾失效
  finishSeq = 0;

  /** 当前选中文件条目（未选中或已被移除时为 null） */
  @computed get selectedFile() {
    return this.files.find(f => f.id === this.selectedFileId) || null;
  }

  /** 是否持有任一文件的本地会话（未保存拦截以"任一有效会话"为准） */
  @computed get hasAnySession() {
    return this.files.some(f => !!this.sessionKeyOf(f.id));
  }

  // ---------------------------------------------------------------------------
  // 会话（按文件）：sessionStorage 键 institution_edit_session_<manualId>_<fileId>

  sessionKeyOf(fileId) {
    const session = this.sessions[fileId];
    return (session && session.sessionKey) || '';
  }

  sessionExpiresOf(fileId) {
    const session = this.sessions[fileId];
    return session ? session.expiresAt : null;
  }

  /**
   * 按当前文件清单恢复本地会话：只恢复清单内文件，顺带清理孤儿键
   * （含旧单文件模式的无后缀键），避免跨手册/已移除文件残留。
   * 仅在 files 拉取成功后调用。
   */
  @action.bound
  loadSessions() {
    const basePrefix = `${SESSION_STORAGE_KEY_PREFIX}${this.id}`;
    const validIds = new Set(this.files.map(f => String(f.id)));
    const staleKeys = [];
    if (sessionStorage.getItem(basePrefix)) staleKeys.push(basePrefix);
    for (let i = 0; i < sessionStorage.length; i++) {
      const key = sessionStorage.key(i);
      if (!key || !key.startsWith(`${basePrefix}_`)) continue;
      const fileId = key.slice(basePrefix.length + 1);
      if (!validIds.has(fileId)) {
        staleKeys.push(key);
        continue;
      }
      try {
        const data = JSON.parse(sessionStorage.getItem(key));
        if (data && data.sessionKey && data.expiresAt &&
            new Date(data.expiresAt).getTime() > Date.now()) {
          this.sessions[Number(fileId)] = {
            sessionKey: data.sessionKey, expiresAt: data.expiresAt};
        } else {
          staleKeys.push(key);
        }
      } catch (e) {
        staleKeys.push(key); /* 忽略本地会话缓存损坏 */
      }
    }
    staleKeys.forEach(key => sessionStorage.removeItem(key));
  }

  @action.bound
  saveSession(fileId, sessionKey, expiresAt) {
    this.sessions[fileId] = {sessionKey, expiresAt};
    sessionStorage.setItem(`${SESSION_STORAGE_KEY_PREFIX}${this.id}_${fileId}`,
      JSON.stringify({sessionKey, expiresAt}));
  }

  /** 清除单个文件的本地会话与编辑配置缓存（该文件回到验证态） */
  @action.bound
  clearSession(fileId) {
    delete this.sessions[fileId];
    delete this.editorConfigs[fileId];
    delete this.editorErrors[fileId];
    delete this.editorDirty[fileId];
    delete this.editorLiveState[fileId];
    delete this.saveConfirmed[fileId];
    // 编辑方式与本机编辑状态随会话一并复位（重开会话后回到缺省在线）
    delete this.editModes[fileId];
    delete this.onlineAvailable[fileId];
    delete this.editorLoadFailed[fileId];
    delete this.localBaselines[fileId];
    if (this.editorLoadingId === fileId) this.editorLoadingId = null;
    if (this.finishingErrorFileId === fileId) {
      this.finishingErrorFileId = null;
      this.finishingError = '';
      this.finishingErrorKind = '';
    }
    sessionStorage.removeItem(`${SESSION_STORAGE_KEY_PREFIX}${this.id}_${fileId}`);
  }

  /**
   * 在线编辑器修改状态上报（闩锁语义）：仅 true 置位；false 事件
   * （DS 自身"所有更改已保存"，只代表文档服务缓存）不清除——清除只能
   * 发生在服务端确认落盘成功（markSaveConfirmed）或会话/页面复位时。
   */
  @action.bound
  setEditorDirty(fileId, dirty) {
    // 实时脏态忠实记录 DS 的原始上报（true/false 都写）；闩锁仍只由
    // true 置位、服务端确认落盘成功或会话/页面复位清除——两份状态
    // 语义不同，确认链沉降复核与轮换闸门只读实时脏态（不受
    // markSaveConfirmed 清除影响），UI 保存状态展示只读闩锁。
    this.editorLiveState[fileId] = !!dirty;
    if (dirty) this.editorDirty[fileId] = true;
  }

  /** 编辑器实例就绪：新实例尚无未保存修改，实时脏态复位（旧实例残留） */
  @action.bound
  markEditorReady(fileId) {
    this.editorLiveState[fileId] = false;
  }

  /** 服务端确认落盘成功：记录确认结果并清除该文件的未确认修改闩锁 */
  @action.bound
  markSaveConfirmed(fileId, draftData) {
    this.saveConfirmed[fileId] = {
      revision: draftData && draftData.revision != null ? draftData.revision : null,
      at: draftData ? draftData.last_saved_at : null,
      by: draftData ? draftData.last_saved_by_name : null,
    };
    this.editorDirty[fileId] = false;
  }

  // ---------------------------------------------------------------------------
  // 编辑方式切换（在线 ONLYOFFICE ⇄ 本机下载-编辑-上传）

  /**
   * 当前生效编辑方式：在线编辑配置可用时取 editModes（缺省在线），否则
   * 恒为本机——服务未配置、配置加载失败（含会话类失败清会话后）都回落
   * 本机，本机入口不依赖任何失败上报的可靠性。
   */
  effectiveEditMode(fileId) {
    const config = this.editorConfigs[fileId];
    if (config && config.editor_available) {
      return this.editModes[fileId] || 'online';
    }
    return 'local';
  }

  /** 编辑器脚本/文档加载失败上报（闩锁；编辑器就绪或重新取配置后清除） */
  @action.bound
  markEditorLoadFailed(fileId) {
    this.editorLoadFailed[fileId] = true;
  }

  @action.bound
  clearEditorLoadFailed(fileId) {
    delete this.editorLoadFailed[fileId];
  }

  /** 下载草稿成功：记录该文件草稿修订号作为本次本机编辑的基线 */
  @action.bound
  recordLocalBaseline(fileId, revision) {
    if (revision == null) return;
    this.localBaselines[fileId] = revision;
  }

  /**
   * 服务端轮换 document key（切到本机编辑前使旧编辑实例的回调失效）：
   * 重取编辑配置即轮换会话 current_doc_key，旧 key 的迟到回调因 key 不符
   * 被后端 409 拒绝——这是服务端认可的失效方式，不依赖隐藏 iframe 或
   * 前端模式状态。返回的配置不缓存、不用于渲染（本机编辑不需要）。
   * 请求失败向上抛出：旧 key 仍有效时绝不允许切走，否则旧编辑实例的
   * 迟到回调会覆盖本机上传的草稿。
   */
  async rotateEditorKey(fileId) {
    const sessionKey = this.sessionKeyOf(fileId);
    if (!sessionKey) throw new Error('缺少编辑会话');
    await http.get(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/editor-config/` +
      `?session_key=${sessionKey}`);
  }

  /**
   * 切换指定文件的编辑方式（'online' | 'local'）。返回 {ok, reason}，
   * 失败语境写入 finishingError（工作台呈现重试入口），不抛错。
   *
   * 切到本机（在线编辑进行中时）：
   * 1) 先走落盘确认链路（confirmFileSave，确认成功但不撤销会话）——
   *    确认失败留在在线编辑，会话与编辑器保留供重试；
   * 2) 轮换闸门：确认返回与轮换之间编辑器实时脏态翻 true（确认链最后
   *    一次复核之后的敲入）则重走一次确认——旧 key 轮换后在途修改必被
   *    409 丢弃，绝不带着脏信号轮换；
   * 3) 确认成功后服务端轮换 document key（rotateEditorKey）——失败同样
   *    阻止切换（此刻旧实例回调仍会被接受，切走即留下覆盖窗口）；
   * 4) 清除编辑配置缓存：在线编辑器随渲染分支卸载销毁，旧配置的
   *    editor_token 绑定签发时修订号，不得被再次渲染使用。
   * 全程不撤销会话——本机上传（multipart draft/save）依赖有效会话。
   *
   * 切回在线：清除编辑器失败标记并重新取编辑配置（本机期间修订号可能
   * 已推进，缓存配置已失效），加载中由编辑区 Spin 呈现。
   */
  @action.bound
  async switchEditMode(fileId, mode) {
    if (this.finishingFileId) return {ok: false, reason: 'busy'};
    if (!this.sessionKeyOf(fileId) || this.effectiveEditMode(fileId) === mode) {
      return {ok: true};
    }
    if (mode === 'local') {
      const config = this.editorConfigs[fileId];
      if (config && config.editor_available) {
        // 在线能力事实先行登记（配置缓存即将清除，本机面板据此提供
        // 「切回在线编辑」入口，不依赖缓存或配置获取路径）
        this.onlineAvailable[fileId] = true;
        const ok = await this.confirmFileSave(
          fileId, '切换到本机编辑', 'switch_local');
        if (!ok) return {ok: false, reason: 'confirm_failed'};
        // 轮换闸门（2026-10-31 竞态修复）：确认返回与轮换之间编辑器又
        // 报出未保存修改（确认链最后一次复核之后的敲入，documentState
        // 事件在确认返回前后才到达）——旧 key 轮换后该在途修改必被
        // 后端 key 比对 409 丢弃，必须重走一次确认，干净后才允许轮换。
        // 读实时脏态而非 editorDirty 闩锁：markSaveConfirmed 刚把闩锁
        // 清除，闸门要抓的正是"清除之后/清除同拍"到达的脏事件。
        if (this.editorLiveState[fileId]) {
          const reok = await this.confirmFileSave(
            fileId, '切换到本机编辑', 'switch_local');
          if (!reok) return {ok: false, reason: 'confirm_failed'};
        }
        const seq = this.finishSeq;
        try {
          await this.rotateEditorKey(fileId);
        } catch (e) {
          if (seq !== this.finishSeq) return {ok: false, reason: 'cancelled'};
          this.finishingErrorFileId = fileId;
          this.finishingErrorKind = 'switch_local';
          this.finishingError = '已取消切换到本机编辑：旧在线编辑实例的保存'
            + '回调尚未在服务端失效，此时切走其迟到回调可能覆盖本机上传的'
            + '草稿。会话与编辑器已保留，请重试。';
          return {ok: false, reason: 'rotate_failed'};
        }
        if (seq !== this.finishSeq) return {ok: false, reason: 'cancelled'};
      }
      this.editModes[fileId] = 'local';
      delete this.editorConfigs[fileId];
      delete this.editorErrors[fileId];
      delete this.editorDirty[fileId];
      delete this.editorLiveState[fileId];
    } else {
      if (!this.onlineAvailable[fileId]) return {ok: false, reason: 'unavailable'};
      this.editModes[fileId] = 'online';
      delete this.editorLoadFailed[fileId];
      delete this.editorConfigs[fileId];
      this.fetchEditorConfig(fileId);
    }
    return {ok: true};
  }

  /**
   * 会话相关失败统一处置（拦截器已提示，业务代码不得二次弹错）。
   * 后端会话失效文案形如"编辑会话已过期，请重新验证密码"，同时含
   * "会话"与"密码"两词——按"会话"优先归类为会话类失效：仅清除该文件
   * 本地会话（该文件回验证态，可用已验证密码重开）；只有不含"会话"
   * 的密码类错误（如"编辑密码错误"）才清空已验证密码并回密码门。
   * 返回提取的错误文案供调用方判断是否还需记录本地错误信息。
   */
  @action.bound
  handleSessionRelatedError(fileId, err) {
    const text = typeof err === 'string' ? err : '';
    if (text.includes('会话') || text.includes('密码')) {
      this.clearSession(fileId);
    }
    if (!text.includes('会话') && text.includes('密码')) {
      this.verifiedPassword = '';
      this.passwordVerified = false;
    }
    return text;
  }

  // ---------------------------------------------------------------------------
  // 数据加载

  @action.bound
  fetchAll(id, requestedFileId) {
    const seq = ++this.fetchSeq;
    this.id = id;
    this.requestedFileId = requestedFileId || null;
    this.deeplinkNotice = '';
    // 先清空上一本手册可能残留的会话/编辑配置内存态，避免跨手册时
    // 文件 id 撞号误用他册会话；本地会话随后按新手册清单从 sessionStorage 恢复
    this.sessions = {};
    this.editorConfigs = {};
    this.editorErrors = {};
    this.editorLoadingId = null;
    this.editModes = {};
    this.onlineAvailable = {};
    this.editorLoadFailed = {};
    this.localBaselines = {};
    this.isFetching = true;
    this.error = '';
    return Promise.all([
      http.get(`/api/institution/manuals/${id}/`),
      http.get(`/api/institution/manuals/${id}/files/`),
    ]).then(([manualData, fileList]) => {
      if (seq !== this.fetchSeq) return; // 快速切换手册：迟到响应丢弃
      this.manual = manualData;
      this.files = fileList || [];
      this.loadSessions();
      this._applyDeepLinkSelection();
      if (!this.files.some(f => f.id === this.selectedFileId)) {
        this.selectedFileId = this.files.length ? this.files[0].id : null;
      }
      // 本地恢复/仍持有会话且尚无缓存的文件：补取编辑配置（有缓存的不动，
      // 重新取会轮换 document key 使在编编辑器回调失效）
      this.files.forEach(file => {
        if (this.sessionKeyOf(file.id) && !this.editorConfigs[file.id]) {
          this.fetchEditorConfig(file.id);
        }
      });
    }).catch(() => {
      if (seq !== this.fetchSeq) return;
      // 失败时清掉可能残留的上一本手册数据，错误页不被旧数据短路
      this.manual = null;
      this.files = [];
      this.error = '手册不存在或无权限访问草稿（需持有该手册的编制角色）';
    }).finally(() => {
      if (seq === this.fetchSeq) this.isFetching = false;
    });
  }

  /**
   * ?file= 深链选中与状态说明（目标不存在/无草稿时给出明确状态，
   * 绝不静默回退会话目标——验证目标在 verifyPassword 中同样受此约束，
   * 这里只负责选中展示与提示文案）
   */
  @action.bound
  _applyDeepLinkSelection() {
    if (this.requestedFileId == null) return;
    const target = this.files.find(f => f.id === this.requestedFileId);
    if (!target) {
      this.deeplinkNotice =
        '链接指定的文件不存在或已移除，未建立任何编辑会话';
      return;
    }
    this.selectedFileId = target.id;
    if (!target.draft) {
      this.deeplinkNotice = `链接指定的文件「${target.name}」还没有草稿，`
        + '无法建立编辑会话；请先在详情页恢复草稿后再进入';
    }
  }

  /**
   * 刷新文件清单（修订序号/保存状态/编辑占用），不动编辑配置——
   * 重新取配置会轮换 document key，使当前编辑器实例的保存回调失效。
   * 失败向上抛出（拦截器已提示），由调用方决定成功提示时机。
   */
  @action.bound
  refreshFiles() {
    const seq = this.fetchSeq;
    return http.get(`/api/institution/manuals/${this.id}/files/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.files = data || [];
        if (!this.files.some(f => f.id === this.selectedFileId)) {
          this.selectedFileId = this.files.length ? this.files[0].id : null;
        }
      });
  }

  @action.bound
  selectFile(fileId) {
    if (this.files.some(f => f.id === fileId)) this.selectedFileId = fileId;
  }

  // ---------------------------------------------------------------------------
  // ONLYOFFICE 编辑配置（按文件）

  /**
   * 获取指定文件的编辑配置（需该文件的有效编辑会话）。
   * editor_available=false 表示编辑服务未配置，页面走本机编辑降级路径。
   * 已有缓存的文件直接复用：编辑中不得重复调用——重新取配置会轮换
   * document key，使当前编辑器实例的保存回调失效；重新开启会话时
   * clearSession 已清除缓存，自然允许重新取。
   */
  @action.bound
  fetchEditorConfig(fileId) {
    const sessionKey = this.sessionKeyOf(fileId);
    if (!sessionKey) return Promise.resolve();
    if (this.editorConfigs[fileId]) return Promise.resolve();
    this.editorLoadingId = fileId;
    this.editorErrors[fileId] = '';
    return http.get(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/editor-config/?session_key=${sessionKey}`)
      .then(data => {
        this.editorConfigs[fileId] = data;
        // 在线能力标记：本机面板据此继续提供「切回在线编辑」入口（配置
        // 缓存在切到本机时会被清除，能力事实不能随之丢失）
        if (data && data.editor_available) this.onlineAvailable[fileId] = true;
      })
      .catch(err => {
        const text = this.handleSessionRelatedError(fileId, err);
        if (!text.includes('会话') && !text.includes('密码')) {
          this.editorErrors[fileId] = '在线编辑配置加载失败，可使用本机编辑降级路径';
        }
      })
      .finally(() => {
        if (this.editorLoadingId === fileId) this.editorLoadingId = null;
      });
  }

  // ---------------------------------------------------------------------------
  // 会话生命周期

  /**
   * 密码门「验证并进入编辑」：为验证目标文件开启会话。
   * ?file= 深链进入时目标必须是深链指定的文件（且存在、有草稿），
   * 否则给出明确原因并拒绝——绝不静默改开另一份文件的会话；
   * 常规进入（菜单）保持原行为：对第一份有草稿的文件开会话。
   * 验证成功=该文件会话建立成功，随后进入工作区；失败原因记录到
   * verifyError 留在密码门展示（拦截器已弹错，不重复弹）。
   */
  @action.bound
  verifyPassword(password) {
    this.verifying = true;
    this.verifyError = '';
    let target;
    if (this.requestedFileId != null) {
      target = this.files.find(f => f.id === this.requestedFileId) || null;
      if (!target) {
        this.verifying = false;
        this.verifyError = this.deeplinkNotice || '链接指定的文件不存在或已移除';
        return Promise.reject(this.verifyError);
      }
      if (!target.draft) {
        this.verifying = false;
        this.verifyError = `文件「${target.name}」还没有草稿，无法建立编辑会话，`
          + '请先在详情页恢复草稿后再进入';
        return Promise.reject(this.verifyError);
      }
    } else {
      // 负责人独占（2026-10-31）：会话开启=内容写路径，后端要求 编制授权
      // + 该文件负责人。非深链进入时优先选择"有草稿且我是负责人"的文件
      // 建立首个会话，避免把首个有草稿的他人负责文件当验证目标（必然被
      // 后端拒绝，误报成密码/权限错误）。
      target = this.files.length
        ? (this.files.find(f => f.draft && f.assignment && f.assignment.is_mine) ||
          this.files.find(f => f.draft) || this.files[0])
        : null;
    }
    if (!target) {
      this.verifying = false;
      this.verifyError = '手册还没有待发布文件，请先在详情页上传原稿';
      return Promise.reject(this.verifyError);
    }
    return http.post(
      `/api/institution/manuals/${this.id}/files/${target.id}/draft/session/`, {password})
      .then(data => {
        this.saveSession(target.id, data.session_key, data.expires_at);
        this.verifiedPassword = password;
        this.passwordVerified = true;
        return this.fetchEditorConfig(target.id).then(() => data);
      })
      .catch(err => {
        const text = this.handleSessionRelatedError(target.id, err);
        this.verifyError = text || '验证失败，请稍后重试';
        throw err; // 保持 rejected，调用方不得误报成功
      })
      .finally(() => {
        this.verifying = false;
      });
  }

  /**
   * 工作区内「开始编辑此文件」：用本次访问已验证的密码开启该文件会话。
   * 本次访问未验证过密码（如恢复会话直接进入工作区）时回密码门。
   * 同一文件已有本人会话时后端视为续期返回同一会话。
   */
  @action.bound
  startFileSession(fileId) {
    if (!this.verifiedPassword) {
      this.passwordVerified = false;
      return Promise.reject('请先通过编辑密码验证');
    }
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/session/`,
      {password: this.verifiedPassword})
      .then(data => {
        this.saveSession(fileId, data.session_key, data.expires_at);
        return this.fetchEditorConfig(fileId).then(() => data);
      })
      .catch(err => {
        this.handleSessionRelatedError(fileId, err);
        throw err;
      });
  }

  /**
   * 退出指定文件的编辑会话（服务端 revoke）。options.discard=false 仅由
   * 「保存并结束编辑」成功路径（finishEditing）传入：显式告知服务端允许
   * 本编辑实例（同一 current_doc_key）撤销后迟到的收尾回调落盘（幂等
   * 跳过，或保存确认链最后一次复核之后、编辑器销毁之前的最后输入）。
   * 缺省不携带=后端缺省 discard=true（撤销后收尾回调一律拒绝）——
   * 「不保存并退出」等一切其他撤销路径必须维持该显式丢弃语义，不得改默认。
   */
  @action.bound
  exitFileSession(fileId, options) {
    const sessionKey = this.sessionKeyOf(fileId);
    if (!sessionKey) return Promise.resolve();
    // axios.delete 的 body 须放 config.data。
    // 失败不吞错也不清本地会话（拦截器已提示）：保留 session_key 供重试，
    // 服务端会话在 DELETE 成功前仍占用单写位，成功提示由调用方给出。
    const data = {session_key: sessionKey};
    if (options && options.discard === false) data.discard = false;
    return http.delete(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/session/`,
      {data})
      .then(() => this.clearSession(fileId));
  }

  // ---------------------------------------------------------------------------
  // 保存确认与结束编辑（"保存并结束编辑"与离开保护的唯一确认实现）

  /**
   * 尽力而为的落盘触发（仅用于无法拦截的页面卸载兜底，如浏览器关闭、
   * 未经工作台按钮的路由离开）：请求文档服务对当前编辑文档立即
   * forcesave，不等结果、不提示、不改 UI 状态——即使失败，编辑器销毁
   * 后 DS 的关闭回调（会话仍活跃时被接受）仍会把内容落盘。
   * 工作台内可拦截的离开（切换文件/返回详情）必须走 confirmFileSave
   * 的确认链路，不得仅用本方法冒充保护。
   */
  @action.bound
  requestForcesaveQuiet(fileId) {
    const sessionKey = this.sessionKeyOf(fileId);
    const config = this.editorConfigs[fileId];
    if (!sessionKey || !config || !config.editor_available) {
      return Promise.resolve();
    }
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/forcesave/`,
      {session_key: sessionKey}, {skipErrorNotification: true})
      .then(() => {})
      .catch(() => {});
  }

  _delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  /**
   * 轮询服务端草稿修订号直到越过基线（真实落盘确认）：
   * ONLYOFFICE 回调保存经 save_file_draft 推进修订号后才算落盘成功，
   * 前端不得以固定等待时间冒充。单次轮询失败静默重试；超过
   * pollMaxAttempts 仍未确认返回 null（调用方做最终复核或呈现重试状态）。
   * 确认成功返回最新一次轮询的草稿数据（含推进后的修订号/保存人/时间），
   * 并就地更新清单条目的 draft（保存状态展示使用服务端数据）。
   */
  async _pollSaveConfirmed(fileId, baselineRevision, seq) {
    for (let i = 0; i < this.pollMaxAttempts; i++) {
      if (i > 0) await this._delay(this.pollIntervalMs);
      if (seq !== this.finishSeq) return null;
      try {
        const data = await http.get(
          `/api/institution/manuals/${this.id}/files/${fileId}/draft/`,
          {skipErrorNotification: true});
        if (seq !== this.finishSeq) return null;
        if (data && data.revision != null && data.revision > baselineRevision) {
          const entry = this.files.find(f => f.id === fileId);
          if (entry) entry.draft = data;
          return data;
        }
      } catch (e) { /* 单次失败继续重试，超时后统一呈现可重试状态 */ }
    }
    return null;
  }

  _draftRevisionOf(fileId) {
    const entry = this.files.find(f => f.id === fileId);
    return entry && entry.draft && entry.draft.revision != null
      ? entry.draft.revision : 0;
  }

  _requestForcesave(fileId, sessionKey) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/forcesave/`,
      {session_key: sessionKey});
  }

  /**
   * no_changes 沉降复核（2026-10-31 竞态修复，_confirmForcesave 专用）：
   * DS 对 forcesave 的 no_changes 应答只反映命令处理瞬间的缓冲状态——
   * 与命令几乎同拍敲入的修改可能经事件通道晚于命令注册（dev 实测：
   * DS 误答 no_changes → 前端轮换 key 销毁编辑器 → 在途修改随收尾
   * 回调被 409 丢弃）。因此 no_changes 不即时采信，按序三道判据：
   * 1) 编辑器实时脏态已报脏（修改注册晚于命令，DS 应答已过时）→ 在途；
   * 2) 短沉降窗（一次性等待，非固定周期轮询）后再次 forcesave 复核，
   *    DS 改报受理（沉降窗内有修改注册）→ 在途；
   * 3) 复核命令处理之后敲入的修改：documentState 事件在复核应答返回
   *    前后到达，编辑器此刻仍报脏 → 在途。
   * 三道判据全部干净（复核仍 no_changes 且编辑器不报脏）才认定确认。
   * Returns:
   *   {settled: true} 确认成功 | {settled: false} 修改在途，重走确认循环 |
   *   {failed: true} forcesave 请求失败 | {cancelled: true} 已被新序列取代
   */
  async _settleNoChanges(fileId, sessionKey, seq) {
    if (this.editorLiveState[fileId]) return {settled: false};
    if (this.confirmSettleMs > 0) await this._delay(this.confirmSettleMs);
    if (seq !== this.finishSeq) return {cancelled: true};
    let recheck;
    try {
      recheck = await this._requestForcesave(fileId, sessionKey);
    } catch (err) {
      return {failed: true};
    }
    if (seq !== this.finishSeq) return {cancelled: true};
    if (!(recheck && recheck.forcesave === 'no_changes')) {
      return {settled: false};
    }
    if (this.editorLiveState[fileId]) return {settled: false};
    return {settled: true};
  }

  /**
   * 落盘确认核心（"保存并结束编辑"与离开保护共用的唯一实现）：
   * 循环触发 forcesave，直到 DS 报告 no_changes 且经 _settleNoChanges
   * 沉降复核仍然干净，才认定确认成功——no_changes 表示 DS 文档在命令
   * 处理瞬间没有待落盘的修改，即编辑器内容已全部经回调写入制度草稿，
   * 这是比"命令已受理"更强的服务端确认。
   *
   * 每轮：forcesave 受理 → 以响应携带的修订号为基线轮询草稿修订号推进
   * （回调真实落盘的标志）→ 推进后再次 forcesave 复核。复核的必要性：
   * 修订号推进也可能来自其他保存路径（如同账号其他页签的 multipart
   * 保存），若把它误判为本次回调落盘，会在编辑器内容尚未落盘时撤销
   * 会话/销毁编辑器造成丢失；只有 DS 报告 no_changes 才排除这种误判。
   * 轮询超时后做一次最终 forcesave 复核：no_changes 经沉降复核仍干净
   * 仍认定成功（回调内容与当前草稿一致被幂等跳过、修订号不推进的情
   * 形），仍受理则确认失败——绝不冒充成功。
   *
   * 返回 {ok, reason}；成功时写入 saveConfirmed 并清除该文件脏标记。
   */
  async _confirmForcesave(fileId, sessionKey, seq) {
    for (let round = 0; round < this.confirmMaxRounds; round++) {
      let res;
      try {
        res = await this._requestForcesave(fileId, sessionKey);
      } catch (err) {
        return {ok: false, reason: 'forcesave_failed'};
      }
      if (seq !== this.finishSeq) return {ok: false, reason: 'cancelled'};
      if (res && res.forcesave === 'no_changes') {
        const settle = await this._settleNoChanges(fileId, sessionKey, seq);
        if (settle.cancelled) return {ok: false, reason: 'cancelled'};
        if (settle.failed) return {ok: false, reason: 'forcesave_failed'};
        if (settle.settled) {
          this.markSaveConfirmed(fileId, this.files.find(f => f.id === fileId)?.draft);
          return {ok: true, reason: ''};
        }
        continue; // 沉降复核发现修改在途：重走确认循环
      }
      // 受理：以响应修订号为基线；响应异常时退回清单内草稿修订号
      const baseline = res && res.revision != null
        ? res.revision : this._draftRevisionOf(fileId);
      const advanced = await this._pollSaveConfirmed(fileId, baseline, seq);
      if (seq !== this.finishSeq) return {ok: false, reason: 'cancelled'};
      if (advanced) continue; // 修订号已推进：下一轮 forcesave 复核其来源
      // 轮询超时：最终复核一次（受理=修改仍未落盘→失败；no_changes=已
      // 落盘只是幂等跳过未推进修订号→成功，同样经沉降复核）
      let finalRes;
      try {
        finalRes = await this._requestForcesave(fileId, sessionKey);
      } catch (err) {
        return {ok: false, reason: 'forcesave_failed'};
      }
      if (seq !== this.finishSeq) return {ok: false, reason: 'cancelled'};
      if (finalRes && finalRes.forcesave === 'no_changes') {
        const settle = await this._settleNoChanges(fileId, sessionKey, seq);
        if (settle.cancelled) return {ok: false, reason: 'cancelled'};
        if (settle.failed) return {ok: false, reason: 'forcesave_failed'};
        if (settle.settled) {
          this.markSaveConfirmed(fileId, this.files.find(f => f.id === fileId)?.draft);
          return {ok: true, reason: ''};
        }
        continue; // 沉降复核发现修改在途：重走确认循环（轮数耗尽则超时失败）
      }
      return {ok: false, reason: 'timeout'};
    }
    return {ok: false, reason: 'timeout'};
  }

  /**
   * 「保存并结束编辑」：服务端确认内容已落盘后才撤销会话并报告成功。
   * - 在线编辑中：走 _confirmForcesave 确认链路（forcesave → 轮询修订号
   *   → no_changes 复核），确认后才 exitFileSession。
   * - 降级路径（无在线编辑器）：保存是同步 multipart，无未落盘窗口，
   *   直接撤销会话。
   * - 撤销会话显式携带 discard=false（保存意图）：允许本编辑实例撤销后
   *   迟到的收尾回调落盘，确认链最后一次复核之后的最后输入不随编辑器
   *   销毁丢失（降级路径无 DS 实例，该参数不会被任何回调使用）。
   * - 任何失败/超时：保留会话与编辑器，置 finishingError 供界面呈现
   *   重试状态，返回 false。绝不吞错冒充成功。
   */
  @action.bound
  async finishEditing(fileId) {
    const seq = ++this.finishSeq;
    this.finishingFileId = fileId;
    this.finishingErrorFileId = null;
    this.finishingError = '';
    this.finishingErrorKind = '';
    try {
      const sessionKey = this.sessionKeyOf(fileId);
      if (!sessionKey) {
        this.finishingErrorFileId = fileId;
        this.finishingError = '该文件没有进行中的编辑会话';
        return false;
      }
      const config = this.editorConfigs[fileId];
      if (config && config.editor_available) {
        const result = await this._confirmForcesave(fileId, sessionKey, seq);
        if (seq !== this.finishSeq) return false;
        if (!result.ok) {
          this.finishingErrorFileId = fileId;
          this.finishingError = result.reason === 'forcesave_failed'
            ? '保存并结束编辑未完成，会话与编辑器已保留，请重试。'
            : '保存结果未确认：编辑内容可能尚未落盘到服务'
              + '端。会话与编辑器已保留，请稍后重试；也可在编辑器内按 '
              + 'Ctrl+S 保存后再试。';
          return false;
        }
      }
      // 保存意图的撤销：显式 discard=false，DS 在编辑器销毁时补发的
      // 收尾回调（可能晚于撤销到达）允许后端落盘，不再被 403 丢弃
      await this.exitFileSession(fileId, {discard: false});
      if (seq !== this.finishSeq) return false;
      this.refreshFiles().catch(() => {});
      return true;
    } catch (err) {
      if (seq === this.finishSeq) {
        // 具体错误已由拦截器提示一次；这里只呈现可重试状态
        this.finishingErrorFileId = fileId;
        this.finishingError =
          '保存并结束编辑未完成，会话与编辑器已保留，请重试。';
      }
      return false;
    } finally {
      if (seq === this.finishSeq) this.finishingFileId = null;
    }
  }

  /**
   * 离开保护（切换文件/返回详情/切换编辑方式/下载草稿）复用的保存确认：
   * 与 finishEditing 共用 _confirmForcesave 确认链路，但确认成功后不撤销
   * 会话（会话按文件保留，切回可继续编辑；编辑器销毁后 DS 的关闭回调对
   * 已确认内容只会幂等跳过，重新进入轮换 document key 也不会再造成丢失）。
   * errorKind：失败后的重试语境（''=重试保存并结束编辑；'switch_local'/
   * 'download_draft'=对应动作的语境化重试），驱动工作台重试按钮分发。
   * 进行中复用 finishingFileId 状态（工作台禁用冲突导航与重复提交）；
   * 失败保留会话与编辑器，置 finishingError 并带明 context（被取消的
   * 动作）供界面呈现原因与重试入口。
   */
  @action.bound
  async confirmFileSave(fileId, context, errorKind) {
    const seq = ++this.finishSeq;
    this.finishingFileId = fileId;
    this.finishingErrorFileId = null;
    this.finishingError = '';
    this.finishingErrorKind = errorKind || '';
    try {
      const sessionKey = this.sessionKeyOf(fileId);
      if (!sessionKey) return true; // 无会话无在线文档，无需保护
      const config = this.editorConfigs[fileId];
      if (config && config.editor_available) {
        const result = await this._confirmForcesave(fileId, sessionKey, seq);
        if (seq !== this.finishSeq) return false;
        if (!result.ok) {
          this.finishingErrorFileId = fileId;
          this.finishingError = (context ? `已取消${context}：` : '')
            + '当前文件的编辑内容尚未经服务端确认落盘，离开可能丢失。'
            + '会话与编辑器已保留，请重试；也可在编辑器内按 Ctrl+S 后重试。';
          return false;
        }
      }
      return true;
    } catch (err) {
      if (seq === this.finishSeq) {
        // 具体错误已由拦截器提示一次；这里只呈现可重试状态
        this.finishingErrorFileId = fileId;
        this.finishingError = (context ? `已取消${context}：` : '')
          + '当前文件保存未确认，会话与编辑器已保留，请重试。';
      }
      return false;
    } finally {
      if (seq === this.finishSeq) this.finishingFileId = null;
    }
  }

  // ---------------------------------------------------------------------------
  // 草稿保存

  /**
   * 保存指定文件草稿：携带该文件当前修订序号；后端校验会话与修订号，
   * 过期/旧修订被拒绝。成功后用返回的最新草稿更新清单内该文件条目。
   * 会话类失败在 store 内清该文件会话（错误仍向上抛，提示由拦截器负责）。
   * revision：显式提交的期望修订号（本机上传=下载时的基线），缺省取
   * 清单内草稿当前修订号（降级路径的同步保存）。
   */
  @action.bound
  saveDraft(fileId, file, revision) {
    return this._saveDraftRequest(fileId, file, revision)
      .catch(err => {
        this.handleSessionRelatedError(fileId, err);
        throw err;
      });
  }

  /**
   * multipart 保存请求本体（不掺错误分类）：会话与修订号由后端校验；
   * 错误分类由调用方按路径语义处理（在线/降级同步保存清会话，本机
   * 上传保留会话，见 uploadLocalDraft）。
   */
  _saveDraftRequest(fileId, file, revision) {
    this.saving = true;
    const entry = this.files.find(f => f.id === fileId);
    const draft = entry ? entry.draft : null;
    const expectedRevision = revision != null ? revision : (draft ? draft.revision : 0);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_key', this.sessionKeyOf(fileId));
    formData.append('revision', expectedRevision);
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/save/`, formData)
      .then(data => {
        if (entry) entry.draft = data;
        return data;
      })
      .finally(() => {
        this.saving = false;
      });
  }

  /**
   * 本机编辑上传保存（编辑方式=本机时的保存入口）：必须携带下载草稿时
   * 记录的基线修订号——绝不读取清单内最新修订号冒充基线（服务端草稿
   * 已被推进时后端按修订号冲突拒绝，新草稿内容不被覆盖）。
   * 成功：以返回草稿更新清单条目、清除已消费的基线并刷新清单（修订
   * 状态随之刷新）；成功提示由调用方在真实成功响应之后给出。
   * 失败：错误向上抛（拦截器已提示），绝不报成功。
   * - 基线过期（"草稿已被其他会话更新"）：清除基线——用户须重新下载
   *   最新草稿取得新基线后再上传；**会话保留可重试**（修订号冲突不是
   *   会话失效，"其他会话更新"文案含"会话"一词，不得走会话清理规则）。
   * - 其余失败：沿用既有分类——会话类清该文件会话（可重开），密码类
   *   回密码门（handleSessionRelatedError）。
   */
  @action.bound
  uploadLocalDraft(fileId, file) {
    const baseline = this.localBaselines[fileId];
    if (baseline == null) {
      return Promise.reject('请先下载草稿到本机编辑后再上传保存');
    }
    return this._saveDraftRequest(fileId, file, baseline)
      .then(data => {
        delete this.localBaselines[fileId];
        return this.refreshFiles().catch(() => {}).then(() => data);
      })
      .catch(err => {
        const text = typeof err === 'string' ? err : '';
        if (text.includes('草稿已被其他会话更新')) {
          delete this.localBaselines[fileId];
        } else {
          this.handleSessionRelatedError(fileId, err);
        }
        throw err;
      });
  }

  // ---------------------------------------------------------------------------
  // 草稿恢复（无草稿文件；恢复优先级由后端权威决定，前端不猜恢复来源）

  /**
   * 恢复无草稿文件的草稿：POST draft/create（空体）——后端按严格优先级
   * 执行：已有草稿拒绝 > 从当前生效版本快照恢复 > 从最近原稿创建
   * （仅制度从未发布过版本时）。不得静默调用最近原稿。
   */
  @action.bound
  recoverDraft(fileId) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/create/`, {})
      .then(data => this.refreshFiles()
        .catch(() => {})
        .then(() => data));
  }

  /** 拉取某文件的原稿清单（高级恢复：明确按指定原稿重建） */
  @action.bound
  fetchFileOriginals(fileId) {
    return http.get(
      `/api/institution/manuals/${this.id}/files/${fileId}/originals/`)
      .then(data => data || []);
  }

  /**
   * 高级恢复：明确「从原始上传文件重建草稿」（confirm=true）。
   * 有草稿被丢弃且手册配置了编辑密码时，后端要求携带密码校验——
   * 工作台在密码门之后，传本次访问已验证密码。
   */
  @action.bound
  rebuildDraftFromOriginal(fileId, originalId, password) {
    const body = {original_id: originalId, confirm: true};
    if (password) body.password = password;
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/draft/create/`, body)
      .then(data => this.refreshFiles()
        .catch(() => {})
        .then(() => data));
  }

  // ---------------------------------------------------------------------------
  // 文件管理（新增/改名/排序/移除）；成功后刷新文件清单

  /** 新增文件（multipart，可携带 owner_id/note 指定文件负责人）。
   *  draft_error 非空=文件已创建但草稿未就绪（不算失败） */
  @action.bound
  createFile(file, ownerId, note) {
    const formData = new FormData();
    formData.append('file', file);
    if (ownerId) formData.append('owner_id', ownerId);
    if (note) formData.append('note', note);
    return http.post(`/api/institution/manuals/${this.id}/files/create/`, formData)
      .then(data => this.refreshFiles()
        .catch(() => {})
        .then(() => data));
  }

  @action.bound
  renameFile(fileId, name) {
    return http.post(`/api/institution/manuals/${this.id}/files/${fileId}/rename/`, {name})
      .then(data => this.refreshFiles()
        .catch(() => {})
        .then(() => data));
  }

  /** 移动顺序：position 为 1 起目标序位（当前序位±1），清单重取保证全局有序 */
  @action.bound
  moveFile(fileId, position) {
    return http.post(`/api/institution/manuals/${this.id}/files/${fileId}/move/`, {position})
      .then(data => this.refreshFiles()
        .catch(() => {})
        .then(() => data));
  }

  /** 移除文件：清其本地会话；若是选中文件则回落到第一份 */
  @action.bound
  removeFile(fileId) {
    return http.post(`/api/institution/manuals/${this.id}/files/${fileId}/remove/`, {})
      .then(() => {
        this.clearSession(fileId);
        this.files = this.files.filter(f => f.id !== fileId);
        if (this.selectedFileId === fileId) {
          this.selectedFileId = this.files.length ? this.files[0].id : null;
        }
      });
  }

  /** 离开页面时整体复位（sessionStorage 中的会话按设计跨访问保留） */
  @action.bound
  reset() {
    this.finishSeq++; // 使进行中的保存确认轮询与收尾失效
    this.id = null;
    this.manual = null;
    this.files = [];
    this.selectedFileId = null;
    this.isFetching = false;
    this.error = '';
    this.sessions = {};
    this.editorConfigs = {};
    this.editorErrors = {};
    this.editorLoadingId = null;
    this.verifying = false;
    this.verifyError = '';
    this.saving = false;
    this.verifiedPassword = '';
    this.passwordVerified = false;
    this.requestedFileId = null;
    this.deeplinkNotice = '';
    this.finishingFileId = null;
    this.finishingErrorFileId = null;
    this.finishingError = '';
    this.finishingErrorKind = '';
    this.editorDirty = {};
    this.editorLiveState = {};
    this.saveConfirmed = {};
    this.editModes = {};
    this.onlineAvailable = {};
    this.editorLoadFailed = {};
    this.localBaselines = {};
  }
}

export default new DraftStore();
