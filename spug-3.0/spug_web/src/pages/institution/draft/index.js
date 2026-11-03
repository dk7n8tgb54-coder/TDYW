/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台（2026-10-30 交互改造）：密码验证门 → 左侧文件导航 + 右侧
 * 编辑区主体；单文件制度不渲染导航，开门即编辑。
 * - 右侧顶部状态条集中展示：当前文件、修订号、独立的"制度草稿保存状态"
 *   （服务端确认落盘才显示"已保存到制度草稿：rN、时间"；ONLYOFFICE 的
 *   "所有更改已保存"只代表文档服务缓存，绝不据此显示业务已保存）与
 *   编制状态 Tag（待发布人核对/可直接纳入整套发布/待提交待发布核对/
 *   待负责人提交待发布核对/已撤回/已退回/提交已失效/旧版提交记录/
 *   编制中/无需提交，与详情页文件清单同一口径，共用
 *   compilationStatusShared）。
 * - 流程按钮：开始编辑 → 保存并结束编辑 → 提交待发布核对；下载/预览/
 *   改名/排序/移除/新增为次级操作。**2026-11-03 固定快照交接规则**：
 *   提交**仅文件有效负责人**（assignment.is_effective_owner）渲染（手册
 *   所有者非该文件有效负责人不得代提交，后端会拒绝）；提交由服务端创建
 *   独立不可变快照并冻结该文件内容——冻结期间工作区不渲染编辑器与任何
 *   编辑/结构入口，改显示「预览待核对快照」「下载待核对快照」与撤回/退回
 *   说明；pending 显示不可点击「待发布人核对」+「撤回提交」（负责人本人），
 *   持发布权且非有效负责人可「退回修改」（原因必填 ≤500）；提交失效显示
 *   「重新提交」；本文件有进行中编辑会话时禁用提交并提示先「保存并结束
 *   编辑」；有效负责人兼发布权时提示本人发布可直接纳入整套发布、提交只是
 *   交给其他发布人核对固定快照的可选动作。提交/撤回/退回真实成功后刷新
 *   清单与菜单红点（InstitutionBadgeStore，事件驱动，禁轮询）；
 *   `legacy_submitted` 旧提交记录不可用于发布，需按新规则重新提交。
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
 * - 编辑区放大/还原（2026-10-30）：编辑器上方「放大/还原」按钮（图标 +
 *   Tooltip，还原态注明 Esc）。放大以 fixed 浮层承载（zIndex 900，低于
 *   antd Modal/Message），收起文件导航、元数据与次级操作，顶部精简条
 *   （ExpandedBar）保留保存状态与「保存并结束编辑」；切换放大只改容器
 *   样式与编辑器 height prop（72vh↔100%），编辑器元素在 React 树中的
 *   位置与 key 不变——不重建实例、不重拉 editor-config（不轮换
 *   document key）；Esc 或显式离开动作（切换文件/返回详情/结束编辑/
 *   不保存退出）退出放大，编辑器不可用时放大自动失效。
 * - 编辑方式切换（2026-10-31 恢复/完善）：在线编辑与「本机编辑（下载
 *   草稿 → 本机 Word/WPS 编辑 → 上传保存）」按文件切换（编辑区顶部
 *   Segmented，仅在线配置可用时出现）；服务未配置/配置加载失败/编辑器
 *   加载失败的文件恒为本机方式，本机入口不依赖失败上报的可靠性。切换
 *   链路在 store.switchEditMode：在线切本机先确认落盘（失败留下重试），
 *   再重取编辑配置轮换 document key 让旧编辑实例回调在服务端失效（会话
 *   保留供本机上传）；日常本机上传必须携带下载草稿时记录的基线修订号，
 *   服务端草稿已推进时被后端拒绝并要求重新下载。「下载草稿」在在线
 *   编辑期间同样先确认落盘再下载，下载成功记录基线。
 * - 本机上传两条路径（2026-10-31 二轮拆分，两个入口语义严格区分）：
 *   a) 日常「上传保存（需先下载草稿）」（handleLocalUpload）链路不变——
 *      必须携带下载时记录的基线修订号；文案明确系统不校验所选文件是否
 *      基于已下载的草稿修改，只校验服务端草稿修订号未被推进。
 *   b) 次级危险操作「用本机文件替换当前草稿」（handlePickReplaceLocalFile
 *      → handleReplaceLocalUpload）不要求先下载：点击先弹 Modal.confirm，
 *      展示目标制度文件名、当前待发布草稿修订号 rN 与「整份替换（非增量）
 *      /只更新草稿不发布/历史发布版本不受影响/系统不校验所选文件来源」；
 *      确认后才打开文件选择，并以确认时捕获的 fileId+revision 上传；
 *      取消不打开选择器、不上传。冲突「草稿已被其他会话更新」不报成功、
 *      保留会话、刷新清单并提示重新确认。
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
import { AuthFragment } from 'components';
import { http } from 'libs';
import { downloadFile, formatSize, formatDateTime } from '../utils';
import {
  buildSubmissionPreviewTitle, canReturnSubmission, canWithdrawSubmission,
  effectiveOwnerIdOf, effectiveOwnerNameOf, isEffectiveOwnerOf,
  isFrozenSubmission, ownerIsDefaultAssignment, submissionIsStale,
  submissionOf, submissionSnapshotFileName, submissionStatusOf,
  SUBMISSION_STATUS,
} from '../submissionShared';
import PreviewModal from '../detail/PreviewModal';
import EditorArea from './EditorArea';
import ExpandedBar from './ExpandedBar';
import SaveStatusTag from './SaveStatusTag';
import FileNav, {compilationTagFor} from './FileNav';
import RecoveryPanel from './RecoveryPanel';
import ManualAuthButton from '../ManualAuthButton';
import { finishingErrorTitleOf, finishingRetryLabelOf } from './finishingShared';
import useWorkTabUnsaved from '../../../layout/useWorkTabUnsaved';
import institutionBadge from '../../../layout/InstitutionBadgeStore';
import store from './store';

const {Option} = Select;

/**
 * 放大态根容器：fixed 浮层占满当前视口。zIndex 取 900——盖过主布局
 * 头部/侧栏（z-index 1~2），低于 antd Modal（1000）/Message（1010），
 * 保存确认弹窗、恢复确认窗等不被浮层遮挡。overflow auto 兜底窄屏：
 * 仅浮层自身一层滚动，页面不出现第二重滚动条。
 */
const EXPANDED_ROOT_STYLE = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 900,
  maxWidth: 'none', margin: 0, padding: '8px 12px', background: '#fff',
  display: 'flex', flexDirection: 'column', overflow: 'auto',
};

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
    adding: false,
    renameFile: null, renameValue: '', renaming: false,
    // 编辑区放大态（2026-10-30）：仅在在线编辑真实可用时生效
    // （isExpandedActive），显式退出时机见 exitExpanded 各调用点
    expanded: false,
    // 新增文件时的可选文件分工（负责人/分工说明，2026-10-29）
    pendingFile: null, assignOwners: [], assignOwnerId: undefined,
    assignNote: '', assignOwnersError: '', fetchingOwners: false,
  };

  // 「用本机文件替换当前草稿」确认时捕获的目标上下文（{fileId, revision}）：
  // Modal.confirm 打开瞬间的快照，文件选择器回调只认这份上下文——确认后
  // 清单即使被推进，也绝不改用最新修订号替代确认时修订号
  pendingReplaceLocal = null;

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
    window.removeEventListener('keydown', this.handleExpandEsc);
    store.files.forEach(file => {
      if (store.sessionKeyOf(file.id)) store.requestForcesaveQuiet(file.id);
    });
    store.reset();
  }

  componentDidUpdate(_prevProps, prevState) {
    // Esc 还原监听随放大态挂/摘（页面焦点处按键；编辑器 iframe 内的
    // 按键属于独立 document 不冒泡到本页，还原始终有可见按钮兜底）
    if (prevState.expanded !== this.state.expanded) {
      if (this.state.expanded) {
        window.addEventListener('keydown', this.handleExpandEsc);
      } else {
        window.removeEventListener('keydown', this.handleExpandEsc);
      }
    }
    // 编辑器不再可用（会话退出/切换到无会话文件等）：放大随之退出，
    // 避免残留无编辑器的全屏浮层
    if (this.state.expanded && !this.isSelectedFileOnlineEditing()) {
      this.setState({expanded: false});
    }
  }

  // ---------------------------------------------------------------------------
  // 编辑区放大/还原（2026-10-30）

  /** 放大是否实际生效：state + 当前文件在线编辑真实可用 */
  isExpandedActive() {
    return this.state.expanded && this.isSelectedFileOnlineEditing();
  }

  toggleExpanded = () => {
    this.setState(prev => ({expanded: !prev.expanded}));
  };

  handleExpandEsc = (e) => {
    if (e.key === 'Escape') this.setState({expanded: false});
  };

  /** 显式退出放大：切换文件/返回详情/结束编辑/不保存退出共用 */
  exitExpanded = () => {
    if (this.state.expanded) this.setState({expanded: false});
  };

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
          this.exitExpanded();
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
    const go = () => {
      this.exitExpanded();
      history.push(`/institution/manuals/${store.id}`);
    };
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
  // 编辑方式切换（在线 ⇄ 本机）与本机编辑流程

  /**
   * 编辑方式切换（Segmented）：确认落盘、旧编辑实例回调失效（轮换
   * document key）与会话保留都在 store.switchEditMode；此处只负责冲突
   * 导航提示与切换成功的明示。切换失败时文件头部 Alert 呈现语境与
   * 重试入口（handleFinishingRetry 按 finishingErrorKind 分发）。
   */
  handleSwitchEditMode = (mode) => {
    if (store.finishingFileId) {
      message.warning('正在保存当前文件，请稍候再切换编辑方式');
      return;
    }
    const file = store.selectedFile;
    if (!file) return;
    store.switchEditMode(file.id, mode).then(res => {
      if (res.ok && mode === 'local') {
        message.success('已切换为本机编辑：下载草稿 → 本机 Word/WPS 编辑 → 上传保存');
      }
    });
  };

  /** 保存确认失败后的重试分发（语境化重试按 finishingErrorKind） */
  handleFinishingRetry = () => {
    if (store.finishingErrorKind === 'switch_local') {
      this.handleSwitchEditMode('local');
      return;
    }
    if (store.finishingErrorKind === 'download_draft') {
      this.handleDownloadDraft();
      return;
    }
    this.handleSaveFinish();
  };

  /**
   * 下载草稿（本机编辑第一步，也在文件管理行提供）：在线编辑进行中先
   * 走落盘确认链路——确认失败不下载、不切走，会话与编辑器保留供重试
   * （finishingErrorKind='download_draft'，重试按钮=重试下载）。下载前
   * 刷新清单并读取服务端当前修订号作为本次本机编辑基线，下载成功才
   * 记录（downloadFile 真实完成）；上传保存必须携带该基线，服务端草稿
   * 已推进时上传被拒、须重新下载最新草稿。无会话的查看者仅下载，
   * 不记录基线。
   */
  handleDownloadDraft = () => {
    const file = store.selectedFile;
    if (!file || !file.draft) return;
    if (store.finishingFileId) {
      message.warning('正在保存当前文件，请稍候');
      return;
    }
    const doDownload = () => {
      store.refreshFiles().then(() => {
        const entry = store.files.find(f => f.id === file.id);
        const revision = entry && entry.draft ? entry.draft.revision : null;
        return downloadFile(
          `/api/institution/manuals/${store.id}/files/${file.id}/draft/download/`,
          entry && entry.draft ? entry.draft.file_name : undefined)
          .then(() => {
            if (store.sessionKeyOf(file.id)) {
              store.recordLocalBaseline(file.id, revision);
              message.success(`草稿已下载（本机编辑基线 r${revision != null ? revision : '?'}），`
                + '本机 Word/WPS 编辑后回到本页上传保存');
            } else {
              message.success('草稿已下载');
            }
          });
      }).catch(() => {});
    };
    if (this.isSelectedFileOnlineEditing()) {
      store.confirmFileSave(file.id, '下载草稿', 'download_draft').then(ok => {
        if (ok) doDownload();
      });
      return;
    }
    doDownload();
  };

  /**
   * 本机编辑日常上传保存（编辑区本机面板「上传保存（需先下载草稿）」入口；
   * 隐藏 input 程序触发；与次级「整份替换当前草稿」入口严格区分）：
   * 客户端先拒绝非 .docx（不允许 .doc 覆盖工作草稿，后端独立校验）；
   * 必须已有下载基线（store.localBaselines）。成功提示只在后端真实成功
   * 响应之后；失败不清会话、不报成功，可重试（基线过期时重新下载）。
   */
  handleLocalUpload = (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.docx')) {
      message.error('草稿工作文件必须是 .docx 格式');
      return;
    }
    const fileId = store.selectedFileId;
    if (store.localBaselines[fileId] == null) {
      message.warning('请先下载草稿到本机编辑后再上传保存');
      return;
    }
    store.uploadLocalDraft(fileId, file)
      .then(data => {
        const revision = data && data.revision != null ? data.revision : '?';
        message.success(`草稿已上传保存（修订号 r${revision}）`);
      })
      .catch(() => {});
  };

  /**
   * 「用本机文件替换当前草稿」点击入口（本机面板次级危险操作）：
   * 先弹确认窗而不是文件选择器——展示目标制度文件名、当前待发布草稿
   * 修订号 rN 与整份替换影响（非增量修改、只更新草稿不发布、历史发布
   * 版本不受影响、系统不校验所选文件是否基于已下载草稿），用户确认后
   * 才打开 .docx 文件选择器；取消不上传。确认瞬间把 fileId+revision
   * 捕获到 pendingReplaceLocal，上传只认这份快照。
   * （antd 4 Modal.confirm 内容为打开时快照，不依赖后续 state 重渲染）
   */
  handlePickReplaceLocalFile = () => {
    const file = store.selectedFile;
    if (!file || !file.draft) return;
    const targetFileId = file.id;
    const targetName = file.name;
    const targetRevision = file.draft.revision;
    Modal.confirm({
      title: `用本机文件替换当前草稿：「${targetName}」`,
      content: (
        <div>
          <p>
            目标制度文件：<b>{targetName}</b>
            {targetRevision != null && `（当前待发布草稿修订号 r${targetRevision}）`}
          </p>
          <p>
            确认后请选择本机 .docx 文件：会<b>整份替换</b>该文件的当前草稿（不是增量修改）。
          </p>
          <p>上传成功只更新草稿，<b>不会发布</b>；历史发布版本不受影响。</p>
          <p style={{color: '#888'}}>
            系统不会校验所选文件是否基于已下载的草稿修改，请确认本机文件就是该草稿的最新版本。
          </p>
        </div>
      ),
      okText: '选择文件并替换',
      cancelText: '取消',
      okType: 'danger',
      onOk: () => {
        this.pendingReplaceLocal = {
          fileId: targetFileId, revision: targetRevision};
        if (this.replaceFileInput) this.replaceFileInput.click();
      },
    });
  };

  /**
   * 「用本机文件替换当前草稿」文件选择回调：客户端先拒绝非 .docx；
   * 只使用确认弹窗捕获的（fileId, revision）发起整份替换（绝不改用清单
   * 最新修订号）；成功提示只在后端真实成功之后。冲突「草稿已被其他会话
   * 更新」=确认时修订号过期：不报成功、会话保留（后端同口径不清会话）、
   * 刷新清单并提示重新确认后再选文件；其余错误由 store 按既有会话/密码
   * 分类处理（拦截器已提示，不二次弹同一错误）。
   */
  handleReplaceLocalUpload = (e) => {
    const picked = e.target.files[0];
    e.target.value = '';
    if (!picked) return;
    const pending = this.pendingReplaceLocal;
    if (!pending) return; // 未经确认（正常不可达）：绝不上传
    if (!picked.name.toLowerCase().endsWith('.docx')) {
      message.error('草稿工作文件必须是 .docx 格式');
      return;
    }
    this.pendingReplaceLocal = null;
    if (!store.sessionKeyOf(pending.fileId)) {
      message.warning('需要该文件的编辑会话才能替换草稿');
      return;
    }
    store.replaceLocalDraft(pending.fileId, picked, pending.revision)
      .then(data => {
        const revision = data && data.revision != null ? data.revision : '?';
        message.success(`已用本机文件替换草稿（修订号 r${revision}）`);
      })
      .catch(err => {
        const text = typeof err === 'string' ? err : '';
        if (text.includes('草稿已被其他会话更新')) {
          // 拦截器已提示过错误：这里只刷新清单并引导重新确认（不重复弹
          // 同一错误），会话保留可重试
          store.refreshFiles().catch(() => {});
          message.warning('当前草稿已更新，请重新点击「用本机文件替换当前草稿」'
            + '确认最新修订号后再选择文件');
        }
      });
  };

  // ---------------------------------------------------------------------------
  // 文件管理

  /** 选中文件后先弹分工弹窗（负责人可选），确认后才上传创建。
   *  负责人默认=手册所有者（manual.owner_id；后端本次起 assignment-owners
   *  候选也会包含所有者），可改选其他持编制资格账号或清空。 */
  handleAddFile = (e) => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    const manual = store.manual || {};
    this.setState({pendingFile: file, assignOwners: [],
      assignOwnerId: manual.owner_id || undefined,
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
      .then(() => {
        // 每份上传文件各自建立独立制度文件与当前草稿；创建失败由 HTTP
        // 拦截器统一提示一次，这里只负责成功提示与关闭分工弹窗
        message.success('文件已新增');
        this.setState({pendingFile: null});
      })
      .catch(() => {})
      .finally(() => this.setState({adding: false}));
  };

  handlePickAddFile = () => {
    if (this.addFileInput) this.addFileInput.click();
  };

  /** 提交待发布核对（仅文件有效负责人；服务端创建固定不可变快照并冻结
   *  该文件内容，发布人核对快照后整套发布使用该快照）。
   *  提交成功真实返回后才提示、刷新清单并刷新菜单红点（事件驱动，禁轮询）。 */
  handleSubmitCompile = (file) => {
    const stale = submissionIsStale(file);
    const label = stale ? '重新提交' : '提交待发布核对';
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
            发布人核对固定快照后，整套发布将使用该快照内容（不再读取当前草稿）。
          </p>
          <p style={{color: '#888'}}>
            提交有效期间不能重复提交；可「撤回提交」后继续修改，或由发布人
            「退回修改」（必填原因）。你本人具备发布权时也可直接纳入整套发布。
          </p>
        </div>
      ),
      okText: '确认提交',
      onOk: () => http.post(
        `/api/institution/manuals/${store.id}/files/${file.id}/submit/`, {})
        .then(() => {
          message.success('已提交待发布核对，等待发布人核对固定快照');
          // 待核对快照数属菜单红点：真实成功后刷新（fetch 静默失败，不影响流程）
          institutionBadge.fetch();
          return store.refreshFiles().catch(() => {});
        }),
    });
  };

  /** 撤回提交待发布核对（仅文件有效负责人本人）：撤回后快照作废、
   *  内容解冻，可修改后重新提交；发布人不能再使用该快照 */
  handleWithdrawSubmission = (file) => {
    Modal.confirm({
      title: `撤回提交：${file.name}`,
      content: '撤回后该文件已提交的固定快照作废、内容解冻，你可以继续修改并按新规则重新提交；发布人将不能再使用该快照核对与发布。',
      okText: '确认撤回',
      onOk: () => store.withdrawSubmission(file.id)
        .then(() => message.success('已撤回提交，可继续修改该文件')),
    });
  };

  /** 退回修改（持发布权且非该文件有效负责人）：原因必填（≤500），
   *  退回后旧快照作废、内容解冻，负责人修改后可重新提交 */
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
          .then(() => message.success('已退回修改，等待负责人重新提交待发布核对'));
      },
    });
  };

  /** 待核对快照预览（冻结文件；标题含提交人与提交时间，绝不冒充当前草稿） */
  handleSubmissionPreview = (file) => {
    store.fetchSubmissionPreviewUrl(file.id)
      .then(data => this.setState({preview: {
        url: data && data.preview_url,
        fileName: (data && data.file_name) || submissionSnapshotFileName(file),
        title: buildSubmissionPreviewTitle(file, data),
      }}))
      .catch(() => {});
  };

  /** 下载待核对快照（文件名用接口下发的快照文件名） */
  handleDownloadSubmission = (file) => {
    downloadFile(
      `/api/institution/manuals/${store.id}/files/${file.id}/submission/download/`,
      submissionSnapshotFileName(file));
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
      if (ok) {
        // 会话已撤销：放大态随编辑器一起退出（结束编辑退出放大）
        this.exitExpanded();
        message.success('已保存并结束编辑');
      }
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
        .then(() => {
          this.exitExpanded();
          message.success('已退出编辑会话');
        })
        .catch(() => {}),
    });
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

  /** 预览当前待发布草稿（不是提交时快照）：标题明确版本来源，不含修订号 rN */
  handlePreview = (file) => {
    http.get(`/api/institution/manuals/${store.id}/files/${file.id}/draft/preview-url/`)
      .then(data => this.setState({preview: {
        url: data.preview_url, fileName: data.file_name,
        title: `预览待发布草稿：${data.file_name || ''}`,
      }}));
  };

  // ---------------------------------------------------------------------------
  // 草稿恢复（无草稿文件）：两态由 files 清单行下发的 draft_recovery 决定
  // （current_version=从当前生效版本恢复；none/缺失=仅提示重新上传），
  // 渲染唯一实现在 RecoveryPanel，本文件不额外判断恢复来源。

  // ---------------------------------------------------------------------------
  // 渲染

  renderLocked() {
    const manual = store.manual || {};
    const target = store.requestedFileId != null
      ? store.files.find(f => f.id === store.requestedFileId) : null;
    const locked = !!store.deeplinkNotice; // 深链目标不可用：禁用验证
    // 负责人独占（2026-10-31）：持编制资格但未指派任何文件负责人的账号
    // 无法建立编辑会话（后端同口径拒绝），在密码门前明确提示
    const hasEditRole = (manual.my_roles || []).includes('edit');
    const hasMineAssignment = (store.files || []).some(
      f => f.assignment && f.assignment.is_mine);
    return (
      <Card title="进入草稿编辑" style={{maxWidth: 520, margin: '40px auto'}}>
        {store.deeplinkNotice && (
          <Alert type="warning" showIcon message={store.deeplinkNotice}
            style={{marginBottom: 12}}/>
        )}
        {hasEditRole && !hasMineAssignment && (
          <Alert type="warning" showIcon style={{marginBottom: 12}}
            message="编辑仅限文件负责人：你持本手册编制资格，但尚未被指派任何文件的负责人，请先由手册所有者指派"/>
        )}
        <p>
          手册「{manual.name}」的草稿编辑受编辑密码保护。
          {manual.is_owner
            ? '你是本手册所有者：可编辑该手册任意文件，验证密码后即可进入。'
            : '需同时满足：账号持本手册编制资格且为对应文件负责人，并通过编辑密码验证。'}
        </p>
        <p>
          {target && target.draft
            ? `验证成功后将为文件「${target.name}」建立编辑会话并进入工作区。`
            : '验证成功后将建立你负责文件的编辑会话并进入工作区，其余文件可在工作区内逐一开启会话。'}
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

  /** 发布权口径（与详情页/共享 helper 同一口径：手册所有者 或 my_roles 含 publish） */
  canPublishCompilation() {
    const manual = store.manual || {};
    return !!manual.is_owner || (manual.my_roles || []).includes('publish');
  }

  /** 提交待发布核对 / 撤回提交 / 退回修改入口（2026-11-03 固定快照交接）：
   *  - 「提交待发布核对」/「重新提交」**仅对 assignment.is_effective_owner
   *    渲染**（手册所有者非该文件有效负责人不得代提交，后端同口径）；
   *  - pending（有效固定快照、内容已冻结）显示不可点击「待发布人核对」+「撤回提交」；
   *    持发布权且非该文件有效负责人可「退回修改」（原因必填 ≤500）；
   *  - 该文件有进行中的编辑会话时禁用提交并提示先「保存并结束编辑」。 */
  renderSubmissionActions(file, canPublish, busy) {
    const manual = store.manual || {};
    const status = submissionStatusOf(submissionOf(file));
    const isEffectiveOwner = isEffectiveOwnerOf(file);
    const stale = submissionIsStale(file);
    if (status === SUBMISSION_STATUS.PENDING && !stale) {
      return (
        <React.Fragment>
          <Tooltip title="该文件已提交待发布核对：固定不可变快照有效期间不能重复提交（内容已冻结）。发布人核对快照后整套发布将使用该快照内容">
            <span><Button size="small" disabled>待发布人核对</Button></span>
          </Tooltip>
          {canWithdrawSubmission(file) && (
            <Button size="small" danger
              onClick={() => this.handleWithdrawSubmission(file)}>
              撤回提交
            </Button>
          )}
          {canReturnSubmission(file, manual) && (
            <Tooltip title="退回后该文件快照作废、内容解冻，负责人可修改后重新提交；必须填写退回原因（≤500 字）">
              <Button size="small"
                onClick={() => this.handleReturnSubmission(file)}>
                退回修改
              </Button>
            </Tooltip>
          )}
        </React.Fragment>
      );
    }
    if (!isEffectiveOwner) return null;
    // 已发布且无待发布修改（revision_open=false）的文件没有需要交接的草稿：
    // 不渲染必然无意义、且会与状态 Tag 冲突的入口（stale 兜底可重提）
    if (!file.revision_open) return null;
    const label = stale ? '重新提交' : '提交待发布核对';
    let tip = stale
      ? '提交待发布核对已失效：提交后草稿又被保存/重建，需重新提交以生成新的固定快照'
      : '提交会为该文件创建固定不可变快照并冻结内容，等待发布人核对；' +
        '发布人核对快照后整套发布将使用该快照内容（不再读取当前草稿）';
    if (busy) {
      tip = '该文件有进行中的编辑会话，请先「保存并结束编辑」后再提交待发布核对';
    } else if (canPublish) {
      tip = '你是该文件有效负责人且具备发布权：本人发布时可直接纳入整套发布并' +
        '使用当前草稿；提交待发布核对只是交给其他发布人核对固定快照的可选动作';
    }
    return (
      <Tooltip title={tip}>
        {/* disabled 的原生按钮不派发鼠标事件，须用 span 包裹让提示可达 */}
        <span>
          <Button size="small" disabled={busy}
            onClick={() => this.handleSubmitCompile(file)}>
            {label}
          </Button>
        </span>
      </Tooltip>
    );
  }

  /** 流程按钮行：开始编辑（负责人独占）→ 保存并结束编辑 → 提交待发布核对 + 刷新 */
  renderFlowActions(file, hasSession, active) {
    const manual = store.manual || {};
    const finishing = store.finishingFileId === file.id;
    const frozen = isFrozenSubmission(file);
    const hasActiveSession = hasSession || !!active;
    // 负责人独占编辑（2026-10-31）：编制授权 + 该文件负责人；二轮权限
    // 模型改造起 所有者例外可编辑该手册任意文件（超管不可，除非兼任
    // 所有者/负责人）。其余账号不渲染会话入口，明确提示指引。
    // 冻结文件（有效提交固定快照）一律不渲染任何编辑入口（后端拒绝）
    const canEdit = (manual.my_roles || []).includes('edit');
    const isAssignee = !frozen &&
      (!!(canEdit && file.assignment && file.assignment.is_mine) ||
        !!manual.is_owner);
    // 提交门控（2026-11-03 固定快照交接，后端同口径）：仅有效负责人
    const canPublish = this.canPublishCompilation();
    return (
      <div style={{marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap',
        alignItems: 'center'}}>
        {frozen && (
          <span style={{color: '#999', fontSize: 12}}>
            该文件已提交待发布核对：内容已冻结，需负责人撤回提交或发布人退回后才能继续编辑
          </span>
        )}
        {!frozen && !hasSession && isAssignee && (
          <Tooltip title={!file.draft ? '该文件还没有可编辑草稿' : undefined}>
            <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
              type="primary" size="small" disabled={!file.draft}
              onClick={() => this.handleStartSession(file.id)}>
              开始编辑
            </ManualAuthButton>
          </Tooltip>
        )}
        {!frozen && !hasSession && !isAssignee && (
          <span style={{color: '#999', fontSize: 12}}>
            编辑仅限文件负责人，请先由手册所有者指派
          </span>
        )}
        {!frozen && hasSession && (
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
        {this.renderSubmissionActions(file, canPublish,
          hasActiveSession || finishing)}
        <Tooltip title="读取最新修订序号与保存状态（不影响编辑器）">
          <Button type="link" size="small" icon={<ReloadOutlined/>}
            onClick={this.handleRefreshRevision}>刷新草稿状态</Button>
        </Tooltip>
      </div>
    );
  }

  /** 次级操作行（2026-10-31 按授权模型拆分门控；2026-11-03 固定快照冻结）：
   *  - 未冻结文件：下载草稿/预览草稿 = 文件负责人（编制授权 + is_mine，
   *    与编辑入口同域；所有者例外）；改名/上移/下移/移除/新增文件 = 手册
   *    所有者或平台超管（ManualAuthButton：所有者豁免页面码，后端独立校验）。
   *  - 冻结文件（有效提交固定快照）：预览/下载改读**待核对快照**端点；改名/
   *    调整顺序/移除/分工一律禁用（后端结构写路径同样拒绝）——需负责人撤回
   *    提交或发布人退回后才能继续维护。 */
  renderFileAdminRow(file, draft) {
    const manual = store.manual || {};
    const frozen = isFrozenSubmission(file);
    const fileIndex = store.files.findIndex(f => f.id === file.id);
    const canEdit = (manual.my_roles || []).includes('edit');
    const isAssignee = !frozen &&
      (!!(canEdit && file.assignment && file.assignment.is_mine) ||
        !!manual.is_owner);
    const canManageFiles = !!manual.is_owner || !!manual.is_admin;
    const frozenTip = '该文件已提交待发布核对（内容已冻结）：不能改名/调整顺序/移除/改派分工；需负责人撤回提交或发布人退回修改后才能继续维护';
    return (
      <div style={{marginTop: 10, paddingTop: 8, borderTop: '1px dashed #f0f0f0',
        display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center'}}>
        <span style={{color: '#999', fontSize: 12}}>文件管理：</span>
        {frozen ? (
          <span>
            <ManualAuthButton manual={manual} auth="institution.manual.view"
              type="link" size="small"
              onClick={() => this.handleSubmissionPreview(file)}>
              预览待核对快照
            </ManualAuthButton>
            <Tooltip title={`下载该文件已提交的固定快照（${submissionSnapshotFileName(file)}）；整套发布将使用该快照内容`}>
              <ManualAuthButton manual={manual} auth="institution.manual.download"
                type="link" size="small"
                onClick={() => this.handleDownloadSubmission(file)}>
                下载待核对快照
              </ManualAuthButton>
            </Tooltip>
          </span>
        ) : isAssignee ? (
          <span>
            <ManualAuthButton manual={manual} auth="institution.manual.download"
              type="link" size="small"
              disabled={!file.draft}
              onClick={this.handleDownloadDraft}>下载草稿</ManualAuthButton>
            <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
              type="link" size="small"
              disabled={!file.draft} onClick={() => this.handlePreview(file)}>
              预览草稿
            </ManualAuthButton>
          </span>
        ) : (
          <span style={{color: '#999', fontSize: 12}}>下载/预览草稿仅限文件负责人</span>
        )}
        {canManageFiles && (frozen ? (
          <Tooltip title={frozenTip}>
            <span>
              <Button type="link" size="small" disabled>改名</Button>
              {store.files.length > 1 && (
                <span>
                  <Button type="link" size="small" disabled>上移</Button>
                  <Button type="link" size="small" disabled>下移</Button>
                </span>
              )}
              <Button type="link" danger size="small" disabled>移除</Button>
            </span>
          </Tooltip>
        ) : (
          <span>
            <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
              type="link" size="small"
              onClick={this.showRename}>改名</ManualAuthButton>
            {store.files.length > 1 && (
              <span>
                <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
                  type="link" size="small"
                  disabled={fileIndex <= 0}
                  onClick={() => this.handleMove(file, -1)}>上移</ManualAuthButton>
                <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
                  type="link" size="small"
                  disabled={fileIndex < 0 || fileIndex >= store.files.length - 1}
                  onClick={() => this.handleMove(file, 1)}>下移</ManualAuthButton>
              </span>
            )}
            {(manual.is_owner ? (
              <Popconfirm title={`确定将文件「${file.name}」移除出待发布集合？`}
                onConfirm={() => this.handleRemove(file)}>
                <Button type="link" danger size="small"
                  disabled={store.files.length <= 1}>移除</Button>
              </Popconfirm>
            ) : (
              <AuthFragment auth="institution.manual.draft_edit">
                <Popconfirm title={`确定将文件「${file.name}」移除出待发布集合？`}
                  onConfirm={() => this.handleRemove(file)}>
                  <Button type="link" danger size="small"
                    disabled={store.files.length <= 1}>移除</Button>
                </Popconfirm>
              </AuthFragment>
            ))}
            {store.files.length <= 1 && (
              <ManualAuthButton manual={manual} auth="institution.manual.upload"
                type="link" size="small"
                loading={this.state.adding} onClick={this.handlePickAddFile}>
                新增文件（.doc/.docx）
              </ManualAuthButton>
            )}
          </span>
        ))}
      </div>
    );
  }

  /**
   * 独立的"制度草稿保存状态"展示已抽出为 SaveStatusTag（状态条与放大态
   * 精简顶栏共用，2026-10-30）；此处仅负责装配。
   */
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
            ? <Tooltip title={'内部修订号：草稿每次保存/重建递增，仅用于并发保护与提交失效判定，' +
                '不是草稿版本号（正式版本号 vN 只在发布后产生）'}>
                <span style={{color: '#999', fontSize: 12}}>
                  内部修订号 r{draft.revision}
                </span>
              </Tooltip>
            : <Tag style={{marginRight: 0}}>无草稿</Tag>}
          <SaveStatusTag file={file} hasSession={hasSession}/>
          {compilationTagFor(file, {canPublish: this.canPublishCompilation()})}
          {isFrozenSubmission(file) && (
            <Tooltip title="该文件已提交待发布核对：内容已冻结，发布人核对固定快照后整套发布使用该快照">
              <Tag color="blue" style={{marginRight: 0}}>已冻结</Tag>
            </Tooltip>
          )}
        </div>
        {this.renderFlowActions(file, hasSession, active)}
        {store.finishingError && store.finishingErrorFileId === file.id && (
          <Alert type="error" showIcon style={{marginTop: 10}}
            message={finishingErrorTitleOf(store.finishingErrorKind)}
            description={store.finishingError}
            action={
              <span>
                <Button size="small" type="primary"
                  onClick={this.handleFinishingRetry}>
                  {finishingRetryLabelOf(store.finishingErrorKind)}
                </Button>
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
            : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="负责人">
          {effectiveOwnerIdOf(file) != null && effectiveOwnerIdOf(file) !== ''
            ? `${effectiveOwnerNameOf(file) || '-'}` +
              `${ownerIsDefaultAssignment(file) ? '（手册所有者，默认）' : ''}`
            : '未分配'}
        </Descriptions.Item>
        <Descriptions.Item label="分工说明">
          {(file.assignment && file.assignment.note) || '-'}
        </Descriptions.Item>
      </Descriptions>
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
        {/* 恢复面板（两态由服务端 draft_recovery 决定：current_version 可恢复；
            无发布快照只提示重新上传，不渲染任何恢复/重建按钮）自 2026-10-31
            起独立为 RecoveryPanel（文件行数门禁拆分） */}
        <RecoveryPanel file={file}/>
      </div>
    );
  }

  /** 冻结文件工作区（有效提交固定快照）：不渲染任何编辑入口/编辑器，
   *  明确说明冻结语义与出口（撤回提交 / 退回修改），并提示预览/下载
   *  「待核对快照」（与发布将使用的内容一致） */
  renderFrozenNotice() {
    return (
      <Card size="small">
        <Alert type="info" showIcon
          message="该文件已提交待发布核对：内容已冻结，不能开始/继续编辑"
          description={
            <div>
              <p>
                提交已为该文件创建固定不可变内容快照并冻结内容：本轮不能编辑、
                改名、调整顺序、移除或改派分工，也不能重复提交；发布人核对固定
                快照后，整套发布将使用该快照内容（不再读取当前草稿）。
              </p>
              <p>
                如需修改：负责人可「撤回提交」，持发布权的账号可「退回修改」
                （必须填写原因）；撤回或退回后旧快照作废、内容解冻，可修改并
                重新提交待发布核对。
              </p>
              <p style={{color: '#888'}}>
                冻结期间可在「文件管理」行预览/下载待核对快照，内容与发布时一致。
              </p>
            </div>
          }/>
      </Card>
    );
  }

  renderWorkspace(file) {
    if (!file.draft) return this.renderDraftlessWorkspace(file);
    const active = file.active_session;
    const hasSession = !!store.sessionKeyOf(file.id);
    const expanded = this.isExpandedActive();
    const frozen = isFrozenSubmission(file);
    return (
      /* 放大态：工作区占满 Col 并以 flex column 分层，头部/元数据/说明
         均以 display none 收起（不改变编辑器在树中的位置，实例不重建） */
      <div style={expanded ? {height: '100%', display: 'flex',
        flexDirection: 'column', minHeight: 0} : undefined}>
        <div style={expanded ? {display: 'none'} : undefined}>
          {this.renderFileHeader(file, hasSession, active)}
        </div>
        <div style={expanded ? {display: 'none'} : undefined}>
          {this.renderFileMeta(file, hasSession, active)}
        </div>
        <div style={expanded ? {flex: 1, minHeight: 320, marginTop: 8}
          : {marginTop: 12}}>
          {frozen ? this.renderFrozenNotice() : (
            <EditorArea file={file} hasSession={hasSession}
              expanded={expanded} onToggleExpanded={this.toggleExpanded}
              onSwitchMode={this.handleSwitchEditMode}
              onDownloadDraft={this.handleDownloadDraft}
              onPickUploadFile={this.handlePickSaveFile}
              onPickReplaceFile={this.handlePickReplaceLocalFile}/>
          )}
        </div>
        {file.draft.base_version_id && (
          <p style={expanded ? {display: 'none'}
            : {marginTop: 8, color: '#999', fontSize: 12}}>
            提示：完成编辑后请在手册详情页「版本与发布」中填写变更说明并发布新版本。
          </p>
        )}
      </div>
    );
  }

  /**
   * 0 文件空态：内容入口只指向详情页「文件清单 → 修订草稿」的
   * 「新增制度文件」（上传文件直接生成当前草稿，不再有历史来源类入口）。
   */
  renderEmptyWorkspace() {
    return (
      <Card size="small">
        <div style={{padding: '32px 0', textAlign: 'center', color: '#999'}}>
          该制度还没有待发布文件：请回到手册详情页，在「文件清单 → 修订草稿」
          中点击「新增待发布文件」上传，上传文件作为待发布文件的当前草稿。
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
    const editorActive = this.isSelectedFileOnlineEditing();
    const multi = store.files.length > 1;
    const expanded = this.isExpandedActive();
    return (
      <div style={expanded ? EXPANDED_ROOT_STYLE
        : {maxWidth: editorActive ? 1400 : 1000, margin: '0 auto', padding: '12px 0'}}>
        {/* 顶栏槽位（常规=返回入口；放大=精简条）：两侧分支同为 div，
            类型稳定，切换放大不位移后续兄弟（编辑器树位置不变） */}
        {expanded ? (
          <div style={{flexShrink: 0, marginBottom: 8}}>
            <ExpandedBar file={file}
              onBackToDetail={this.handleBackToDetail}
              onSaveFinish={this.handleSaveFinish}
              onDiscardExit={this.showDiscardExit}
              onFinishingRetry={this.handleFinishingRetry}/>
          </div>
        ) : (
          <div style={{marginBottom: 12}}>
            <Button type="link" icon={<ArrowLeftOutlined/>} style={{padding: 0}}
              onClick={this.handleBackToDetail}>
              返回 {store.manual ? store.manual.name : ''}
            </Button>
          </div>
        )}
        {/* 隐藏 input 不得作为 Button/label 的嵌套子节点（嵌套会双触发
            或留死按钮），统一 ref 程序触发：新增文件=handlePickAddFile /
            日常上传=handlePickSaveFile（handleLocalUpload）/ 整份替换=
            handlePickReplaceLocalFile（确认后才触发，handleReplaceLocalUpload） */}
        <input ref={el => { this.addFileInput = el; }} type="file"
          accept=".doc,.docx" style={{display: 'none'}} onChange={this.handleAddFile}/>
        <input ref={el => { this.saveFileInput = el; }} type="file"
          accept=".docx" style={{display: 'none'}} onChange={this.handleLocalUpload}/>
        <input ref={el => { this.replaceFileInput = el; }} type="file"
          accept=".docx" style={{display: 'none'}} onChange={this.handleReplaceLocalUpload}/>
        {store.deeplinkNotice && (
          <Alert type="warning" showIcon
            style={expanded ? {display: 'none'} : {marginBottom: 12}}
            message={store.deeplinkNotice}/>
        )}
        <Row gutter={16} style={expanded ? {flex: 1, minHeight: 0} : undefined}>
          {multi && (
            <Col xs={24} md={8} lg={7} xl={6}
              style={expanded ? {display: 'none'} : {marginBottom: 16}}>
              <FileNav adding={this.state.adding}
                onPickAddFile={this.handlePickAddFile}
                onSelect={this.handleSelectFile}/>
            </Col>
          )}
          <Col xs={24} md={multi ? 16 : 24} lg={multi ? 17 : 24} xl={multi ? 18 : 24}
            style={expanded ? {flex: '1 1 auto', minWidth: 0, maxWidth: '100%'}
              : undefined}>
            {file
              ? this.renderWorkspace(file)
              : this.renderEmptyWorkspace()}
          </Col>
        </Row>
        {/* 新增文件：先选文件，再在弹窗中可选指定负责人与分工说明
            （不指定即默认负责人=手册所有者，之后可在详情页文件清单负责人列改派） */}
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
            <Form.Item label="负责人" extra="默认手册所有者；候选=持本手册编制资格的启用账号（含所有者），可改选或清空。负责人独占编辑并负责提交待发布核对（提交后创建固定快照并冻结内容）">
              <Select allowClear showSearch optionFilterProp="children"
                loading={this.state.fetchingOwners}
                placeholder="选择负责人账号（默认手册所有者，可清空）"
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
          title={this.state.preview && this.state.preview.title}
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

export default InstitutionDraftWorkspace;
