/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台（2026-10-30 交互改造）：密码验证门 → 左侧文件导航 + 右侧
 * 编辑区主体；单文件制度不渲染导航，开门即编辑。
 * - 右侧顶部状态条集中展示：当前文件、修订号、独立的"制度草稿保存状态"
 *   （服务端确认落盘才显示"已保存到制度草稿：rN、时间"；ONLYOFFICE 的
 *   "所有更改已保存"只代表文档服务缓存，绝不据此显示业务已保存）与
 *   提交编制状态（未提交/已提交/提交已失效，服务端 submission.state）。
 * - 流程按钮：开始编辑 → 保存并结束编辑 → 提交编制；下载/预览/改名/
 *   排序/移除/新增为次级操作。负责人持有该文件编辑会话时提交编制禁用
 *   （明确提示先保存并结束编辑；后端仍独立校验）。
 * - 「保存并结束编辑」的真实落盘确认在 store.finishEditing：确认链路
 *   （forcesave → 轮询草稿修订号推进 → 再次 forcesave 复核到 no_changes）
 *   通过后才撤销会话并提示成功；失败或超时保留会话与编辑器并给出重试
 *   状态，绝不静默销毁在编编辑器。
 * - 切换文件/返回详情（工作台内可拦截的离开）复用同一确认链路
 *   （store.confirmFileSave：确认落盘但不撤销会话），确认成功才真正
 *   切换/跳转，失败留在当前文件并呈现原因与重试入口；确认期间禁用
 *   冲突导航与重复提交。关闭工作页签/浏览器关闭等无法拦截的离开保留
 *   beforeunload 提醒与 quiet forcesave + DS 关闭回调兜底。
 * - ?file= 深链：密码验证只针对指定且可编辑（存在、有草稿）的文件建立
 *   会话；目标不存在/无草稿时给出明确状态（deeplinkNotice），绝不静默
 *   开启另一份文件的会话；被他人占用时由后端验证拒绝并明确提示。
 * - 隐藏 input 不得嵌套在 Button/label 内（统一 ref 程序触发）。
 */
import React, {useEffect} from 'react';
import { observer } from 'mobx-react';
import {
  Spin, Card, Button, Input, Alert, Descriptions, Tag, message, Tooltip,
  Modal, Popconfirm, Select, Form, Row, Col,
} from 'antd';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { history } from 'libs';
import { AuthButton, AuthFragment } from 'components';
import { http } from 'libs';
import { downloadFile, formatSize, formatDateTime } from '../utils';
import PreviewModal from '../detail/PreviewModal';
import OnlyOfficeEditor from './OnlyOfficeEditor';
import FileNav, {submissionTagFor} from './FileNav';
import useWorkTabUnsaved from '../../../layout/useWorkTabUnsaved';
import store from './store';

const {Option} = Select;

/**
 * 未保存内容登记 + beforeunload 拦截（工作页签 LRU 淘汰配套）。
 * 任一文件持有有效编辑会话即视为可能有未保存内容：编辑器销毁后未
 * forcesave 的内容随 DS 收尾回调落盘，若此刻会话/key 已轮换则该部分
 * 内容丢失且无感知，因此宁可拦截也不静默丢弃。
 */
function DraftUnsavedGate({dirty}) {
  useWorkTabUnsaved(dirty);
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = e => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);
  return null;
}

@observer
class InstitutionDraftWorkspace extends React.Component {
  state = {
    password: '', preview: null,
    adding: false, uploading: false,
    renameFile: null, renameValue: '', renaming: false,
    // 新增文件时的可选文件分工（负责人/分工说明，2026-10-29）
    pendingFile: null, assignOwners: [], assignOwnerId: undefined,
    assignNote: '', assignOwnersError: '', fetchingOwners: false,
  };

  componentDidMount() {
    const id = this.props.match.params.id;
    // ?file=<fid> 深链（详情页"继续编辑"入口）：验证目标与选中文件都
    // 以它为准；目标不存在/无草稿由 store 给出 deeplinkNotice 明确状态
    const requestedId = Number(
      new URLSearchParams((this.props.location && this.props.location.search) || '')
        .get('file')) || null;
    store.fetchAll(id, requestedId);
  }

  componentWillUnmount() {
    // 无法拦截的离开（菜单跳转/关闭工作页签/浏览器关闭）兜底：尽力触发
    // 各在线编辑文档落盘（quiet forcesave，DS 关闭回调兜底），不等待
    // 结果、不提示；可拦截的离开（返回详情按钮/切换文件）已在触发前
    // 走 store.confirmFileSave 确认链路。会话按文件保留在 sessionStorage
    store.files.forEach(file => {
      if (store.sessionKeyOf(file.id)) store.requestForcesaveQuiet(file.id);
    });
    store.reset();
  }

  // ---------------------------------------------------------------------------
  // 密码门

  handleVerify = () => {
    if (!this.state.password) return message.warning('请输入编辑密码');
    store.verifyPassword(this.state.password)
      .then(() => {
        this.setState({password: ''});
        message.success('已进入编辑会话');
      })
      .catch(() => {});
  };

  // ---------------------------------------------------------------------------
  // 文件选择与切换保护

  /** 当前选中文件是否处于在线编辑（有会话且编辑配置可用） */
  isSelectedFileOnlineEditing() {
    const current = store.selectedFile;
    if (!current || !store.sessionKeyOf(current.id)) return false;
    const config = store.editorConfigs[current.id];
    return !!(config && config.editor_available);
  }

  handleSelectFile = (fileId) => {
    if (fileId === store.selectedFileId) return;
    if (store.finishingFileId) {
      // 保存确认进行中：禁用冲突导航（重复提交/切换会造成编辑器销毁竞态）
      message.warning('正在保存当前文件，请稍候再切换');
      return;
    }
    const current = store.selectedFile;
    if (current && this.isSelectedFileOnlineEditing()) {
      // 切换保护：复用"保存并结束编辑"的确认链路（确认落盘但不撤销
      // 会话），服务端确认后才真正切换；失败留在当前文件并呈现重试入口，
      // 绝不静默 forcesave 后销毁编辑器
      store.confirmFileSave(current.id, '切换文件').then(ok => {
        if (ok) {
          message.success(`当前文件「${current.name}」已保存到制度草稿`);
          store.selectFile(fileId);
        }
      });
      return;
    }
    store.selectFile(fileId);
  };

  /** 返回详情（工作台内可拦截的离开）：先确认落盘再跳转 */
  handleBackToDetail = () => {
    if (store.finishingFileId) {
      message.warning('正在保存当前文件，请稍候');
      return;
    }
    const go = () => history.push(`/institution/manuals/${store.id}`);
    if (this.isSelectedFileOnlineEditing()) {
      const current = store.selectedFile;
      store.confirmFileSave(current.id, '返回详情').then(ok => {
        if (ok) go();
      });
      return;
    }
    go();
  };

  // ---------------------------------------------------------------------------
  // 文件管理

  /** 选中文件后先弹分工弹窗（负责人可选），确认后才上传创建 */
  handleAddFile = (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    this.setState({pendingFile: file, assignOwners: [], assignOwnerId: undefined,
      assignNote: '', assignOwnersError: ''});
    this.fetchAssignOwners();
  };

  fetchAssignOwners() {
    // 负责人候选走制度模块专用接口（与详情页文件分工一致，权限与分工
    // 写路径匹配）；不得再拉账号管理列表 /api/account/user/（要求
    // system.account.view，无账号查看权即"权限拒绝"，2026-10-30 修正）。
    // 失败在弹窗内展示错误与重试（skipErrorNotification 避免拦截器重复
    // 弹窗），绝不把失败静默表现为空候选列表。
    this.setState({fetchingOwners: true, assignOwnersError: ''});
    http.get(
      `/api/institution/manuals/${store.id}/assignment-owners/`,
      {skipErrorNotification: true})
      .then(data => {
        const items = Array.isArray(data) ? data : [];
        this.setState({assignOwners: items, assignOwnersError: ''});
      })
      .catch(err => {
        this.setState({assignOwnersError:
          typeof err === 'string' && err ? err : '负责人候选加载失败'});
      })
      .finally(() => this.setState({fetchingOwners: false}));
  }

  handleConfirmAddFile = () => {
    const file = this.state.pendingFile;
    if (!file) return;
    this.setState({adding: true});
    store.createFile(file, this.state.assignOwnerId,
      (this.state.assignNote || '').trim())
      .then(data => {
        if (data && data.draft_error) {
          // 文件已创建但草稿未就绪（如 .doc 转换失败）：警示不算失败
          message.warning(data.draft_error);
        } else {
          message.success('文件已新增');
        }
        this.setState({pendingFile: null});
      })
      .catch(() => {})
      .finally(() => this.setState({adding: false}));
  };

  handlePickAddFile = () => {
    if (this.addFileInput) this.addFileInput.click();
  };

  /** 提交编制（负责人完成编制后的交接标记；与详情页文件清单同一接口） */
  handleSubmitCompile = (file) => {
    const revision = file.draft ? file.draft.revision : null;
    Modal.confirm({
      title: `提交编制：${file.name}`,
      content: (
        <div>
          <p>确认该文件已完成编制并提交核对？</p>
          <p style={{color: '#888'}}>
            将记录当前草稿修订号 {revision != null ? `r${revision}` : '-'} 与提交时间；
            此后草稿再次保存或重建，提交状态会自动失效，需重新提交。
          </p>
        </div>
      ),
      okText: '确认提交',
      onOk: () => http.post(
        `/api/institution/manuals/${store.id}/files/${file.id}/submit/`, {})
        .then(() => {
          message.success('已提交编制，等待发布核对');
          return store.refreshFiles().catch(() => {});
        }),
    });
  };

  showRename = () => {
    const file = store.selectedFile;
    if (file) this.setState({renameFile: file, renameValue: file.name});
  };

  handleRename = () => {
    const name = this.state.renameValue.trim();
    if (!name) return message.warning('请输入文件名');
    this.setState({renaming: true});
    store.renameFile(this.state.renameFile.id, name)
      .then(() => {
        message.success('已改名');
        this.setState({renameFile: null, renameValue: ''});
      })
      .catch(() => {})
      .finally(() => this.setState({renaming: false}));
  };

  handleMove = (file, delta) => {
    const idx = store.files.findIndex(f => f.id === file.id);
    const target = idx + delta + 1; // 1 起目标序位
    if (target < 1 || target > store.files.length) return;
    store.moveFile(file.id, target)
      .then(() => message.success('已调整顺序'))
      .catch(() => {});
  };

  handleRemove = (file) => {
    store.removeFile(file.id)
      .then(() => message.success('已移除文件'))
      .catch(() => {});
  };

  // ---------------------------------------------------------------------------
  // 会话与草稿（按选中文件）

  handleStartSession = (fileId) => {
    store.startFileSession(fileId)
      .then(() => message.success('编辑会话已开启'))
      .catch(() => {});
  };

  /** 保存并结束编辑：成功提示只出现在服务端确认落盘并撤销会话之后 */
  handleSaveFinish = () => {
    const file = store.selectedFile;
    if (!file) return;
    store.finishEditing(file.id).then(ok => {
      if (ok) message.success('已保存并结束编辑');
    });
  };

  /** 保存确认反复失败时的出口：明确告知可能丢失，绝不冒充已保存 */
  showDiscardExit = () => {
    const file = store.selectedFile;
    if (!file) return;
    Modal.confirm({
      title: '不保存并退出编辑会话？',
      content: (
        <div>
          <p>服务端尚未确认当前内容已落盘。退出后本页编辑器将关闭，
            未落盘的内容可能丢失。</p>
        </div>
      ),
      okText: '不保存并退出',
      okType: 'danger',
      onOk: () => store.exitFileSession(file.id)
        .then(() => message.success('已退出编辑会话'))
        .catch(() => {}),
    });
  };

  handleSaveUpload = (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.docx')) {
      message.error('草稿工作文件必须是 .docx 格式');
      return;
    }
    const fileId = store.selectedFileId;
    this.setState({uploading: true});
    store.saveDraft(fileId, file)
      .then(() => {
        message.success('草稿已保存（修订序号已递增）');
        return store.refreshFiles();
      })
      .catch(() => {})
      .finally(() => this.setState({uploading: false}));
  };

  handlePickSaveFile = () => {
    if (this.saveFileInput) this.saveFileInput.click();
  };

  handleRefreshRevision = () => {
    // 失败不弹成功（拦截器已提示过一次），只有真实成功才提示
    store.refreshFiles()
      .then(() => message.success('已刷新草稿状态'))
      .catch(() => {});
  };

  handlePreview = (file) => {
    http.get(`/api/institution/manuals/${store.id}/files/${file.id}/draft/preview-url/`)
      .then(data => this.setState({preview: {url: data.preview_url, fileName: data.file_name}}));
  };

  // ---------------------------------------------------------------------------
  // 草稿恢复（无草稿文件；恢复途径以 files 清单 draft_recovery 为准）

  /** 默认恢复：后端按优先级从当前生效版本快照或初始原稿建立草稿 */
  handleRecoverDraft = () => {
    const file = store.selectedFile;
    if (!file) return;
    store.recoverDraft(file.id)
      .then(data => {
        const revision = data && data.revision != null ? data.revision : '';
        const source = data && data.base_version_no != null
          ? `来源版本 v${data.base_version_no}`
          : '来源：初始原稿';
        message.success(`草稿已恢复（修订号 r${revision}，${source}）`);
      })
      .catch(() => {});
  };

  /** 高级恢复：明确「从原始上传文件重建草稿」，高风险确认后执行 */
  showAdvancedRecovery = () => {
    const file = store.selectedFile;
    if (!file) return;
    store.fetchFileOriginals(file.id).then(originals => {
      const latest = originals && originals[0];
      if (!latest) {
        message.warning('该文件没有可用的原始上传文件，请先在详情页上传原稿');
        return;
      }
      Modal.confirm({
        title: '从原始上传文件重建草稿（高级恢复）',
        content: (
          <div>
            <p>
              将以原始上传文件「{latest.file_name}」的副本重建该文件草稿，
              不可撤销。
            </p>
            <p style={{color: '#f5222d'}}>
              该制度已发布过版本，此操作以原始文件（而非当前生效版本）为编辑基线，
              仅在当前生效版本不含该文件或管理员明确要求从原始文件重新开始时使用。
            </p>
          </div>
        ),
        okText: '确认重建',
        onOk: () => store.rebuildDraftFromOriginal(
            file.id, latest.id, store.verifiedPassword || undefined)
          .then(data => {
            const revision = data && data.revision != null ? data.revision : '';
            message.success(`草稿已按原始上传文件重建（修订号 r${revision}）`);
          }),
      });
    }).catch(() => {});
  };

  /** 无草稿文件的恢复面板（途径由服务端 draft_recovery 提示决定） */
  renderRecoveryPanel(file) {
    const hint = file.draft_recovery || {source: 'original'};
    if (hint.source === 'current_version') {
      return (
        <Alert type="warning" showIcon style={{marginTop: 12}} message={
          <div>
            <div style={{marginBottom: 8}}>
              该文件还没有草稿。当前生效版本为 v{hint.version_no}，
              可从该版本的完整文件快照恢复草稿。
            </div>
            <AuthButton auth="institution.manual.draft_edit" type="primary" size="small"
              onClick={this.handleRecoverDraft}>
              从当前生效版本恢复草稿
            </AuthButton>
          </div>}/>
      );
    }
    if (hint.requires_confirm) {
      return (
        <Alert type="warning" showIcon style={{marginTop: 12}} message={
          <div>
            <div style={{marginBottom: 8}}>
              该文件还没有草稿，且{hint.note || '当前生效版本不包含该文件'}；
              不能自动从原始上传文件补建，如确认需要请执行高级恢复操作。
            </div>
            <Button danger size="small" onClick={this.showAdvancedRecovery}>
              从原始上传文件重建草稿（高级恢复）
            </Button>
          </div>}/>
      );
    }
    return (
      <Alert type="warning" showIcon style={{marginTop: 12}} message={
        <div>
          <div style={{marginBottom: 8}}>
            该文件还没有草稿，可从初始原稿创建草稿。
          </div>
          <AuthButton auth="institution.manual.draft_edit" type="primary" size="small"
            onClick={this.handleRecoverDraft}>
            从初始原稿创建草稿
          </AuthButton>
        </div>}/>
    );
  }

  // ---------------------------------------------------------------------------
  // 渲染

  renderLocked() {
    const manual = store.manual || {};
    const target = store.requestedFileId != null
      ? store.files.find(f => f.id === store.requestedFileId) : null;
    const locked = !!store.deeplinkNotice; // 深链目标不可用：禁用验证
    return (
      <Card title="进入草稿编辑" style={{maxWidth: 520, margin: '40px auto'}}>
        {store.deeplinkNotice && (
          <Alert type="warning" showIcon message={store.deeplinkNotice}
            style={{marginBottom: 12}}/>
        )}
        <p>
          手册「{manual.name}」的草稿编辑受编辑密码保护。
          需同时满足：账号持有本手册的编制角色，并通过编辑密码验证。
        </p>
        <p>
          {target && target.draft
            ? `验证成功后将为文件「${target.name}」建立编辑会话并进入工作区。`
            : '验证成功后将建立第一份可编辑文件的会话并进入工作区，其余文件可在工作区内逐一开启会话。'}
        </p>
        {target && target.draft && target.active_session &&
          !target.active_session.is_mine && (
          <Alert type="warning" showIcon style={{marginBottom: 12}}
            message={`该文件当前由「${target.active_session.user_name}」编辑中，验证将无法建立会话`}/>
        )}
        {store.verifyError && <Alert type="warning" showIcon message={store.verifyError} style={{marginBottom: 12}}/>}
        <Input.Password placeholder="编辑密码" value={this.state.password}
          disabled={locked}
          onChange={e => this.setState({password: e.target.value})}
          onPressEnter={this.handleVerify} style={{marginBottom: 12}}/>
        <Button type="primary" loading={store.verifying} disabled={locked}
          onClick={this.handleVerify}>
          验证并进入编辑
        </Button>
        <Button type="link" onClick={() => history.push(`/institution/manuals/${store.id}`)}>
          返回详情
        </Button>
      </Card>
    );
  }

  /** 流程按钮行：开始编辑 → 保存并结束编辑 → 提交编制 + 刷新 */
  renderFlowActions(file, hasSession, active) {
    const finishing = store.finishingFileId === file.id;
    const hasActiveSession = hasSession || !!active;
    return (
      <div style={{marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap',
        alignItems: 'center'}}>
        {!hasSession && (
          <Tooltip title={!file.draft ? '该文件还没有可编辑草稿' : undefined}>
            <AuthButton auth="institution.manual.draft_edit" type="primary"
              size="small" disabled={!file.draft}
              onClick={() => this.handleStartSession(file.id)}>
              开始编辑
            </AuthButton>
          </Tooltip>
        )}
        {hasSession && (
          <Tooltip title={store.editorConfigs[file.id] &&
            store.editorConfigs[file.id].editor_available
            ? '请求文档服务保存并等待服务端确认落盘后，才退出会话'
            : undefined}>
            <Button type="primary" size="small" loading={finishing}
              disabled={finishing} onClick={this.handleSaveFinish}>
              保存并结束编辑
            </Button>
          </Tooltip>
        )}
        {/* 降级路径的保存动作：本机编辑后上传是同步 multipart 落盘 */}
        {hasSession && file.draft && !(
          store.editorConfigs[file.id] &&
          store.editorConfigs[file.id].editor_available) && (
          <Tooltip title="需要该文件的编辑会话才能保存">
            <AuthButton auth="institution.manual.draft_edit" size="small"
              loading={this.state.uploading || store.saving}
              disabled={!hasSession || !file.draft}
              onClick={this.handlePickSaveFile}>
              本机编辑后上传（.docx）
            </AuthButton>
          </Tooltip>
        )}
        {(file.assignment && file.assignment.is_mine) && (
          <Tooltip title={hasActiveSession
            ? '该文件有进行中的编辑会话，请先「保存并结束编辑」后再提交编制'
            : undefined}>
            <span style={{display: 'inline-block'}}>
              <Button size="small" disabled={hasActiveSession || finishing}
                onClick={() => this.handleSubmitCompile(file)}>
                提交编制
              </Button>
            </span>
          </Tooltip>
        )}
        <Tooltip title="读取最新修订序号与保存状态（不影响编辑器）">
          <Button type="link" size="small" icon={<ReloadOutlined/>}
            onClick={this.handleRefreshRevision}>刷新草稿状态</Button>
        </Tooltip>
      </div>
    );
  }

  /** 次级操作行：下载/预览/改名/排序/移除；单文件制度的新增文件入口 */
  renderFileAdminRow(file, draft) {
    const fileIndex = store.files.findIndex(f => f.id === file.id);
    return (
      <div style={{marginTop: 10, paddingTop: 8, borderTop: '1px dashed #f0f0f0',
        display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center'}}>
        <span style={{color: '#999', fontSize: 12}}>文件管理：</span>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          disabled={!file.draft}
          onClick={() => downloadFile(
            `/api/institution/manuals/${store.id}/files/${file.id}/draft/download/`,
            draft.file_name)}>下载草稿</AuthButton>
        <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
          disabled={!file.draft} onClick={() => this.handlePreview(file)}>
          预览草稿
        </AuthButton>
        <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
          onClick={this.showRename}>改名</AuthButton>
        {store.files.length > 1 && (
          <span>
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              disabled={fileIndex <= 0}
              onClick={() => this.handleMove(file, -1)}>上移</AuthButton>
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              disabled={fileIndex < 0 || fileIndex >= store.files.length - 1}
              onClick={() => this.handleMove(file, 1)}>下移</AuthButton>
          </span>
        )}
        <AuthFragment auth="institution.manual.draft_edit">
          <Popconfirm title={`确定将文件「${file.name}」移除出待发布集合？`}
            onConfirm={() => this.handleRemove(file)}>
            <Button type="link" danger size="small"
              disabled={store.files.length <= 1}>移除</Button>
          </Popconfirm>
        </AuthFragment>
        {store.files.length <= 1 && (
          <AuthButton auth="institution.manual.upload" type="link" size="small"
            loading={this.state.adding} onClick={this.handlePickAddFile}>
            新增文件（.doc/.docx）
          </AuthButton>
        )}
      </div>
    );
  }

  /**
   * 独立的"制度草稿保存状态"（最重要）：只有服务端确认回调落盘后才
   * 显示"已保存到制度草稿：rN、时间"。ONLYOFFICE 编辑器自身的"所有
   * 更改已保存"只代表文档服务缓存，绝不据此显示业务已保存：
   * - 确认进行中 → 正在请求服务端保存；
   * - 在线编辑 + 有未确认修改（editorDirty 闩锁）→ 明确警示；
   * - 在线编辑 + 确认成功（saveConfirmed）→ 已保存到制度草稿：rN、时间；
   * - 在线编辑无确认记录 → 编辑中，内容尚未经服务端确认落盘；
   * - 非在线编辑（无会话/降级路径）→ 服务端草稿数据本身就是落盘结果。
   */
  renderSaveStatus(file, hasSession) {
    const draft = file.draft || {};
    const config = store.editorConfigs[file.id];
    const onlineEditing = hasSession && !!(config && config.editor_available);
    if (store.finishingFileId === file.id) {
      return (
        <span style={{fontSize: 12, color: '#1890ff'}}>
          正在请求服务端保存当前文件…
        </span>
      );
    }
    if (onlineEditing) {
      if (store.editorDirty[file.id]) {
        return (
          <Tooltip title="ONLYOFFICE 的「所有更改已保存」仅代表文档服务缓存，不代表已写入制度草稿；「保存并结束编辑」或切换文件/返回详情时会请求服务端保存并确认落盘。">
            <Tag color="orange" style={{marginRight: 0}}>
              有未确认落盘的修改
            </Tag>
          </Tooltip>
        );
      }
      if (store.saveConfirmed[file.id]) {
        const confirmed = store.saveConfirmed[file.id];
        const revision = confirmed.revision != null
          ? confirmed.revision : draft.revision;
        return (
          <span style={{fontSize: 12, color: '#389e0d'}}>
            已保存到制度草稿：r{revision}
            {confirmed.at ? ` · ${formatDateTime(confirmed.at)}` : ''}
          </span>
        );
      }
      return (
        <span style={{fontSize: 12, color: '#d48806'}}>
          编辑中：内容尚未经服务端确认落盘
        </span>
      );
    }
    if (file.draft) {
      return (
        <span style={{fontSize: 12, color: '#389e0d'}}>
          已保存到制度草稿：r{draft.revision} · {formatDateTime(draft.last_saved_at)}
          {draft.last_saved_by_name ? `（${draft.last_saved_by_name}）` : ''}
        </span>
      );
    }
    return null;
  }

  /** 右侧顶部状态条：当前文件/修订号/独立保存状态/提交状态 +
      流程按钮（开始编辑 → 保存并结束编辑 → 提交编制）+ 次级操作行 */
  renderFileHeader(file, hasSession, active) {
    const draft = file.draft || {};
    const finishing = store.finishingFileId === file.id;
    return (
      <Card size="small" style={{marginBottom: 12}}>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: '4px 12px',
          alignItems: 'center'}}>
          <span style={{color: '#999'}}>当前文件：</span>
          <span style={{fontWeight: 600, fontSize: 15}}>{file.name}</span>
          {file.draft
            ? <Tag color="blue" style={{marginRight: 0}}>r{draft.revision}</Tag>
            : <Tag style={{marginRight: 0}}>无草稿</Tag>}
          {this.renderSaveStatus(file, hasSession)}
          {submissionTagFor(file.submission)}
        </div>
        {this.renderFlowActions(file, hasSession, active)}
        {store.finishingError && store.finishingErrorFileId === file.id && (
          <Alert type="error" showIcon style={{marginTop: 10}}
            message="保存未确认，会话已保留"
            description={store.finishingError}
            action={
              <span>
                <Button size="small" type="primary"
                  onClick={this.handleSaveFinish}>重试保存</Button>
                <Button size="small" danger style={{marginLeft: 8}}
                  onClick={this.showDiscardExit}>不保存并退出</Button>
              </span>
            }/>
        )}
        {this.renderFileAdminRow(file, draft)}
      </Card>
    );
  }

  /** 草稿元信息（次级）：会话有效期/工作文件/基于版本/负责人与分工说明 */
  renderFileMeta(file, hasSession, active) {
    const draft = file.draft || {};
    return (
      <Descriptions size="small" column={3} style={{marginTop: 12}}>
        <Descriptions.Item label="工作文件">{draft.file_name || '-'}</Descriptions.Item>
        <Descriptions.Item label="大小">{formatSize(draft.file_size)}</Descriptions.Item>
        <Descriptions.Item label="编辑会话">
          {hasSession
            ? <Tag color="green" style={{marginRight: 0}}>
                本会话可写（{formatDateTime(store.sessionExpiresOf(file.id))} 前有效）
              </Tag>
            : (active
              ? (active.is_mine
                ? <Tag color="orange" style={{marginRight: 0}}>本账号其他页签的会话进行中</Tag>
                : <Tag color="orange" style={{marginRight: 0}}>{active.user_name} 的会话进行中</Tag>)
              : <Tag color="red" style={{marginRight: 0}}>未开启会话</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="基于版本">
          {draft.base_version_no
            ? `v${draft.base_version_no}（版本快照）`
            : '来自初始原稿'}
        </Descriptions.Item>
        <Descriptions.Item label="负责人">
          {(file.assignment && file.assignment.owner_id)
            ? `${file.assignment.owner_name || '-'}`
            : '未分配'}
        </Descriptions.Item>
        <Descriptions.Item label="分工说明">
          {(file.assignment && file.assignment.note) || '-'}
        </Descriptions.Item>
      </Descriptions>
    );
  }

  renderEditorArea(file, hasSession) {
    const fileId = file.id;
    if (!hasSession) {
      return (
        <Alert type="warning" showIcon style={{marginBottom: 12}}
          message="该文件尚未开启编辑会话，开启后才能在线编辑或上传保存。"/>
      );
    }
    if (store.editorLoadingId === fileId) {
      return <div style={{padding: 40, textAlign: 'center'}}><Spin tip="正在获取编辑配置…"/></div>;
    }
    const config = store.editorConfigs[fileId];
    if (config && config.editor_available) {
      return (
        <div>
          {/* key 含 document_key：切换文件或重开会话（配置轮换）时
              强制销毁重建编辑器实例 */}
          <OnlyOfficeEditor key={`${fileId}:${config.document_key || fileId}`}
            editorConfig={config}
            onDirtyChange={dirty => store.setEditorDirty(fileId, dirty)}/>
          <div style={{marginTop: 8, color: '#999', fontSize: 12}}>
            在编辑器内保存（Ctrl+S / 自动保存）经文档服务回调落盘；
            「保存并结束编辑」与切换文件/返回详情都会请求文档服务立即保存，
            并在服务端确认落盘后才继续。编辑器的"所有更改已保存"不代表已写入制度草稿，
            以上方保存状态为准。
          </div>
        </div>
      );
    }
    return (
      <Alert type="info" showIcon style={{marginBottom: 12}} message={
        <span>
          {store.editorErrors[fileId] || '在线编辑服务未配置。'}
          当前工作方式：<b>下载草稿</b> → 本机 Word/WPS 编辑 → <b>上传保存</b>，
          全程受编辑会话与修订序号保护；同一时间每个文件仅一个可写会话。
        </span>}/>
    );
  }

  /** 无草稿文件工作区：不渲染空白编辑器，给出明确恢复入口（不得误报"草稿已保存"） */
  renderDraftlessWorkspace(file) {
    return (
      <div>
        <Card size="small" style={{marginBottom: 12}}>
          <div style={{display: 'flex', flexWrap: 'wrap', gap: '4px 12px',
            alignItems: 'center'}}>
            <span style={{color: '#999'}}>当前文件：</span>
            <span style={{fontWeight: 600, fontSize: 15}}>{file.name}</span>
            <Tag style={{marginRight: 0}}>无草稿</Tag>
          </div>
        </Card>
        {this.renderRecoveryPanel(file)}
      </div>
    );
  }

  renderWorkspace(file) {
    if (!file.draft) return this.renderDraftlessWorkspace(file);
    const active = file.active_session;
    const hasSession = !!store.sessionKeyOf(file.id);
    return (
      <div>
        {this.renderFileHeader(file, hasSession, active)}
        {this.renderFileMeta(file, hasSession, active)}
        <div style={{marginTop: 12}}>
          {this.renderEditorArea(file, hasSession)}
        </div>
        {file.draft.base_version_id && (
          <p style={{marginTop: 8, color: '#999', fontSize: 12}}>
            提示：完成编辑后请在手册详情页「版本与发布」中填写变更说明并发布新版本。
          </p>
        )}
      </div>
    );
  }

  renderEmptyWorkspace() {
    return (
      <Card size="small">
        <div style={{padding: '32px 0', textAlign: 'center', color: '#999'}}>
          该制度还没有待发布文件，请先在详情页上传原稿。
        </div>
      </Card>
    );
  }

  render() {
    const body = this.renderBody();
    return (
      <React.Fragment>
        <DraftUnsavedGate dirty={store.hasAnySession}/>
        {body}
      </React.Fragment>
    );
  }

  renderBody() {
    if (store.isFetching && !store.manual && !store.error) {
      return <div style={{padding: 40, textAlign: 'center'}}><Spin/></div>;
    }
    if (store.error && !store.manual) {
      return (
        <div style={{maxWidth: 520, margin: '40px auto'}}>
          <Alert type="warning" showIcon message={store.error}
            action={<Button size="small" onClick={() => history.push('/institution')}>返回列表</Button>}/>
        </div>
      );
    }
    if (!store.passwordVerified && !store.hasAnySession) return this.renderLocked();
    const file = store.selectedFile;
    const config = file ? store.editorConfigs[file.id] : null;
    const editorActive = !!(file && store.sessionKeyOf(file.id) &&
      config && config.editor_available);
    const multi = store.files.length > 1;
    return (
      <div style={{maxWidth: editorActive ? 1400 : 1000, margin: '0 auto', padding: '12px 0'}}>
        <div style={{marginBottom: 12}}>
          <Button type="link" icon={<ArrowLeftOutlined/>} style={{padding: 0}}
            onClick={this.handleBackToDetail}>
            返回 {store.manual ? store.manual.name : ''}
          </Button>
        </div>
        {/* 隐藏 input 不得作为 Button/label 的嵌套子节点（嵌套会双触发
            或留死按钮），统一 ref 程序触发，见 handlePickAddFile /
            handlePickSaveFile */}
        <input ref={el => { this.addFileInput = el; }} type="file"
          accept=".doc,.docx" style={{display: 'none'}} onChange={this.handleAddFile}/>
        <input ref={el => { this.saveFileInput = el; }} type="file"
          accept=".docx" style={{display: 'none'}} onChange={this.handleSaveUpload}/>
        {store.deeplinkNotice && (
          <Alert type="warning" showIcon style={{marginBottom: 12}}
            message={store.deeplinkNotice}/>
        )}
        <Row gutter={16}>
          {multi && (
            <Col xs={24} md={8} lg={7} xl={6} style={{marginBottom: 16}}>
              <FileNav adding={this.state.adding}
                onPickAddFile={this.handlePickAddFile}
                onSelect={this.handleSelectFile}/>
            </Col>
          )}
          <Col xs={24} md={multi ? 16 : 24} lg={multi ? 17 : 24} xl={multi ? 18 : 24}>
            {file
              ? this.renderWorkspace(file)
              : this.renderEmptyWorkspace()}
          </Col>
        </Row>
        {/* 新增文件：先选文件，再在弹窗中可选指定负责人与分工说明
            （不指定即"未分配"，之后可在详情页文件清单「文件分工」改派） */}
        <Modal visible={!!this.state.pendingFile}
          title={`新增文件：${this.state.pendingFile ? this.state.pendingFile.name : ''}`}
          confirmLoading={this.state.adding}
          okText="创建"
          onCancel={() => this.setState({pendingFile: null})}
          onOk={this.handleConfirmAddFile}>
          {this.state.assignOwnersError && (
            <Alert style={{marginBottom: 12}} type="error" showIcon
              message={`负责人候选加载失败：${this.state.assignOwnersError}`}
              description="未加载到候选不代表没有可用负责人，请重试；也可不留空直接创建后再改派。"
              action={<Button size="small" type="primary"
                loading={this.state.fetchingOwners}
                onClick={() => this.fetchAssignOwners()}>重试</Button>}/>
          )}
          <Form labelCol={{span: 5}} wrapperCol={{span: 17}}>
            <Form.Item label="负责人" extra="可选；负责人完成编制后可提交编制，负责人身份不授予编辑权限">
              <Select allowClear showSearch optionFilterProp="children"
                loading={this.state.fetchingOwners}
                placeholder="选择负责人账号（可留空）"
                value={this.state.assignOwnerId}
                onChange={v => this.setState({assignOwnerId: v})}>
                {this.state.assignOwners.map(u => (
                  <Option key={u.id} value={u.id}>{u.name}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="分工说明">
              <Input.TextArea rows={2} maxLength={500}
                placeholder="职责范围、协作方式等补充说明（可选）"
                value={this.state.assignNote}
                onChange={e => this.setState({assignNote: e.target.value})}/>
            </Form.Item>
          </Form>
        </Modal>
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

export default InstitutionDraftWorkspace;
