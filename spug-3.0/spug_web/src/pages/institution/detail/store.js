/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import { observable, action } from 'mobx';
import { http } from 'libs';
import { canViewWorkspace } from '../utils';

class DetailStore {
  fetchSeq = 0;
  @observable id = null;
  @observable manual = null;
  @observable isFetching = false;
  @observable error = '';

  @observable versions = [];
  @observable versionsTotal = 0;
  @observable versionsPage = 1;
  @observable isFetchingVersions = false;
  // 版本清单加载失败置位（错误提示由拦截器弹一次）；不得以空列表冒充成功
  @observable versionsError = '';

  // 当前生效版本文件区域：/versions/<vid>/files/ 的完整快照
  // （version_id/version_no/change_note/previous_version_no/items/removed_items，
  // 变更状态字段由服务端计算）
  @observable currentFiles = null;
  @observable isFetchingCurrentFiles = false;
  @observable currentFilesError = '';

  // 发布前预检（publish-preview）：服务端分组 changed/unchanged/added/
  // removed/blocked；确认窗口数据源
  @observable publishPreview = null;
  @observable isFetchingPublishPreview = false;

  // 草稿状态总览（draft-status）：服务端按哈希/名称/序位计算的逐份
  // "草稿 vs 生效版本"关系与整套摘要（修改/新增/移除/改名/排序）。
  // 加载失败置错误态可重试；失败或未加载时绝不显示"无变化/可发布"。
  @observable draftStatus = null;
  @observable isFetchingDraftStatus = false;
  @observable draftStatusError = '';

  // 文件变更记录（按文件）：发布参与记录 + 该文件操作记录分页
  @observable fileVersion = null;
  @observable isFetchingFileVersion = false;
  // 发布记录加载失败置位（拦截器已提示），不得以空列表冒充成功
  @observable fileVersionError = '';
  @observable fileLogs = [];
  @observable fileLogsTotal = 0;
  @observable fileLogsPage = 1;
  @observable isFetchingFileLogs = false;
  // 文件级请求序号：同手册内快速切换文件/翻页时，较早请求的迟到响应
  // 不得覆盖当前文件的记录（fetchSeq 只守卫手册上下文切换）
  fileVersionReqSeq = 0;
  fileLogsReqSeq = 0;

  // 待发布文件清单（多文件制度）：结构+草稿状态+编辑占用，
  // 仅有 view 角色时条目的 draft/active_session 为 null（只看结构）
  @observable files = [];
  @observable isFetchingFiles = false;

  // 初始来源聚合视图（"初始来源"页签）：一次请求返回全部制度文件行
  // （最初原稿 + 完整原稿历史 + 首次发布版本 + 清理状态），避免文件较多时
  // 为每一行单独发请求；失败置错误态可重试，不以空列表冒充成功
  @observable originalsOverview = [];
  @observable isFetchingOriginalsOverview = false;
  @observable originalsOverviewError = '';

  @observable chapters = [];
  @observable isFetchingChapters = false;

  @observable logs = [];
  @observable logsTotal = 0;
  @observable logsPage = 1;
  @observable isFetchingLogs = false;

  // 逐本账号授权（2026-10-31 授权模型改造，替代旧角色关联；二轮改造起
  // 仅 items 清单，「编制授权者可查看发布版」开关已废除）：
  // {items: [{account_id, account_name, can_view, can_edit, can_publish}]}；
  // 仅手册所有者/平台超级管理员可读写
  @observable authorizations = null;
  @observable isFetchingAuthorizations = false;
  // 授权清单加载失败置位（拦截器已提示），卡片内展示错误与重试
  @observable authorizationsError = '';
  // 授权界面账号候选（全部启用账号，仅 id+name；所有者/平台超级管理员）。
  // 候选加载失败置错误态（skipErrorNotification，由卡片内展示+重试），
  // 绝不把失败静默表现为空候选列表
  @observable accountOptions = [];
  @observable accountOptionsError = '';
  // 所有者候选（所有者移交/超管接管用；启用账号最小清单）；失败置错误态
  @observable ownerCandidates = [];
  @observable ownerCandidatesError = '';

  // 文件清单行「变更记录」入口预选的制度文件 ID（FileChangeTab 经
  // reaction 消费并清空——页签保持挂载时再次跳转同样生效；详情页由此
  // 实现 文件行 -> 按文件变更记录 的直达跳转）
  @observable fileChangeTarget = null;

  @action.bound
  fetchDetail(id) {
    // fetchSeq 是"手册上下文代数"：仅在切换手册时推进（卸载走 reset 统一作废）。
    // 同手册刷新（如 OriginalsTab.refresh 连发 fetchOriginalsOverview+fetchDetail）若也
    // 推进序号，先发的列表请求会在 finally 中拒绝复位 loading，spinner 永久残留。
    const seq = (this.id !== id) ? ++this.fetchSeq : this.fetchSeq;
    this.id = id;
    this.isFetching = true;
    this.error = '';
    return http.get(`/api/institution/manuals/${id}/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.manual = data;
      })
      .catch(() => {
        if (seq !== this.fetchSeq) return;
        this.error = '手册不存在或无权限访问';
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetching = false;
      });
  }

  @action.bound
  fetchVersions(id, page = 1) {
    const seq = this.fetchSeq;
    this.isFetchingVersions = true;
    return http.get(`/api/institution/manuals/${id}/versions/`, {
      params: {page, page_size: 10},
    }).then(data => {
      if (seq !== this.fetchSeq) return;
      this.versions = data.items || [];
      this.versionsTotal = data.total || 0;
      this.versionsPage = page;
      this.versionsError = '';
    }).catch(() => {
      // 拦截器已提示；置错误态并清空列表，不冒充成功数据
      if (seq !== this.fetchSeq) return;
      this.versions = [];
      this.versionsTotal = 0;
      this.versionsError = '版本清单加载失败，请重试';
    }).finally(() => {
      if (seq === this.fetchSeq) this.isFetchingVersions = false;
    });
  }

  @action.bound
  fetchCurrentFiles(id, versionId) {
    const seq = this.fetchSeq;
    this.isFetchingCurrentFiles = true;
    return http.get(`/api/institution/manuals/${id}/versions/${versionId}/files/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.currentFiles = data || {};
        this.currentFilesError = '';
      })
      .catch(() => {
        // 拦截器已提示；置错误态可重试，不以空清单冒充成功
        if (seq !== this.fetchSeq) return;
        this.currentFiles = null;
        this.currentFilesError = '当前生效文件加载失败，请重试';
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingCurrentFiles = false;
      });
  }

  @action.bound
  clearCurrentFiles() {
    this.currentFiles = null;
    this.currentFilesError = '';
    this.isFetchingCurrentFiles = false;
  }

  @action.bound
  fetchPublishPreview(id) {
    const seq = this.fetchSeq;
    this.isFetchingPublishPreview = true;
    return http.get(`/api/institution/manuals/${id}/publish-preview/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.publishPreview = data || {};
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingPublishPreview = false;
      });
  }

  @action.bound
  fetchFiles(id) {
    const seq = this.fetchSeq;
    this.isFetchingFiles = true;
    return http.get(`/api/institution/manuals/${id}/files/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.files = data || [];
      })
      .catch(() => {
        // 失败置空（拦截器已提示），不得以空清单冒充成功数据之外的语义
        if (seq !== this.fetchSeq) return;
        this.files = [];
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingFiles = false;
      });
  }

  /**
   * 草稿状态总览（draft-status/，编制/发布角色可见；仅查看角色调用方
   * 不应调用本方法）。失败置错误态并清空旧状态，可重试——失败后绝不
   * 沿用旧数据冒充"无变化/一致"。
   */
  @action.bound
  fetchDraftStatus(id) {
    const seq = this.fetchSeq;
    this.isFetchingDraftStatus = true;
    return http.get(`/api/institution/manuals/${id}/draft-status/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.draftStatus = data || null;
        this.draftStatusError = '';
      })
      .catch(() => {
        // 拦截器已提示；置错误态可重试，不以旧状态或"无变化"冒充成功
        if (seq !== this.fetchSeq) return;
        this.draftStatus = null;
        this.draftStatusError = '草稿状态加载失败，请重试';
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingDraftStatus = false;
      });
  }

  @action.bound
  fetchOriginalsOverview(id) {
    const seq = this.fetchSeq;
    this.isFetchingOriginalsOverview = true;
    return http.get(`/api/institution/manuals/${id}/originals-overview/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.originalsOverview = (data && data.files) || [];
        this.originalsOverviewError = '';
      })
      .catch(() => {
        // 拦截器已提示；置错误态可重试，不以空列表冒充成功
        if (seq !== this.fetchSeq) return;
        this.originalsOverview = [];
        this.originalsOverviewError = '初始来源加载失败，请重试';
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingOriginalsOverview = false;
      });
  }

  @action.bound
  fetchChapters(id) {
    const seq = this.fetchSeq;
    this.isFetchingChapters = true;
    return http.get(`/api/institution/manuals/${id}/chapters/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.chapters = data || [];
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingChapters = false;
      });
  }

  /**
   * 指定/改派/清空文件负责人（文件分工；ownerId=null 即清空为未分配）。
   * 成功后用返回的文件行就地更新清单；失败向上抛（拦截器已提示）。
   */
  @action.bound
  assignFile(fileId, ownerId, note) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/assignment/`,
      {owner_id: ownerId, note: note || ''})
      .then(data => this.updateFileRow(fileId, data));
  }

  /**
   * 批量文件分工：勾选多份文件统一指定/清空负责人并填写分工说明。
   * 后端逐文件校验归属，全成功或全失败；成功后用返回的文件行就地
   * 更新清单（不整页重取）；失败向上抛（拦截器已提示）。
   */
  @action.bound
  batchAssignFiles(fileIds, ownerId, note) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/batch-assignment/`,
      {file_ids: fileIds, owner_id: ownerId, note: note || ''})
      .then(data => {
        (data && data.files || []).forEach(row => this.updateFileRow(row.id, row));
        return data;
      });
  }

  /**
   * 开始修订（已发布文件的真实状态动作）：开启新一轮修订并复用现有
   * 工作副本。返回服务端结果——needs_repair=true 时由调用方明确提示
   * （工作副本缺失/损坏/与生效基线不一致）并携带 confirm_repair 重试。
   * 失败向上抛。
   */
  @action.bound
  startRevision(fileId, confirmRepair = false) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/revision/start/`,
      confirmRepair ? {confirm_repair: true} : {});
  }

  /**
   * 提交编制（负责人完成编制后的交接标记：后端记录草稿修订号与时间；
   * 草稿再次保存/重建后提交状态按修订号比对自动失效）。失败向上抛。
   */
  @action.bound
  submitCompile(fileId) {
    return http.post(
      `/api/institution/manuals/${this.id}/files/${fileId}/submit/`, {})
      .then(data => this.updateFileRow(fileId, data));
  }

  /** 用接口返回的最新文件行就地更新清单（保持原有顺序，不整页重取） */
  @action.bound
  updateFileRow(fileId, data) {
    const idx = this.files.findIndex(f => f.id === fileId);
    if (idx >= 0 && data && data.id === fileId) {
      this.files.splice(idx, 1, data);
    }
    return data;
  }

  @action.bound
  fetchLogs(id, page = 1) {
    const seq = this.fetchSeq;
    this.isFetchingLogs = true;
    return http.get(`/api/institution/manuals/${id}/operation-logs/`, {
      params: {page, page_size: 15},
    }).then(data => {
      if (seq !== this.fetchSeq) return;
      this.logs = data.items || [];
      this.logsTotal = data.total || 0;
      this.logsPage = page;
    }).finally(() => {
      if (seq === this.fetchSeq) this.isFetchingLogs = false;
    });
  }

  /**
   * 逐本账号授权清单（GET authorizations/，所有者或平台超级管理员）。
   * 失败置错误态可重试，不以空清单冒充成功（拦截器已提示一次）。
   */
  @action.bound
  fetchAuthorizations(id) {
    const seq = this.fetchSeq;
    this.isFetchingAuthorizations = true;
    return http.get(`/api/institution/manuals/${id}/authorizations/`)
      .then(data => {
        if (seq !== this.fetchSeq) return;
        this.authorizations = data || {items: []};
        this.authorizationsError = '';
      })
      .catch(() => {
        if (seq !== this.fetchSeq) return;
        this.authorizations = null;
        this.authorizationsError = '授权清单加载失败，请重试';
      })
      .finally(() => {
        if (seq === this.fetchSeq) this.isFetchingAuthorizations = false;
      });
  }

  /**
   * 整体替换授权（PUT authorizations/，所有者或平台超级管理员）：
   * items 全量；返回 revoked_sessions（失去编制授权被撤销的进行中编辑
   * 会话数），由调用方提示。成功后以响应刷新本地授权状态。失败向上抛
   * （拦截器已提示）。
   */
  @action.bound
  saveAuthorizations(id, items) {
    return http.put(`/api/institution/manuals/${id}/authorizations/`, {items})
      .then(data => {
        this.authorizations = {
          items: (data && data.items) || [],
        };
        this.authorizationsError = '';
        return data;
      });
  }

  /**
   * 授权界面账号候选（全部启用账号，仅 id+name；所有者/制度管理员）。
   * skipErrorNotification：错误在卡片内展示一次并提供重试（FileAssignmentModal
   * 同款模式），绝不把失败静默表现为空候选列表。
   */
  @action.bound
  fetchAccountOptions(id) {
    return http.get(`/api/institution/manuals/${id}/account-options/`,
      {skipErrorNotification: true})
      .then(data => {
        this.accountOptions = data || [];
        this.accountOptionsError = '';
      })
      .catch(err => {
        this.accountOptions = [];
        this.accountOptionsError =
          typeof err === 'string' && err ? err : '账号候选加载失败';
      });
  }

  /** 所有者候选（所有者移交/超管接管；启用账号最小清单；错误卡片内展示+重试） */
  @action.bound
  fetchOwnerCandidates(id) {
    return http.get(`/api/institution/manuals/${id}/owner-candidates/`,
      {skipErrorNotification: true})
      .then(data => {
        this.ownerCandidates = data || [];
        this.ownerCandidatesError = '';
      })
      .catch(err => {
        this.ownerCandidates = [];
        this.ownerCandidatesError =
          typeof err === 'string' && err ? err : '所有者候选加载失败';
      });
  }

  /**
   * 所有者移交/超管接管（POST owner/；所有者可移交启用账号，平台超管
   * 可指定/接管，原所有者移交后失权）。成功后用返回的手册详情刷新
   * manual（owner_name/is_owner 随之更新）。失败向上抛（拦截器已提示）。
   */
  @action.bound
  setManualOwner(id, accountId) {
    return http.post(`/api/institution/manuals/${id}/owner/`,
      {account_id: accountId})
      .then(data => {
        if (data && data.id) {
          this.manual = data;
        } else {
          return this.fetchDetail(id);
        }
        return data;
      });
  }

  /**
   * 按文件回看发布参与记录（files/<fid>/version-history/，服务端按快照
   * 哈希计算变更状态）。失败置错误态可重试，不以空列表冒充成功。
   * reqSeq 守卫：同手册内快速切换文件时，较早请求的迟到响应不写入。
   */
  @action.bound
  fetchFileVersionHistory(id, fileId) {
    const seq = this.fetchSeq;
    const reqSeq = ++this.fileVersionReqSeq;
    this.isFetchingFileVersion = true;
    return http.get(
      `/api/institution/manuals/${id}/files/${fileId}/version-history/`)
      .then(data => {
        if (seq !== this.fetchSeq || reqSeq !== this.fileVersionReqSeq) return;
        this.fileVersion = data || {};
        this.fileVersionError = '';
      })
      .catch(() => {
        if (seq !== this.fetchSeq || reqSeq !== this.fileVersionReqSeq) return;
        this.fileVersion = null;
        this.fileVersionError = '发布记录加载失败，请重试';
      })
      .finally(() => {
        if (seq === this.fetchSeq && reqSeq === this.fileVersionReqSeq) {
          this.isFetchingFileVersion = false;
        }
      });
  }

  /**
   * 按文件过滤的操作记录（operation-logs/?file_id=，后端过滤+分页）。
   * reqSeq 守卫：快速切换文件/翻页时，较早请求的迟到响应不写入。
   */
  @action.bound
  fetchFileLogs(id, fileId, page = 1) {
    const seq = this.fetchSeq;
    const reqSeq = ++this.fileLogsReqSeq;
    this.isFetchingFileLogs = true;
    return http.get(`/api/institution/manuals/${id}/operation-logs/`, {
      params: {page, page_size: 15, file_id: fileId},
    }).then(data => {
      if (seq !== this.fetchSeq || reqSeq !== this.fileLogsReqSeq) return;
      this.fileLogs = data.items || [];
      this.fileLogsTotal = data.total || 0;
      this.fileLogsPage = page;
    }).finally(() => {
      if (seq === this.fetchSeq && reqSeq === this.fileLogsReqSeq) {
        this.isFetchingFileLogs = false;
      }
    });
  }

  /** 切换文件时清空上一份文件的记录：loading 期间不残留上一文件数据，
   *  也不会把旧文件记录误显示为新文件的记录 */
  @action.bound
  clearFileRecords() {
    this.fileVersion = null;
    this.fileVersionError = '';
    this.fileLogs = [];
    this.fileLogsTotal = 0;
    this.fileLogsPage = 1;
  }

  /**
   * 详情入口的整套草稿状态拉取：仅工作区可见者（编制/发布角色或管理
   * 权限）请求；仅查看角色不请求也不展示（后端对该接口同样拒绝）。
   */
  @action.bound
  fetchDraftStatusIfAllowed(id) {
    if (this.manual && canViewWorkspace(this.manual)) this.fetchDraftStatus(id);
  }

  /**
   * 生命周期动作（发布/回退/废止）后的统一刷新：详情、版本历史、操作
   * 记录、整套草稿状态（仅工作区可见者请求，仅查看角色后端亦拒绝）与
   * 当前生效文件清单。刷新只由真实动作触发，禁止固定周期轮询。
   */
  @action.bound
  refreshAfterLifecycle(id) {
    return this.fetchDetail(id).then(() => {
      this.fetchVersions(id, 1);
      this.fetchLogs(id, 1);
      if (canViewWorkspace(this.manual)) this.fetchDraftStatus(id);
      const current = this.manual && this.manual.current_version;
      if (current && current.id != null) {
        this.fetchCurrentFiles(id, current.id);
      } else {
        this.clearCurrentFiles();
      }
    });
  }

  @action.bound
  reset() {
    // 卸载/重挂载即切换上下文：作废全部在途请求并清空 id，
    // 保证旧挂载的迟到响应不会写入新挂载的状态
    this.fetchSeq++;
    this.id = null;
    this.manual = null;
    this.isFetching = false;
    this.isFetchingFiles = false;
    this.isFetchingVersions = false;
    this.isFetchingOriginalsOverview = false;
    this.isFetchingChapters = false;
    this.isFetchingLogs = false;
    this.error = '';
    this.files = [];
    this.versions = [];
    this.originalsOverview = [];
    this.originalsOverviewError = '';
    this.chapters = [];
    this.logs = [];
    this.versionsPage = 1;
    this.logsPage = 1;
    this.versionsError = '';
    this.currentFiles = null;
    this.currentFilesError = '';
    this.isFetchingCurrentFiles = false;
    this.publishPreview = null;
    this.isFetchingPublishPreview = false;
    this.draftStatus = null;
    this.isFetchingDraftStatus = false;
    this.draftStatusError = '';
    this.fileVersion = null;
    this.isFetchingFileVersion = false;
    this.fileVersionError = '';
    this.fileLogs = [];
    this.fileLogsTotal = 0;
    this.fileLogsPage = 1;
    this.isFetchingFileLogs = false;
    this.fileChangeTarget = null;
    this.authorizations = null;
    this.isFetchingAuthorizations = false;
    this.authorizationsError = '';
    this.accountOptions = [];
    this.accountOptionsError = '';
    this.ownerCandidates = [];
    this.ownerCandidatesError = '';
  }
}

export default new DetailStore();
