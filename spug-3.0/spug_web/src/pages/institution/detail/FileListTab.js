/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签（详情页默认页签，2026-10-30 双视图版；2026-11-03 固定
 * 快照交接改造）：
 * 页签内分两个内容视图（不新增顶层页签），杜绝"已发布文件 / 待发布草稿 /
 * 提交待发布核对"三种状态混为一谈：
 * - 「当前生效版本 vN」：最近一次发布形成的不可变快照清单。预览/下载始终
 *   打开发布快照，按钮与预览标题均注明版本来源（预览当前生效版 vN）；
 *   草稿侧的"已从待发布移除"以行内 Tag 提示（发布后该文件将不在清单中）。
 *   2026-10-31 起不展示负责人列（负责人属修订分工，只在「修订草稿」视图
 *   展示与维护；assignment 数据仍随行关联，供「只看我负责的文件」筛选）。
 * - 「修订草稿」：待发布工作内容。列=顺序/文件名/大小/负责人/状态（草稿 vs
 *   生效版本关系+修订进行中）/编制状态/操作。未冻结文件的预览与下载明确
 *   打开**当前**待发布草稿（预览待发布草稿：文件名），仅持编制角色者可用
 *   （后端同样要求 draft_edit + can_edit_draft，前端不扩权）。
 * 默认视图：有生效版本 → 当前生效版本；首次发布前 → 修订草稿。切换视图
 * 保留「只看我负责的文件」筛选并清空行勾选（勾选属于草稿视图的批量分工）。
 * **2026-11-03 固定快照交接（最重要）**：提交待发布核对由服务端创建独立
 * 不可变快照并冻结该文件内容——冻结期间不能编辑/改名/排序/移除/改派分工/
 * 重复提交；预览与下载改读 `submission/preview-url/`、`submission/download/`
 * （标题「预览待核对快照：文件名（提交人 X，提交时间 Y）」），发布时使用
 * 同一快照。编制状态唯一实现 `../compilationStatusShared.js`
 * buildCompilationState（待发布人核对/可直接纳入整套发布/待提交待发布核对/
 * 待负责人提交待发布核对/已撤回/已退回/提交已失效/旧版提交记录/编制中/
 * 无需提交），服务端字段只映射不推断；`legacy_submitted` 旧提交记录**不可
 * 用于发布**，必须按新规则重新提交（说明与 Tooltip 明确提示）。
 * 提交入口（「提交待发布核对」/「重新提交」）只对文件有效负责人
 * （assignment.is_effective_owner，旧 payload 回退 is_mine）渲染；pending
 * 显示不可点击「待发布人核对」+「撤回提交」（有效负责人本人）；持发布权且
 * 非该文件有效负责人可「退回修改」（原因必填 ≤500）。撤回/退回后旧快照
 * 作废、内容解冻。编辑会话进行中禁用提交并提示先「保存并结束编辑」。
 * 负责人列展示**有效负责人**（文件负责人 > 手册所有者默认 > 未分配）：
 * `owner_assigned=false` 时后缀「（手册所有者，默认）」，只有 effective_owner
 * 为空才显示「未分配」。负责人是当前责任归属（仅在「修订草稿」视图展示与
 * 维护）：2026-10-31 授权模型下负责人独占编辑——编辑=模块 draft_edit 权限 +
 * 手册编制授权（my_roles.edit）+ 该文件负责人身份，同一文件受单写会话
 * 限制（同一时间仅一人）；分工入口在「修订草稿」视图的负责人列
 * （仅所有者/制度管理员可写；冻结文件不可改派），不改变任何权限。
 * 行操作：修订进行中 → 「继续编辑」深链复用工作副本；修订已结束 →
 * 「开始修订」（真实状态动作，needs_repair 时经确认从生效版本快照修复）。
 * 两个视图的行操作都提供统一的「文件历史」入口：按 file_id 直接打开
 * FileHistoryModal（标题=制度文件名，内含 发布记录/操作记录 两个子页签，
 * 始终定位同一份制度文件；不切换顶层页签，弹窗关闭后清单视图、滚动位置
 * 与行勾选保持不变）。已取消的「历史来源/高级恢复/更换来源」入口不再提供。
 * 「新增制度文件」入口在「修订草稿」视图顶部（隐藏 input 由 ref 程序触发）：
 * 选择文件后**先弹分工弹窗**（负责人默认手册所有者=manual.owner_id，候选
 * 走 assignment-owners，可改选其他持编制资格账号或清空），确认后才逐份
 * files/create 并携带 owner_id/note（每个上传文件各建立一个独立制度文件
 * 与当前草稿；创建失败由拦截器提示；业务门=所有者或制度管理员）。
 * 数据源（均为服务端权威计算，前端只展示、不推断）：
 * - /files/：待发布集合 + 修订状态 + 文件分工（草稿与提交状态仅工作区
 *   可见者返回；负责人为责任信息对所有可见者下发）
 * - /draft-status/：逐份内容关系与整套摘要（服务端按哈希/名称/序位计算）
 * - /versions/<vid>/files/：生效快照（预览/下载走当前生效版本端点）
 * 加载失败置错误态可重试，绝不以空清单或"无变化"冒充；已清理快照只显示
 * 元数据，不提供会失败的预览/下载。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message, Alert, Button, Tooltip, Checkbox,
  Segmented } from 'antd';
import { AuthButton } from 'components';
import ManualAuthButton from '../ManualAuthButton';
import { hasPermission, history } from 'libs';
import { http } from 'libs';
import {
  canViewPublished, canViewWorkspace, downloadFile, formatSize,
  formatDateTime,
} from '../utils';
import PreviewModal from './PreviewModal';
import FileAssignmentModal from './FileAssignmentModal';
import FileHistoryModal from './FileHistoryModal';
import { buildFileState } from './draftStatusShared';
import { buildCompilationState } from '../compilationStatusShared';
import {
  buildSubmissionPreviewTitle, canReturnSubmission, canWithdrawSubmission,
  effectiveOwnerIdOf, effectiveOwnerNameOf, isEffectiveOwnerOf,
  isFrozenSubmission, ownerIsDefaultAssignment, submissionIsStale,
  submissionOf, submissionSnapshotFileName, submissionStatusOf,
  SUBMISSION_STATUS,
} from '../submissionShared';
import store from './store';
import institutionBadge from '../../../layout/InstitutionBadgeStore';

const VIEW_EFFECTIVE = 'effective';
const VIEW_DRAFT = 'draft';

@observer
class FileListTab extends React.Component {
  state = {
    preview: null, assignmentFile: null, batchAssign: false,
    onlyMine: false, selectedKeys: [], activeView: null,
    // 行「文件历史」弹窗目标（file_id + 展示名；两种清单视图行入口共用）
    historyFileId: null, historyFileName: '',
    uploading: false,
    // 新增制度文件：已选待创建文件（非空时展示分工弹窗，确认后才逐份创建）
    uploadFiles: null,
  };

  componentDidMount() {
    const manual = store.manual || {};
    // 文件结构对查看角色可见（后端 /files/ 同口径：草稿信息仅工作区填充）
    store.fetchFiles(store.id);
    if (canViewPublished(manual)) {
      const current = manual.current_version;
      if (current && current.id != null) {
        store.fetchCurrentFiles(store.id, current.id);
      }
    }
    // 逐份内容关系：仅工作区可见者请求（后端同样拒绝）
    if (canViewWorkspace(manual)) {
      store.fetchDraftStatus(store.id);
    }
  }

  componentWillUnmount() {
    this.unmounted = true;
  }

  /** 默认视图：有生效版本 → 当前生效版本；首次发布前 → 修订草稿 */
  defaultView(manual) {
    const hasCurrent = !!(manual.current_version &&
      manual.current_version.id != null);
    return hasCurrent ? VIEW_EFFECTIVE : VIEW_DRAFT;
  }

  /** 当前生效视图：仅允许该账号有权可见的视图（后端对数据同样分权） */
  currentView(manual) {
    const requested = this.state.activeView || this.defaultView(manual);
    if (requested === VIEW_DRAFT && !canViewWorkspace(manual)) {
      return VIEW_EFFECTIVE;
    }
    if (requested === VIEW_EFFECTIVE && !canViewPublished(manual)) {
      return VIEW_DRAFT;
    }
    return requested;
  }

  handleViewChange = (view) => {
    // 切换视图清空行勾选（批量分工属于草稿视图的操作，不得对另一视图
    // 的行误操作）；保留「只看我负责的文件」筛选与滚动体验
    this.setState({activeView: view, selectedKeys: []});
  };

  refresh() {
    const id = store.id;
    // 刷新后不保留旧选择：避免对旧清单的勾选误操作
    this.setState({selectedKeys: []});
    store.fetchDetail(id).then(() => {
      const manual = store.manual || {};
      const current = manual.current_version;
      if (canViewPublished(manual) && current && current.id != null) {
        store.fetchCurrentFiles(id, current.id);
      } else {
        store.clearCurrentFiles();
      }
      store.fetchFiles(id);
      if (canViewWorkspace(manual)) {
        store.fetchDraftStatus(id);
      }
    });
  }

  /**
   * 「新增制度文件」批量上传（2026-11-02 改造：先分工后上传）。
   * 选择文件后**先弹分工弹窗**（负责人默认手册所有者=manual.owner_id，
   * 候选走 assignment-owners，可改选其他持编制资格账号或清空），确认后
   * 才逐份 files/create 并携带 owner_id/note（每个上传文件各建立一个
   * 独立制度文件与当前草稿，绝不把多个文件追加到同一项）。门禁与后端
   * files/create 一致：upload 页面权限码 且（手册所有者或制度管理员）；
   * 无权限时只给只读说明。隐藏 input 由 ref 程序触发，不得嵌套在
   * Button/label 内。
   */
  handleUploadClick = () => {
    if (this.uploadInput) this.uploadInput.click();
  };

  handleUploadChange = (e) => {
    const picked = Array.from(e.target.files || []);
    e.target.value = '';
    if (!picked.length) return;
    // 只暂存所选文件，真正创建等分工弹窗确认（默认负责人=手册所有者）
    this.setState({uploadFiles: picked});
  };

  /** 分工弹窗确认：逐份创建（owner_id 显式携带，null 以空串提交=未分配） */
  handleUploadAssignSubmit = (ownerId, note) => {
    const picked = this.state.uploadFiles || [];
    if (!picked.length) return Promise.resolve();
    return this.createFiles(picked, ownerId, note).then(() => {
      if (!this.unmounted) this.setState({uploadFiles: null});
    });
  };

  async createFiles(picked, ownerId, note) {
    this.setState({uploading: true});
    let okCount = 0;
    // 逐个顺序上传：单个失败（拦截器已弹错）不中断剩余文件
    for (const file of picked) {
      const formData = new FormData();
      formData.append('file', file);
      // 负责人/分工说明显式携带：owner_id 空串=清空为未分配（后端按字段
      // 是否存在区分"未指定"与"显式未分配"，不得省略该字段）
      formData.append('owner_id', ownerId == null ? '' : String(ownerId));
      if (note) formData.append('note', note);
      try {
        // 每份上传文件各自创建一个独立制度文件与当前草稿；失败由 HTTP
        // 拦截器提示一次，这里不重复弹错、也不额外警示
        await http.post(
          `/api/institution/manuals/${store.id}/files/create/`, formData);
        okCount += 1;
      } catch (err) {
        // 拦截器已提示单个失败，继续传剩余文件
      }
    }
    if (this.unmounted) return;
    this.setState({uploading: false});
    if (okCount) {
      message.success(
        `已新增 ${okCount} 份待发布文件，上传文件作为各自文件的当前草稿`);
    }
    this.refresh();
  }

  handleDeprecate = () => {
    Modal.confirm({
      title: '废止确认',
      content: '废止后制度暂无生效版本，历史版本文件保留。确定废止当前生效版本？',
      onOk: () => http.post(`/api/institution/manuals/${store.id}/deprecate/`)
        .then(() => {
          message.success('已废止');
          this.refresh();
        }),
    });
  };

  showPreview = (request, fileName, title) => {
    request.then(data => {
      this.setState({preview: {
        url: data.preview_url, fileName: data.file_name || fileName, title,
      }});
    });
  };

  /** 行「文件历史」：按 file_id 直接打开弹窗（不切顶层页签）。
   *  两种清单视图共用：始终定位同一份制度文件；弹窗关闭后清单视图、
   *  滚动位置与行勾选保持不变 */
  openFileHistory = (fileId, fileName) => {
    this.setState({historyFileId: fileId, historyFileName: fileName || ''});
  };

  /** 生效视图预览/下载：始终打开当前生效版本的发布快照（不可变）；
   *  无快照或已清理不渲染入口 */
  renderSnapshotActions(snap, cf) {
    if (!snap || !cf || snap.is_cleaned) return null;
    const versionNo = cf.version_no;
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.showPreview(
            http.get(`/api/institution/manuals/${store.id}/versions/${cf.version_id}/files/${snap.id}/preview-url/`),
            snap.file_name, `预览当前生效版 v${versionNo}：${snap.file_name}`)}>
          预览当前生效版
        </AuthButton>
        <Tooltip title={`下载当前生效版本 v${versionNo} 的发布快照（不受草稿修改影响）`}>
          <AuthButton auth="institution.manual.download" type="link" size="small"
            onClick={() => downloadFile(
              `/api/institution/manuals/${store.id}/versions/${cf.version_id}/files/${snap.id}/download/`,
              snap.file_name)}>下载</AuthButton>
        </Tooltip>
      </span>
    );
  }

  /** 草稿视图预览/下载（未冻结文件）：明确打开**当前**待发布草稿（尚未
   *  生效）。后端要求 draft_edit + 编制授权（负责人域），前端只在 负责人
   *  （编制授权 + is_mine）行渲染，与负责人独占编辑口径一致，不扩权。
   *  冻结文件（有效提交固定快照）改用 renderSubmissionSnapshotActions。 */
  renderDraftFileActions(file) {
    const draft = file.draft;
    if (!draft) return null;
    const name = draft.file_name || file.name;
    const manual = store.manual || {};
    return (
      <span>
        <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
          type="link" size="small"
          onClick={() => this.showPreview(
            http.get(`/api/institution/manuals/${store.id}/files/${file.id}/draft/preview-url/`),
            name, `预览待发布草稿：${name}`)}>
          预览草稿
        </ManualAuthButton>
        <Tooltip title="下载当前待发布草稿（尚未生效的工作副本）">
          <ManualAuthButton manual={manual} auth="institution.manual.download"
            type="link" size="small"
            onClick={() => downloadFile(
              `/api/institution/manuals/${store.id}/files/${file.id}/draft/download/`,
              name)}>下载</ManualAuthButton>
        </Tooltip>
      </span>
    );
  }

  /** 冻结文件（有效提交固定快照）的预览/下载：改读 submission 快照端点，
   *  不再打开当前草稿——负责人核对与发布人核对读同一份**不可变快照**，
   *  发布时也使用该快照；下载文件名用接口返回的快照文件名 */
  renderSubmissionSnapshotActions(file) {
    const manual = store.manual || {};
    const name = submissionSnapshotFileName(file);
    return (
      <span>
        <ManualAuthButton manual={manual} auth="institution.manual.view"
          type="link" size="small"
          onClick={() => this.showSubmissionPreview(file)}>
          预览待核对快照
        </ManualAuthButton>
        <Tooltip title={`下载该文件已提交的固定快照（${name}）；整套发布将使用该快照内容`}>
          <ManualAuthButton manual={manual} auth="institution.manual.download"
            type="link" size="small"
            onClick={() => this.handleDownloadSubmission(file)}>
            下载待核对快照
          </ManualAuthButton>
        </Tooltip>
      </span>
    );
  }

  /** 待核对快照预览：标题统一为「预览待核对快照：<文件名>（提交人 X，提交时间 Y）」，
   *  提交人/提交时间/文件名优先取接口返回（其次快照落库字段），绝不冒充当前草稿 */
  showSubmissionPreview = (file) => {
    store.fetchSubmissionPreviewUrl(file.id)
      .then(data => this.setState({preview: {
        url: data && data.preview_url,
        fileName: (data && data.file_name) || submissionSnapshotFileName(file),
        title: buildSubmissionPreviewTitle(file, data),
      }}))
      .catch(() => {});
  };

  /** 下载待核对快照（二进制失败由拦截器提示；文件名用接口下发的快照文件名） */
  handleDownloadSubmission = (file) => {
    downloadFile(
      `/api/institution/manuals/${store.id}/files/${file.id}/submission/download/`,
      submissionSnapshotFileName(file));
  };

  /** 开始修订：真实状态动作。needs_repair 时明确提示并二次确认修复 */
  handleStartRevision = (file) => {
    store.startRevision(file.id)
      .then(data => {
        if (data && data.needs_repair) {
          this.confirmRepair(file, data);
          return;
        }
        message.success(data && data.resumed ? '该文件修订已在进行中' : '已开始修订');
        history.push(`/institution/manuals/${store.id}/draft?file=${file.id}`);
      })
      .catch(() => {});
  };

  confirmRepair = (file, data) => {
    Modal.confirm({
      title: `开始修订：${file.name}`,
      content: (
        <div>
          <p>{data.message}</p>
          {data.draft_recovery && data.draft_recovery.source === 'current_version' && (
            <p style={{color: '#888'}}>
              修复来源：当前生效版本 v{data.draft_recovery.version_no} 的文件快照。
            </p>
          )}
        </div>
      ),
      okText: '确认修复并开始修订',
      onOk: () => store.startRevision(file.id, true)
        .then(() => {
          message.success('工作副本已修复，修订已开始');
          history.push(`/institution/manuals/${store.id}/draft?file=${file.id}`);
        }),
    });
  };

  /** 文件分工（单文件，负责人列点击入口）：保存后行内刷新 */
  handleAssignSubmit = (fileId) => (ownerId, note) => {
    return store.assignFile(fileId, ownerId, note)
      .then(() => message.success('文件分工已保存'));
  };

  /** 批量分工：后端逐文件校验归属，全成功或全失败 */
  handleBatchSubmit = (fileIds) => (ownerId, note) => {
    return store.batchAssignFiles(fileIds, ownerId, note)
      .then(() => {
        message.success(`已更新 ${fileIds.length} 份文件的负责人`);
        this.setState({selectedKeys: []});
      });
  };

  handleBatchClear = () => {
    const ids = this.batchFileIds();
    const names = (store.files || [])
      .filter(f => ids.includes(f.id)).map(f => f.name);
    Modal.confirm({
      title: `清空 ${ids.length} 份文件的负责人`,
      content: `将把已选 ${ids.length} 份文件全部置为「未分配」：${names.join('、')}。` +
        '这些文件已提交待发布核对的固定快照将作废、内容解冻（历史操作记录保留）。',
      okText: '确认清空',
      onOk: () => store.batchAssignFiles(ids, null, '')
        .then(() => {
          message.success(`已清空 ${ids.length} 份文件的负责人`);
          this.setState({selectedKeys: []});
        }),
    });
  };

  /** 提交/重新提交待发布核对（仅文件有效负责人本人）：服务端会创建独立
   *  不可变快照并冻结该文件内容，发布人预览/下载/最终发布读同一快照。
   *  成功提示只在后端真实成功后出现，随后刷新详情清单（服务端权威数据）；
   *  菜单红点在 store 方法内刷新（不做乐观更新） */
  handleSubmitCompile = (file, actionLabel) => {
    const label = actionLabel || '提交待发布核对';
    const revision = file.draft ? file.draft.revision : null;
    Modal.confirm({
      title: `${label}：${file.name}`,
      content: (
        <div>
          <p>确认提交该文件待发布核对？</p>
          <p style={{color: '#888'}}>
            提交将创建该文件固定不可变内容快照（记录当前草稿修订号
            {revision != null ? ` r${revision}` : ' -'} 与提交时间），并冻结该文件
            内容：本轮不能开始/继续编辑、改名、调整顺序、移除或改派分工。
            发布人核对固定快照后，整套发布将使用该快照内容（不再读取当前草稿）；
            提交有效期间不能重复提交，可「撤回提交」后修改，或由发布人「退回修改」。
          </p>
        </div>
      ),
      okText: '确认提交',
      onOk: () => store.submitCompile(file.id)
        .then(() => {
          message.success('已提交待发布核对，等待发布人核对固定快照');
          // 后端真实成功后刷新详情清单（快照/冻结状态以服务端为准）与
          // 菜单红点（待核对快照数属红点口径，事件驱动、禁轮询）
          store.fetchFiles(store.id);
          institutionBadge.fetch();
        }),
    });
  };

  /** 撤回提交待发布核对（仅文件有效负责人本人）：撤回后旧快照作废、
   *  内容解冻，可修改后按新规则重新提交；发布人将不能使用该快照 */
  handleWithdrawSubmission = (file) => {
    Modal.confirm({
      title: `撤回提交：${file.name}`,
      content: '撤回后该文件已提交的固定快照作废、内容解冻，你可以继续修改并按新规则重新提交；发布人将不能再使用该快照核对与发布。',
      okText: '确认撤回',
      onOk: () => store.withdrawSubmission(file.id)
        .then(() => {
          message.success('已撤回提交，可继续修改该文件');
          store.fetchFiles(store.id);
        }),
    });
  };

  /** 退回修改（持发布权且非该文件有效负责人）：退回原因必填（≤500），
   *  退回后旧快照作废、内容解冻，负责人修改后可重新提交待发布核对 */
  handleReturnSubmission = (file) => {
    let reason = '';
    Modal.confirm({
      title: `退回修改：${file.name}`,
      content: (
        <div>
          <p>退回后该文件已提交的固定快照作废、内容解冻，负责人修改后可重新提交待发布核对。</p>
          <textarea id="institution-return-reason" rows={3} maxLength={500}
            style={{width: '100%'}}
            placeholder="请填写退回原因（必填，最多 500 字）"
            onChange={e => { reason = e.target.value; }}/>
        </div>
      ),
      okText: '确认退回',
      okType: 'danger',
      onOk: () => {
        const trimmed = String(reason || '').trim();
        if (!trimmed) {
          message.warning('请填写退回原因');
          return Promise.reject();
        }
        if (trimmed.length > 500) {
          message.warning('退回原因不能超过 500 字');
          return Promise.reject();
        }
        return store.returnSubmission(file.id, trimmed)
          .then(() => {
            message.success('已退回修改，等待负责人重新提交待发布核对');
            store.fetchFiles(store.id);
          });
      },
    });
  };

  /** 状态列：服务端内容关系 + 修订进行中 合并的日常短语 */
  renderStateCell(file, relation) {
    const state = buildFileState(file, relation);
    if (!state) {
      // 状态未加载/加载失败：显示占位，绝不显示"一致/无变化"
      return <span style={{color: '#999'}}>—</span>;
    }
    const renamed = relation && relation.renamed;
    return (
      <span>
        <Tooltip title={state.tip}>
          <Tag color={state.color}>{state.label}</Tag>
        </Tooltip>
        {renamed && (
          <Tooltip title={`生效版本中的名称为「${relation.current_name}」，改名尚未发布`}>
            <Tag color="orange">已改名</Tag>
          </Tooltip>
        )}
      </span>
    );
  }

  /** 生效视图行操作：预览/下载（发布快照，注明版本来源）+ 文件历史；
   *  已清理快照只显示元数据 Tag */
  renderEffectiveRowActions(row, cf) {
    const isCleaned = !!(row.snap && row.snap.is_cleaned);
    return (
      <span>
        {isCleaned && (
          <Tooltip title="该文件快照已按保留策略清理，仅存清单与哈希元数据">
            <Tag color="default">已清理</Tag>
          </Tooltip>
        )}
        {!isCleaned && this.renderSnapshotActions(row.snap, cf)}
        <AuthButton type="link" size="small"
          onClick={() => this.openFileHistory(
            row.snap.manual_file_id, row.snap.file_name)}>
          文件历史
        </AuthButton>
      </span>
    );
  }

  /** 草稿视图行操作（2026-11-03 固定快照交接）：
   *  - 未冻结文件：开始修订/继续编辑 + 预览/下载当前草稿（负责人独占：
   *    编制授权 + 该文件负责人；手册所有者可编辑任意文件，后端
   *    can_edit_file 同口径；非负责人只给占位提示）；
   *  - **冻结文件（有效提交固定快照）**：不渲染任何编辑/改结构入口，改为
   *    「预览待核对快照」「下载待核对快照」（读同一份不可变快照）；
   *  - 提交/撤回/退回入口见 renderSubmissionActions；
   *  - 两种状态都保留「文件历史」（按 file_id 打开弹窗）。 */
  renderDraftRowActions(row, canEdit, manualActive, canPublish) {
    const file = row.file;
    const isOwner = !!(store.manual && store.manual.is_owner);
    const frozen = isFrozenSubmission(file);
    // 负责人独占编辑：can_edit 授权 且 该文件负责人；手册所有者例外
    // （可编辑该手册任意文件，后端 can_edit_file 同口径）；非负责人
    // 不渲染，避免点开必然被拒的入口。冻结文件一律不渲染编辑入口
    // （后端内容写路径/结构写路径同样拒绝）
    const isAssignee = !frozen &&
      (isOwner || !!(canEdit && file.assignment && file.assignment.is_mine));
    const editEntry = (label, onClick, extra) => (isOwner ? (
      // 所有者对象级豁免：不要求 draft_edit 页面权限码（规则：所有者
      // 不需要再获得角色权限；后端 manual_auth 同口径）
      <Button type="link" size="small" onClick={onClick} {...extra}>{label}</Button>
    ) : (
      <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
        onClick={onClick} {...extra}>{label}</AuthButton>
    ));
    return (
      <span>
        {isAssignee && manualActive && (
          file.revision_open ? (
            // 修订进行中：直接复用现有工作副本（绝不覆盖），不调状态接口
            editEntry('继续编辑',
              () => history.push(
                `/institution/manuals/${store.id}/draft?file=${file.id}`))
          ) : (
            // 已结束修订的开始修订是真实状态动作：先开启修订再进入工作台
            editEntry('开始修订', () => this.handleStartRevision(file))
          )
        )}
        {!frozen && canEdit && !isOwner && manualActive && !isAssignee && (
          <Tooltip title="编辑仅限文件负责人（须持本手册编制资格）。你持编制授权但不是该文件负责人，请先由手册所有者指派分工。">
            <span style={{color: '#999', fontSize: 12}}>编辑限负责人</span>
          </Tooltip>
        )}
        {manualActive && this.renderSubmissionActions(file, canPublish)}
        {manualActive && (frozen
          ? this.renderSubmissionSnapshotActions(file)
          : (isAssignee ? this.renderDraftFileActions(file) : null))}
        <AuthButton type="link" size="small"
          onClick={() => this.openFileHistory(file.id, file.name)}>
          文件历史
        </AuthButton>
      </span>
    );
  }

  /** 提交待发布核对 / 撤回提交 / 退回修改入口（2026-11-03 固定快照交接）：
   *  - 「提交待发布核对」/「重新提交」**仅对 assignment.is_effective_owner
   *    渲染**（手册所有者非该文件有效负责人不得代提交，后端同口径）；
   *    提交后服务端创建独立不可变快照并冻结内容；
   *  - pending（有效快照）显示不可点击「待发布人核对」（不能重复提交），
   *    有效负责人本人可「撤回提交」；有发布权且非该文件有效负责人可
   *    「退回修改」（原因必填 ≤500）；
   *  - 该文件有活跃编辑会话时禁用提交并提示先「保存并结束编辑」（后端亦拒绝）；
   *  - 有效负责人兼发布权时 Tooltip 说明可直接纳入整套发布、提交只是可选动作。 */
  renderSubmissionActions(file, canPublish) {
    const manual = store.manual || {};
    const status = submissionStatusOf(submissionOf(file));
    const isEffectiveOwner = isEffectiveOwnerOf(file);
    const stale = submissionIsStale(file);
    if (status === SUBMISSION_STATUS.PENDING && !stale) {
      return (
        <span>
          <Tooltip title="该文件已提交待发布核对：固定不可变快照有效期间不能重复提交（内容已冻结）。发布人核对快照后整套发布将使用该快照内容">
            <span><Button type="link" size="small" disabled>待发布人核对</Button></span>
          </Tooltip>
          {canWithdrawSubmission(file) && (
            <Button type="link" size="small" danger
              onClick={() => this.handleWithdrawSubmission(file)}>
              撤回提交
            </Button>
          )}
          {canReturnSubmission(file, manual) && (
            <Tooltip title="退回后该文件快照作废、内容解冻，负责人可修改后重新提交；必须填写退回原因（≤500 字）">
              <Button type="link" size="small"
                onClick={() => this.handleReturnSubmission(file)}>
                退回修改
              </Button>
            </Tooltip>
          )}
        </span>
      );
    }
    if (!isEffectiveOwner) return null;
    // 已发布且无待发布修改（revision_open=false）的文件没有需要交接的草稿：
    // 不渲染必然无意义、且会与同行「无需提交」Tag 冲突的入口（stale 兜底可重提）
    if (!file.revision_open) return null;
    const label = stale ? '重新提交' : '提交待发布核对';
    const activeSession = !!file.active_session;
    let tip = '提交会为该文件创建固定不可变快照并冻结内容，等待发布人核对；' +
      '发布人核对快照后整套发布将使用该快照内容（不再读取当前草稿）';
    if (activeSession) {
      tip = '该文件有进行中的编辑会话，请先「保存并结束编辑」后再提交待发布核对';
    } else if (canPublish) {
      tip = '你是该文件有效负责人且具备发布权：本人发布时可直接纳入整套发布并' +
        '使用当前草稿；提交待发布核对只是交给其他发布人核对固定快照的可选动作';
    }
    return (
      <Tooltip title={tip}>
        {/* disabled 的原生按钮不派发鼠标事件，须用 span 包裹让提示可达 */}
        <span>
          <Button type="link" size="small" disabled={activeSession}
            onClick={() => this.handleSubmitCompile(file, label)}>
            {label}
          </Button>
        </span>
      </Tooltip>
    );
  }

  /** 负责人单元格：展示**有效负责人**（文件负责人 > 手册所有者默认 >
   *  未分配）。`owner_assigned=false` 时后缀「（手册所有者，默认）」；只有
   *  有效负责人为空时才显示「未分配」。有分工权限且文件未冻结时可点击打开
   *  分工弹窗；冻结文件（有效提交快照）禁改分工，只读展示。 */
  renderOwnerCell(assignment, canAssign, file) {
    const ownerId = effectiveOwnerIdOf(file);
    const frozen = isFrozenSubmission(file);
    const canEditAssignment = canAssign && !frozen;
    if (ownerId == null || ownerId === '') {
      return canEditAssignment ? (
        <a onClick={() => this.setState({assignmentFile: file})}
          title="点击指定负责人">未分配</a>
      ) : <Tag>未分配</Tag>;
    }
    const name = effectiveOwnerNameOf(file) || '-';
    const isDefault = ownerIsDefaultAssignment(file);
    const note = assignment && assignment.note;
    const body = (
      <span>
        {note ? (
          <Tooltip title={`分工说明：${note}${frozen ? '' : '（点击修改分工）'}`}>
            <span>{name}</span>
          </Tooltip>
        ) : <span>{name}</span>}
        {isDefault && (
          <span style={{color: '#888'}}>（手册所有者，默认）</span>
        )}
      </span>
    );
    if (!canEditAssignment) return body;
    return (
      <a onClick={() => this.setState({assignmentFile: file})}
        title="点击修改分工">{body}</a>
    );
  }

  /** 编制状态单元格（2026-11-03 固定快照交接，唯一渲染依据=
   *  compilationStatusShared.buildCompilationState）：
   *  - 主 Tag 映射 待发布人核对/可直接纳入整套发布/待提交待发布核对/
   *    待负责人提交待发布核对/已撤回/已退回/提交已失效/旧版提交记录/
   *    编制中/无需提交（服务端快照状态 + draft-status 关系 + revision_open
   *    + 编辑占用，前端只映射不推断）；
   *  - 次要信息=最后保存时间（服务端草稿 last_saved_at），草稿变更后即刷新，
   *    回调未落盘时绝不显示"已保存"；
   *  - 草稿修订号 rN 只出现在 Tooltip 内部辅助信息中，不再作为列值；
   *  - 冻结文件附加「已冻结」Tag（内容已冻结，不能编辑/改结构/重复提交）。 */
  renderCompilationCell(file, relation, canPublish) {
    const state = buildCompilationState(file, relation, {canPublish});
    const draft = file.draft;
    const savedText = draft
      ? (draft.last_saved_at
        ? `最后保存 ${formatDateTime(draft.last_saved_at)}`
        : '尚无保存记录')
      : '无草稿';
    const tipParts = [state.tip];
    if (draft && draft.revision != null) {
      tipParts.push(`当前草稿 r${draft.revision}`);
    }
    const ownerName = effectiveOwnerNameOf(file);
    if (effectiveOwnerIdOf(file) != null && effectiveOwnerIdOf(file) !== '') {
      tipParts.push(`有效负责人 ${ownerName || '-'}` +
        (ownerIsDefaultAssignment(file) ? '（手册所有者，默认）' : ''));
    } else {
      tipParts.push('有效负责人 未分配');
    }
    if (isFrozenSubmission(file)) {
      tipParts.push('已冻结：内容/结构写路径与再次提交均被拒绝，需撤回提交或由发布人退回');
    }
    return (
      <span>
        <Tooltip title={tipParts.join('；')}>
          <Tag color={state.color}>{state.label}</Tag>
        </Tooltip>
        {isFrozenSubmission(file) && (
          <Tooltip title="该文件已提交待发布核对：内容已冻结，发布人核对固定快照后整套发布使用该快照">
            <Tag color="blue">已冻结</Tag>
          </Tooltip>
        )}
        <div style={{color: '#999', fontSize: 12, lineHeight: '16px'}}>
          {savedText}
        </div>
      </span>
    );
  }

  /** 旧章节分工记录（遗留只读，2026-10-29 起由文件分工替代）：
   *  仅在存在历史记录时过渡展示，供人工核对后改为文件分工；
   *  写接口已关闭，记录在人工核对完成前保留。 */
  renderLegacyChapters() {
    const chapters = store.chapters || [];
    if (!chapters.length) return null;
    return (
      <div style={{marginTop: 16}}>
        <Alert type="warning" showIcon style={{marginBottom: 8}} message={
          <span>
            以下为历史「章节分工」记录（{chapters.length} 条，未与具体文件关联），
            仅供查阅与人工核对。分工已改为按整份文件指定负责人（点击上方清单
            负责人列即可修改），请核对后为对应文件重新指定负责人；旧记录在
            人工核对完成前保留，不再支持新增或修改。
          </span>}/>
        <Table rowKey="id" size="small" dataSource={chapters}
          loading={store.isFetchingChapters} pagination={false}>
          <Table.Column title="章节/部分" dataIndex="title"/>
          <Table.Column title="负责人" width={130}
            render={(_, c) => c.owner_name || '-'}/>
          <Table.Column title="参与说明" dataIndex="note" ellipsis/>
          <Table.Column title="进度" dataIndex="progress_display" width={90}/>
          <Table.Column title="提交时间" dataIndex="submitted_at" width={150}
            render={v => formatDateTime(v)}/>
          <Table.Column title="更新时间" dataIndex="updated_at" width={150}
            render={v => formatDateTime(v)}/>
        </Table>
      </div>
    );
  }

  /** 生效视图行：版本快照为行（不可变发布内容，含已移除文件条目的快照）。
   *  工作区可见者以 draft-status.removed_items 标注"已从待发布移除"。
   *  assignment 仍随行关联（负责人列已不展示），供「只看我负责的文件」
   *  筛选使用，不得移除。 */
  buildEffectiveRows(cf) {
    const removedByFileId = {};
    if (store.draftStatus && Array.isArray(store.draftStatus.removed_items)) {
      store.draftStatus.removed_items.forEach(
        r => { removedByFileId[r.file_id] = r; });
    }
    const assignmentByFileId = {};
    (store.files || []).forEach(
      f => { assignmentByFileId[f.id] = f.assignment || null; });
    const items = (cf && Array.isArray(cf.items)) ? cf.items : [];
    return items.map(s => ({
      kind: 'snapshot', key: `s-${s.id}`, snap: s,
      assignment: assignmentByFileId[s.manual_file_id] || null,
      removedFromDraft: !!removedByFileId[s.manual_file_id],
    }));
  }

  /** 草稿视图行：待发布集合为行（含未进入生效版本的新增文件），内嵌
   *  生效快照（大小展示兜底）与逐份内容关系 */
  buildDraftRows() {
    const snapByFileId = {};
    const cf = store.currentFiles;
    if (cf && Array.isArray(cf.items)) {
      cf.items.forEach(s => { snapByFileId[s.manual_file_id] = s; });
    }
    const relationByFileId = {};
    if (store.draftStatus && Array.isArray(store.draftStatus.items)) {
      store.draftStatus.items.forEach(x => { relationByFileId[x.file_id] = x; });
    }
    return (store.files || []).map(f => ({
      kind: 'active', key: `f-${f.id}`, file: f,
      snap: snapByFileId[f.id], relation: relationByFileId[f.id],
    }));
  }

  /** 勾选行键（f-<id>）→ 当前有效的制度文件 ID 列表（仅活动行可勾选） */
  batchFileIds() {
    return this.state.selectedKeys
      .filter(k => typeof k === 'string' && k.startsWith('f-'))
      .map(k => Number(k.slice(2)));
  }

  renderBatchBar(rows) {
    const ids = this.batchFileIds();
    if (!ids.length) return null;
    const names = (store.files || [])
      .filter(f => ids.includes(f.id)).map(f => f.name);
    return (
      <Alert style={{marginBottom: 8}} type="info" showIcon message={
        <span>
          已选 {ids.length} 份文件：{names.join('、')}。
          批量操作将统一应用到所选文件（整体生效）。
          <Button type="link" size="small"
            onClick={() => this.setState({batchAssign: true})}>批量指定负责人</Button>
          <Button type="link" size="small" danger
            onClick={this.handleBatchClear}>清空负责人</Button>
          <Button type="link" size="small"
            onClick={() => this.setState({selectedKeys: []})}>清除选择</Button>
        </span>}/>
    );
  }

  /** 生效视图表格：顺序/文件名/大小/操作（预览/下载均打开
   *  当前生效版本发布快照并注明版本来源）；不展示负责人——
   *  负责人属修订分工，只在「修订草稿」视图的负责人列展示与维护 */
  renderEffectiveTable(rows, {cf, workspace}) {
    return (
      <Table rowKey="key" size="small" scroll={{x: true}}
        loading={store.isFetchingCurrentFiles}
        dataSource={rows} pagination={false}>
        <Table.Column title="顺序" width={55}
          render={(_, r, i) => i + 1}/>
        <Table.Column title="文件名" ellipsis
          render={(_, r) => (
            <span>
              {r.snap.file_name}
              {workspace && r.removedFromDraft && (
                <Tooltip title="该文件已从待发布集合移除，发布新版本后将不在本制度中；可通过整套回退重新纳入">
                  <Tag color="orange" style={{marginLeft: 8}}>已从待发布移除</Tag>
                </Tooltip>
              )}
            </span>
          )}/>
        <Table.Column title="大小" width={85}
          render={(_, r) => formatSize(r.snap.file_size)}/>
        <Table.Column title="操作" width={290} fixed="right"
          render={(_, r) => this.renderEffectiveRowActions(r, cf)}/>
      </Table>
    );
  }

  /** 草稿视图表格：顺序/文件名/大小/负责人/状态/编制状态/操作。
   *  预览与下载打开**当前**待发布草稿（仅编制角色）；冻结文件改读待核对
   *  快照。2026-11-03 固定快照交接：编制状态列合并提交快照状态与冻结提示，
   *  rN 只出现在 Tooltip 内部；冻结行不可勾选（内容/结构写路径已被拒绝）。 */
  renderDraftTable(rows, {canEdit, canAssign, canPublish, manualActive}) {
    const rowSelection = canAssign ? {
      selectedRowKeys: this.state.selectedKeys,
      onChange: keys => this.setState({selectedKeys: keys}),
      // 冻结文件（有效提交固定快照）不参与批量分工：后端结构写路径拒绝，
      // 前端不得提供必然被拒的批量入口
      getCheckboxProps: record => ({
        disabled: !!(record.file && isFrozenSubmission(record.file)),
      }),
    } : null;
    return (
      <Table rowKey="key" size="small" scroll={{x: true}}
        rowSelection={rowSelection}
        loading={store.isFetchingFiles}
        dataSource={rows} pagination={false}>
        <Table.Column title="顺序" width={55}
          render={(_, r, i) => i + 1}/>
        <Table.Column title="文件名" ellipsis
          render={(_, r) => (
            <span title={r.file.name}>
              {r.file.name}
              {isFrozenSubmission(r.file) && (
                <Tooltip title="该文件已提交待发布核对并冻结内容：不能开始/继续编辑、改名、调整顺序、移除或改派分工；需负责人撤回提交或发布人退回修改">
                  <Tag color="blue" style={{marginLeft: 8}}>待核对快照</Tag>
                </Tooltip>
              )}
            </span>
          )}/>
        <Table.Column title="大小" width={85}
          render={(_, r) => {
            const snapSize = r.snap && r.snap.file_size;
            return formatSize(snapSize != null
              ? snapSize : (r.file.draft && r.file.draft.file_size));
          }}/>
        <Table.Column title={
          <Tooltip title="负责人=有效负责人：文件负责人，未单独指派时为手册所有者（默认）；负责人是当前责任归属，负责人独占编辑（须持本手册编制资格），同一文件同一时间仅一人可编辑（单写会话）。点击姓名可修改分工（仅所有者/制度管理员；已提交待发布核对的冻结文件不可改派）。">
            <span>负责人</span>
          </Tooltip>
        } width={150}
          render={(_, r) => this.renderOwnerCell(
            r.file.assignment, canAssign, r.file)}/>
        <Table.Column title="状态" width={190}
          render={(_, r) => this.renderStateCell(r.file, r.relation)}/>
        <Table.Column title={
          <Tooltip title="编制状态是提交待发布核对的固定快照状态（待发布人核对/可直接纳入整套发布/待提交待发布核对/待负责人提交待发布核对/已撤回/已退回/提交已失效/旧版提交记录/编制中/无需提交）。提交会创建固定不可变快照并冻结内容，发布人核对快照后整套发布使用该快照。">
            <span>编制状态</span>
          </Tooltip>
        } width={220}
          render={(_, r) => this.renderCompilationCell(
            r.file, r.relation, canPublish)}/>
        <Table.Column title="操作" width={520} fixed="right"
          render={(_, r) => this.renderDraftRowActions(
            r, canEdit, manualActive, canPublish)}/>
      </Table>
    );
  }

  /** 生效视图：不可变发布快照清单。预览/下载始终打开发布快照，
   *  入口按钮与预览标题注明版本来源；头部保留版本信息与废止入口 */
  renderEffectiveView({manual, current, cf, workspace, viewPublished,
    manualActive, rows}) {
    const removedCount = (store.draftStatus &&
      store.draftStatus.removed_items || []).length;
    return (
      <div>
        <div style={{marginBottom: 8, color: '#666', fontSize: 12}}>
          {workspace
            ? '当前生效版本是最近一次发布形成的不可变清单：本视图的预览与下载始终打开该发布快照，不受草稿修改影响。修订中的待发布内容（含各文件负责人、修订状态、编制状态）请切换到「修订草稿」视图；新增文件请在「修订草稿」视图顶部使用「新增待发布文件」；各文件的发布参与与操作记录可经行内「文件历史」查阅。'
            : '当前生效版本是最新一次发布形成的完整清单（不可变）：预览与下载始终打开该发布快照。各文件的发布参与与操作记录可经行内「文件历史」查阅。'}
        </div>
        {viewPublished && current && (
          <div style={{marginBottom: 12, padding: '12px 16px',
            background: '#fafafa', border: '1px solid #f0f0f0'}}>
            <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8}}>
              <strong>当前生效版本：</strong>
              <Tag color="green">v{current.version_no}</Tag>
              {formatDateTime(current.published_at)} · {current.published_by_name}
              {canPublishVisible(manual) && manualActive && (
                <AuthButton auth="institution.manual.publish" type="link" size="small" danger
                  onClick={this.handleDeprecate}>废止</AuthButton>
              )}
            </div>
            {cf && cf.change_note && (
              <div style={{marginTop: 4, color: '#666'}}>变更说明：{cf.change_note}</div>
            )}
            {store.currentFilesError && (
              <Alert type="error" showIcon style={{marginTop: 8}}
                message={store.currentFilesError}
                action={<Button size="small" type="primary" onClick={() =>
                  store.fetchCurrentFiles(store.id, current.id)}>重试</Button>}/>
            )}
          </div>
        )}
        {viewPublished && !current && (
          <Alert type="info" showIcon style={{marginBottom: 12}}
            message="该制度暂无生效版本。已发布的版本废止后此处为空；当前编辑内容见「修订草稿」视图，发布后在「版本与发布」生成新的生效版本。"/>
        )}
        {workspace && removedCount > 0 && (
          <Alert type="warning" showIcon style={{marginBottom: 8}}
            message={`${removedCount} 份文件已从待发布集合移除（行内标「已从待发布移除」），仍保留在当前生效版本中，发布新版本后将不再包含；可通过整套回退重新纳入。`}/>
        )}
        {rows.length > 0 && this.renderEffectiveTable(rows, {cf, workspace})}
      </div>
    );
  }

  /** 「新增制度文件」入口（草稿视图顶部；0 文件时同样可见）。
   *  隐藏 input 由 ref 程序触发（禁止把 input 嵌套在 Button/label 内）；
   *  选择文件后先弹分工弹窗（默认负责人=手册所有者，可改选/清空），确认后
   *  才逐份创建；业务门=手册所有者或制度管理员（与后端 files/create 一致），
   *  无权限只给只读说明，不渲染必然被拒的入口。 */
  renderUploadEntry() {
    const manual = store.manual || {};
    const canManageFiles = !!(manual.is_owner || manual.is_admin);
    if (!canManageFiles) {
      return (
        <div style={{marginBottom: 8}}>
          <span style={{color: '#999', fontSize: 12}}>
            新增待发布文件仅限手册所有者或制度管理员；当前账号只读，不能上传。
          </span>
        </div>
      );
    }
    return (
      <div style={{marginBottom: 8, display: 'flex', alignItems: 'center',
        flexWrap: 'wrap', gap: 8}}>
        <input ref={el => { this.uploadInput = el; }} type="file"
          accept=".doc,.docx" multiple style={{display: 'none'}}
          onChange={this.handleUploadChange}/>
        <ManualAuthButton manual={manual} auth="institution.manual.upload"
          type="primary" size="small"
          loading={this.state.uploading}
          disabled={!canManageFiles}
          onClick={this.handleUploadClick}>
          新增待发布文件（.doc/.docx，可多选）
        </ManualAuthButton>
      </div>
    );
  }

  /** 草稿视图：待发布工作内容（尚未生效）。负责人/状态/编制状态集中呈现；
   *  预览与下载明确打开**当前**待发布草稿（负责人独占域），rN 只出现在
   *  Tooltip 等内部说明中 */
  renderDraftView({canEdit, canAssign, canPublish, manualActive, rows}) {
    return (
      <div>
        {this.renderUploadEntry()}
        <div style={{marginBottom: 8, color: '#666', fontSize: 12}}>
          本视图是待发布的工作内容（尚未生效）：每份上传文件
          单独加入待发布清单，上传内容直接作为该文件草稿；
          未冻结文件的预览与下载打开当前草稿，已提交待发布核对的文件
          改为预览/下载待核对固定快照。
          上传的文件经整套发布后才会成为新的生效版本；
          移除文件只让该文件退出待发布清单，发布后才影响新版本
          （已发布的历史版本不受影响）。
          「编制状态」是提交待发布核对的固定快照状态：提交入口仅对文件
          有效负责人（文件负责人，未单独指派时为手册所有者默认）开放；
          提交会为该文件创建固定不可变内容快照并冻结编辑，等待发布人核对，
          发布人核对后整套发布使用该快照；提交有效期间不能重复提交，负责人
          可撤回提交、发布人可退回修改（必填原因），撤回/退回后可修改并重新提交。
          有效负责人本人且具备发布权时可直接纳入整套发布（无需提交）。
          旧版提交记录不可用于发布，需按新规则重新提交待发布核对。
          负责人是当前责任归属：编辑仅限文件负责人（须持本手册编制资格），
          单写会话（同一文件同一时间仅一人）；持编制授权但未被指派负责人的
          账号可查看清单，编辑前请先由手册所有者指派分工。
          各文件的发布参与与操作记录可在行内「文件历史」查阅；新增文件请
          使用上方按钮，并先指定负责人。
        </div>
        {store.draftStatusError && (
          <Alert type="warning" showIcon style={{marginBottom: 8}}
            message="草稿与生效版本的关系加载失败，无法确认各文件是否有未发布变化"
            action={<Button size="small" type="primary"
              onClick={() => store.fetchDraftStatus(store.id)}>重试</Button>}/>
        )}
        {canAssign && this.renderBatchBar(rows)}
        {rows.length === 0 && !store.isFetchingFiles && (
          <Alert type="info" showIcon
            message="该制度还没有待发布文件。请使用上方「新增待发布文件」上传，上传文件作为待发布文件的当前草稿。"/>
        )}
        {rows.length > 0 && this.renderDraftTable(rows,
          {canEdit, canAssign, canPublish, manualActive})}
      </div>
    );
  }

  render() {
    const manual = store.manual || {};
    const viewPublished = canViewPublished(manual);
    const workspace = canViewWorkspace(manual);
    const canEdit = (manual.my_roles || []).includes('edit');
    // 分工口径与后端写接口完全一致（2026-10-31 授权模型）：@auth
    // draft_edit 页面权限 +（手册所有者或制度管理员）业务门。缺
    // draft_edit 或非所有者/管理员时保存必然被"权限拒绝"，入口必须只读
    const canAssign = hasPermission('institution.manual.draft_edit') &&
      (manual.is_owner || manual.is_admin);
    // 发布权口径（编制状态「本人发布无需提交」与提交入口 Tooltip 共用，
    // 与 PublishButton 渲染口径一致：所有者对象级豁免 或 发布授权）
    const canPublish = !!(manual.is_owner ||
      (manual.my_roles || []).includes('publish'));
    const current = manual.current_version;
    const manualActive = manual.status === 'active';
    const cf = store.currentFiles;
    const view = this.currentView(manual);

    let rows = view === VIEW_DRAFT
      ? this.buildDraftRows() : this.buildEffectiveRows(cf);
    // 「只看我负责的文件」筛选（按服务端 is_mine；两个视图都可用）。
    // 筛选切换同时清空勾选：不得对筛选后不可见的文件批量操作
    const mineCount = (store.files || []).filter(
      f => f.assignment && f.assignment.is_mine).length;
    if (this.state.onlyMine) {
      rows = rows.filter(r => r.assignment ? r.assignment.is_mine :
        (r.file && r.file.assignment && r.file.assignment.is_mine));
    }

    const viewProps = {manual, current, cf, workspace, viewPublished,
      canEdit, canAssign, canPublish, manualActive, rows};
    return (
      <div>
        {viewPublished && workspace && (
          <div style={{marginBottom: 12, display: 'flex',
            alignItems: 'center', flexWrap: 'wrap', gap: 16}}>
            <Segmented value={view} onChange={this.handleViewChange}
              options={[
                {value: VIEW_EFFECTIVE,
                  label: `当前生效版本${current ? ` v${current.version_no}` : ''}`},
                {value: VIEW_DRAFT, label: '修订草稿'},
              ]}/>
            <Checkbox checked={this.state.onlyMine}
              onChange={e => this.setState(
                {onlyMine: e.target.checked, selectedKeys: []})}>
              只看我负责的文件{mineCount > 0 ? `（${mineCount}）` : ''}
            </Checkbox>
          </div>
        )}
        {view === VIEW_DRAFT
          ? this.renderDraftView(viewProps)
          : this.renderEffectiveView(viewProps)}
        {this.renderLegacyChapters()}
        {this.state.assignmentFile && (
          <FileAssignmentModal manualId={store.id}
            file={this.state.assignmentFile}
            onClose={() => this.setState({assignmentFile: null})}
            onSubmit={this.handleAssignSubmit(this.state.assignmentFile.id)}/>
        )}
        {this.state.batchAssign && this.batchFileIds().length > 0 && (
          <FileAssignmentModal manualId={store.id}
            files={(store.files || []).filter(
              f => this.batchFileIds().includes(f.id))}
            onClose={() => this.setState({batchAssign: false})}
            onSubmit={this.handleBatchSubmit(this.batchFileIds())}/>
        )}
        {/* 新增制度文件：选文件后先指定负责人（默认手册所有者，可改选/
             清空），确认后才逐份创建；隐藏 input 已在上方由 ref 程序触发，
             本弹窗不嵌套任何 file input */}
        {this.state.uploadFiles && this.state.uploadFiles.length > 0 && (
          <FileAssignmentModal manualId={store.id}
            title={`新增待发布文件分工（${this.state.uploadFiles.length} 份）`}
            files={this.state.uploadFiles.map((f, i) => ({
              id: `upload-${i}`, name: f.name, assignment: {},
            }))}
            initialOwnerId={(store.manual || {}).owner_id}
            createMode
            onClose={() => this.setState({uploadFiles: null})}
            onSubmit={this.handleUploadAssignSubmit}/>
        )}
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          title={this.state.preview && this.state.preview.title}
          onClose={() => this.setState({preview: null})}/>
        {/* 文件历史弹窗（两种清单视图行入口共用）：按 file_id 打开，
            发布记录/操作记录在弹窗内查阅；关闭后清单视图、滚动位置与
            行勾选保持不变 */}
        <FileHistoryModal visible={this.state.historyFileId != null}
          fileId={this.state.historyFileId}
          fileName={this.state.historyFileName}
          onClose={() => this.setState({historyFileId: null})}/>
      </div>
    );
  }
}

function canPublishVisible(manual) {
  return (manual.my_roles || []).includes('publish');
}

export default FileListTab;
