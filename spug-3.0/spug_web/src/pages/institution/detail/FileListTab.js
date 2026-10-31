/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签（详情页默认页签，2026-10-30 双视图版）：
 * 页签内分两个内容视图（不新增顶层页签），杜绝"已发布文件 / 待发布草稿 /
 * 编制提交"三种状态混为一谈：
 * - 「当前生效版本 vN」：最近一次发布形成的不可变快照清单。预览/下载始终
 *   打开发布快照，按钮与预览标题均注明版本来源（预览当前生效版 vN）；
 *   草稿侧的"已从待发布移除"以行内 Tag 提示（发布后该文件将不在清单中）。
 *   2026-10-31 起不展示负责人列（负责人属修订分工，只在「修订草稿」视图
 *   展示与维护；assignment 数据仍随行关联，供「只看我负责的文件」筛选）。
 * - 「修订草稿」：待发布工作内容。展示 草稿修订号(rN)/负责人/状态(草稿 vs
 *   生效版本关系+修订进行中)/编制提交；预览与下载明确打开待发布草稿
 *   （预览待发布草稿 rN），仅持编制角色者可用（后端同样要求 draft_edit +
 *   can_edit_draft，前端不扩权）。
 * 默认视图：有生效版本 → 当前生效版本；首次发布前 → 修订草稿。切换视图
 * 保留「只看我负责的文件」筛选并清空行勾选（勾选属于草稿视图的批量分工）。
 * 「编制提交」是交接状态不是发布状态：提交有效时对应提交时的修订号（当前
 * 草稿与提交修订号一致，预览草稿即为提交内容）；草稿再次变更即显示"提交
 * 已失效"。系统不保存提交时刻的文件副本（无历史快照机制），该限制在
 * 提示文案中明确说明，绝不把最新草稿冒充"已提交版本"。
 * 负责人是当前责任归属（仅在「修订草稿」视图展示与维护）：2026-10-31
 * 授权模型下负责人独占编辑——编辑=模块 draft_edit 权限 + 手册编制授权
 * （my_roles.edit）+ 该文件负责人身份（is_mine），同一文件受单写会话
 * 限制（同一时间仅一人）；分工入口在「修订草稿」视图的负责人列
 * （仅所有者/制度管理员可写），不改变任何权限。
 * 行操作：修订进行中 → 「继续编辑」深链复用工作副本；修订已结束 →
 * 「开始修订」（真实状态动作，needs_repair 时经确认从生效版本快照修复）。
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
import { hasPermission, history } from 'libs';
import { http } from 'libs';
import {
  canViewPublished, canViewWorkspace, downloadFile, formatSize,
  formatDateTime,
} from '../utils';
import PreviewModal from './PreviewModal';
import FileAssignmentModal from './FileAssignmentModal';
import { buildFileState } from './draftStatusShared';
import store from './store';

// 提交编制状态文案（服务端 submission.state：none/submitted/stale）。
// 提交是"负责人→发布者"的交接标记，不代表已发布生效；系统不保存提交
// 时刻的文件副本（无历史快照机制），有效/失效的差异与该限制在 Tooltip
// 中说明，绝不把更新后的草稿冒充"已提交版本"。
const SUBMISSION_META = {
  none: {label: '未提交', color: 'default',
    tip: '负责人完成编制后可在此提交（记录提交时的草稿修订号）'},
  submitted: {label: '已提交', color: 'green', tip: null},
  stale: {label: '提交已失效', color: 'orange', tip: null},
};

const VIEW_EFFECTIVE = 'effective';
const VIEW_DRAFT = 'draft';

@observer
class FileListTab extends React.Component {
  state = {
    preview: null, assignmentFile: null, batchAssign: false,
    onlyMine: false, selectedKeys: [], activeView: null,
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

  /** 从文件行跳到"文件变更记录"页签并预选该文件（父级切页签） */
  openFileHistory = (fileId) => {
    store.fileChangeTarget = fileId;
    if (this.props.onOpenFileHistory) this.props.onOpenFileHistory();
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

  /** 草稿视图预览/下载：明确打开待发布草稿（尚未生效）。后端要求
   *  draft_edit + 编制授权（负责人域），前端只在 负责人（编制授权 +
   *  is_mine）行渲染，与负责人独占编辑口径一致，不扩权 */
  renderDraftFileActions(file) {
    const draft = file.draft;
    if (!draft) return null;
    const name = draft.file_name || file.name;
    const revision = draft.revision;
    return (
      <span>
        <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
          onClick={() => this.showPreview(
            http.get(`/api/institution/manuals/${store.id}/files/${file.id}/draft/preview-url/`),
            name, `预览待发布草稿 r${revision}：${name}`)}>
          预览草稿 r{revision}
        </AuthButton>
        <Tooltip title={`下载待发布草稿 r${revision}（尚未生效的工作副本）`}>
          <AuthButton auth="institution.manual.download" type="link" size="small"
            onClick={() => downloadFile(
              `/api/institution/manuals/${store.id}/files/${file.id}/draft/download/`,
              name)}>下载</AuthButton>
        </Tooltip>
      </span>
    );
  }

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
              修复来源：当前生效版本 v{data.draft_recovery.version_no} 的文件快照
              （绝不改用初始来源）。
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
        '对应文件的提交编制记录同步失效（历史操作记录保留）。',
      okText: '确认清空',
      onOk: () => store.batchAssignFiles(ids, null, '')
        .then(() => {
          message.success(`已清空 ${ids.length} 份文件的负责人`);
          this.setState({selectedKeys: []});
        }),
    });
  };

  /** 提交编制：记录提交时草稿修订号；此后草稿再变更提交状态自动失效 */
  handleSubmitCompile = (file) => {
    const assignment = (file.assignment || {});
    const revision = file.draft ? file.draft.revision : null;
    Modal.confirm({
      title: `提交编制：${file.name}`,
      content: (
        <div>
          <p>确认该文件已完成编制并提交核对？</p>
          <p style={{color: '#888'}}>
            将记录当前草稿修订号 {revision != null ? `r${revision}` : '-'} 与提交时间；
            此后草稿再次保存或重建、负责人改派或整套发布完成，提交状态都会
            自动失效，需重新提交。
          </p>
          {!assignment.owner_id && (
            <p style={{color: '#fa8c16'}}>该文件尚未指定负责人，建议先指定负责人再提交。</p>
          )}
        </div>
      ),
      okText: '确认提交',
      onOk: () => store.submitCompile(file.id)
        .then(data => {
          const state = data && data.submission && data.submission.state;
          message.success(state === 'submitted'
            ? '已提交编制，等待发布核对' : '已更新提交记录');
        }),
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

  /** 生效视图行操作：预览/下载（发布快照，注明版本来源）+ 变更记录；
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
          onClick={() => this.openFileHistory(row.snap.manual_file_id)}>
          变更记录
        </AuthButton>
      </span>
    );
  }

  /** 草稿视图行操作：开始修订/继续编辑 与 预览/下载待发布草稿
   *  （负责人独占：编制授权 + 该文件负责人；非负责人的编制授权账号
   *  不渲染编辑入口，占位提示指引先获得分工）+ 提交编制（负责人）+
   *  变更记录 */
  renderDraftRowActions(row, canEdit, manualActive) {
    const file = row.file;
    // 负责人独占编辑：can_edit 授权 且 该文件负责人（后端 can_edit_file
    // 同口径）；非负责人不渲染，避免点开必然被拒的入口
    const isAssignee = !!(canEdit && file.assignment && file.assignment.is_mine);
    return (
      <span>
        {isAssignee && manualActive && (
          file.revision_open ? (
            // 修订进行中：直接复用现有工作副本（绝不覆盖），不调状态接口
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              onClick={() => history.push(
                `/institution/manuals/${store.id}/draft?file=${file.id}`)}>
              继续编辑
            </AuthButton>
          ) : (
            // 已结束修订的开始修订是真实状态动作：先开启修订再进入工作台
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              onClick={() => this.handleStartRevision(file)}>
              开始修订
            </AuthButton>
          )
        )}
        {canEdit && manualActive && !isAssignee && (
          <Tooltip title="编辑仅限文件负责人（须持本手册编制资格）。你持编制授权但不是该文件负责人，请先由手册所有者指派分工。">
            <span style={{color: '#999', fontSize: 12}}>编辑限负责人</span>
          </Tooltip>
        )}
        {manualActive && file.assignment && file.assignment.is_mine && (
          <Button type="link" size="small"
            onClick={() => this.handleSubmitCompile(file)}>
            提交编制
          </Button>
        )}
        {isAssignee && this.renderDraftFileActions(file)}
        <AuthButton type="link" size="small"
          onClick={() => this.openFileHistory(file.id)}>
          变更记录
        </AuthButton>
      </span>
    );
  }

  /** 负责人单元格：有分工权限者点击姓名/「未分配」编辑，无权限只读 */
  renderOwnerCell(assignment, canAssign, file) {
    if (!assignment || !assignment.owner_id) {
      const unassigned = <Tag>未分配</Tag>;
      return canAssign ? (
        <a onClick={() => this.setState({assignmentFile: file})}
          title="点击指定负责人">未分配</a>
      ) : unassigned;
    }
    const note = assignment.note;
    const name = assignment.owner_name || '-';
    const body = note ? (
      <Tooltip title={`分工说明：${note}（点击修改分工）`}>
        <span>{name}</span>
      </Tooltip>
    ) : <span>{name}</span>;
    return canAssign ? (
      <a onClick={() => this.setState({assignmentFile: file})}
        title="点击修改分工">{body}</a>
    ) : body;
  }

  /** 提交编制状态单元格（submission 仅工作区可见者下发；前端只映射不推断）。
   *  提交是交接状态不是发布状态：有效=提交时修订号与当前草稿一致（预览
   *  草稿即为提交内容）；失效=草稿已更新且系统不保留提交时刻的文件副本
   *  （无历史快照机制），绝不提供"已提交版本"预览。 */
  renderSubmissionCell(file) {
    const submission = file.submission;
    if (!submission) return '-';
    const meta = SUBMISSION_META[submission.state] || SUBMISSION_META.none;
    const tipParts = [];
    if (submission.state === 'submitted') {
      tipParts.push(
        `${submission.submitted_by_name || '-'} 提交于 ${formatDateTime(submission.submitted_at)}`,
        `提交时修订号 r${submission.submission_revision} 与当前草稿 r${submission.draft_revision} 一致，预览待发布草稿即为提交时内容`,
        '提交编制仅是交接标记，不代表已发布生效；系统不保存提交时刻的文件副本');
    } else if (submission.state === 'stale') {
      tipParts.push(
        `提交已失效：原提交 r${submission.submission_revision}，草稿已更新至 r${submission.draft_revision}`,
        '系统不保留提交时刻的文件副本，无法查看提交时内容（预览打开的是当前草稿）',
        '请负责人确认后重新提交');
    }
    if (meta.tip) tipParts.push(meta.tip);
    return (
      <Tooltip title={tipParts.join('；')}>
        <Tag color={meta.color}>{meta.label}</Tag>
      </Tooltip>
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

  /** 草稿视图表格：顺序/文件名/大小/草稿修订/负责人/状态/编制提交/操作。
   *  预览与下载打开待发布草稿（仅编制角色），操作按修订状态分叉 */
  renderDraftTable(rows, {canEdit, canAssign, manualActive}) {
    const rowSelection = canAssign ? {
      selectedRowKeys: this.state.selectedKeys,
      onChange: keys => this.setState({selectedKeys: keys}),
      getCheckboxProps: () => ({disabled: false}),
    } : null;
    return (
      <Table rowKey="key" size="small" scroll={{x: true}}
        rowSelection={rowSelection}
        loading={store.isFetchingFiles}
        dataSource={rows} pagination={false}>
        <Table.Column title="顺序" width={55}
          render={(_, r, i) => i + 1}/>
        <Table.Column title="文件名" ellipsis
          render={(_, r) => r.file.name}/>
        <Table.Column title="大小" width={85}
          render={(_, r) => {
            const snapSize = r.snap && r.snap.file_size;
            return formatSize(snapSize != null
              ? snapSize : (r.file.draft && r.file.draft.file_size));
          }}/>
        <Table.Column title={
          <Tooltip title="当前待发布草稿的修订号：每次保存/重建 +1。提交编制按该修订号比对自动失效。">
            <span>草稿修订</span>
          </Tooltip>
        } width={95}
          render={(_, r) => (r.file.draft && r.file.draft.revision != null
            ? <Tag>r{r.file.draft.revision}</Tag> : '-')}/>
        <Table.Column title={
          <Tooltip title="负责人是当前责任归属：负责人独占编辑（须持本手册编制资格），同一文件同一时间仅一人可编辑（单写会话）。点击姓名可修改分工（仅所有者/制度管理员）。">
            <span>负责人</span>
          </Tooltip>
        } width={120}
          render={(_, r) => this.renderOwnerCell(
            r.file.assignment, canAssign, r.file)}/>
        <Table.Column title="状态" width={190}
          render={(_, r) => this.renderStateCell(r.file, r.relation)}/>
        <Table.Column title="编制提交" width={110}
          render={(_, r) => this.renderSubmissionCell(r.file)}/>
        <Table.Column title="操作" width={390} fixed="right"
          render={(_, r) => this.renderDraftRowActions(
            r, canEdit, manualActive)}/>
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
            ? '当前生效版本是最近一次发布形成的不可变清单：本视图的预览与下载始终打开该发布快照，不受草稿修改影响。修订中的待发布内容（含各文件负责人、草稿修订号、编制提交）请切换到「修订草稿」视图。'
            : '当前生效版本是最新一次发布形成的完整清单（不可变）：预览与下载始终打开该发布快照。各文件的发布参与与维护动作见「变更记录」，最初上传的原始文件在「初始来源」。'}
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

  /** 草稿视图：待发布工作内容（尚未生效）。草稿修订号/负责人/状态/
   *  编制提交集中呈现；预览与下载明确打开待发布草稿（负责人独占域） */
  renderDraftView({canEdit, canAssign, manualActive, rows}) {
    return (
      <div>
        <div style={{marginBottom: 8, color: '#666', fontSize: 12}}>
          本视图是待发布的工作内容（尚未生效）：预览与下载打开的是待发布草稿
          （行内标注修订号 rN），整套发布后才会成为新的生效版本。
          负责人是当前责任归属：编辑仅限文件负责人（须持本手册编制资格），
          单写会话（同一文件同一时间仅一人）；持编制授权但未被指派负责人的
          账号可查看清单，编辑前请先由手册所有者指派分工。
          提交编制是交接标记、不代表已发布：仅记录提交时的草稿修订号，系统
          不保存提交时刻的文件副本，草稿再次保存或重建后提交自动失效。
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
            message="该制度还没有待发布文件。请在「初始来源」页签上传原始文件（每份文件各建一个制度文件与草稿）。"/>
        )}
        {rows.length > 0 && this.renderDraftTable(rows,
          {canEdit, canAssign, manualActive})}
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
      canEdit, canAssign, manualActive, rows};
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
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          title={this.state.preview && this.state.preview.title}
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

function canPublishVisible(manual) {
  return (manual.my_roles || []).includes('publish');
}

export default FileListTab;
