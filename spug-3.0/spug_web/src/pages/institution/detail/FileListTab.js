/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件清单页签（详情页默认页签，2026-10-30 修订状态交互优化）：
 * 日常清单保持简单——顺序/文件名/大小/负责人/状态/编制提交/主要操作；
 * 修订号、工作副本来源与"草稿 vs 生效版本"等细节放草稿工作台详情与
 * 变更记录。状态列由服务端计算的 内容关系（draft-status）+ 修订进行中
 * （revision_open 显式状态）合并为一句可懂短语：
 * - 已生效（无未发布修改）→ 行操作显示「开始修订」（真实状态动作：
 *   开启新一轮修订并复用现有工作副本；工作副本缺失/损坏/与生效基线
 *   不一致时明确提示并经确认从当前生效版本快照修复）；
 * - 修订进行中 → 「继续编辑」直接复用，绝不覆盖；
 * - 草稿未就绪（.doc 转换失败等）→ 明确提示，文件已上传但暂不可发布。
 * 文件分工：负责人列直接点击姓名/「未分配」编辑（有分工权限者），
 * 只读展示（无权限者）；支持勾选多份文件批量指定/清空负责人
 * （全成功或全失败，服务端逐文件校验归属）；操作列不再有「文件分工」
 * 链接。提交编制仍仅行内负责人（is_mine）可见。
 * 数据源（均为服务端权威计算，前端只展示、不推断）：
 * - /files/：待发布集合 + 修订状态 + 文件分工（草稿与提交状态仅工作区
 *   可见者返回；负责人为责任信息对所有可见者下发）
 * - /draft-status/：逐份内容关系与整套摘要（服务端按哈希/名称/序位计算）
 * - /versions/<vid>/files/：生效快照（预览/下载走当前生效版本端点）
 * 行来源按权限分口径：工作区可见者以待发布集合为行（含未进入生效版本
 * 的新增文件）；仅查看角色以生效快照为行（不泄漏草稿信息）。
 * 加载失败置错误态可重试，绝不以空清单或"无变化"冒充；已清理快照
 * 只显示元数据，不提供会失败的预览/下载。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message, Alert, Button, Tooltip, Checkbox } from 'antd';
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

// 提交编制状态文案（服务端 submission.state：none/submitted/stale）
const SUBMISSION_META = {
  none: {label: '未提交', color: 'default',
    tip: '负责人完成编制后可在此提交（记录提交时的草稿修订号）'},
  submitted: {label: '已提交', color: 'green', tip: null},
  stale: {label: '提交已失效', color: 'orange',
    tip: '提交后草稿已再次保存或重建，请负责人确认后重新提交'},
};

@observer
class FileListTab extends React.Component {
  state = {
    preview: null, assignmentFile: null, batchAssign: false,
    onlyMine: false, selectedKeys: [],
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

  showPreview = (request, fileName) => {
    request.then(data => {
      this.setState({preview: {url: data.preview_url, fileName: data.file_name || fileName}});
    });
  };

  /** 从文件行跳到"文件变更记录"页签并预选该文件（父级切页签） */
  openFileHistory = (fileId) => {
    store.fileChangeTarget = fileId;
    if (this.props.onOpenFileHistory) this.props.onOpenFileHistory();
  };

  /** 预览/下载走当前生效版本的快照端点；无快照或已清理不渲染入口 */
  renderSnapshotActions(snap, cf) {
    if (!snap || !cf || snap.is_cleaned) return null;
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.showPreview(
            http.get(`/api/institution/manuals/${store.id}/versions/${cf.version_id}/files/${snap.id}/preview-url/`),
            snap.file_name)}>预览</AuthButton>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          onClick={() => downloadFile(
            `/api/institution/manuals/${store.id}/versions/${cf.version_id}/files/${snap.id}/download/`,
            snap.file_name)}>下载</AuthButton>
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

  /** 行操作：预览/下载（生效快照）+ 开始修订/继续编辑（编制角色）+
   *  提交编制（负责人）+ 变更记录；文件分工入口在负责人列 */
  renderRowActions(row, cf, canEdit, manualActive) {
    const isCleaned = !!(row.snap && row.snap.is_cleaned);
    const isActive = row.kind === 'active';
    return (
      <span>
        {isCleaned && (
          <Tooltip title="该文件快照已按保留策略清理，仅存清单与哈希元数据">
            <Tag color="default">已清理</Tag>
          </Tooltip>
        )}
        {!isCleaned && this.renderSnapshotActions(row.snap, cf)}
        {isActive && canEdit && manualActive && (
          row.file.revision_open ? (
            // 修订进行中：直接复用现有工作副本（绝不覆盖），不调状态接口
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              onClick={() => history.push(
                `/institution/manuals/${store.id}/draft?file=${row.file.id}`)}>
              继续编辑
            </AuthButton>
          ) : (
            // 已结束修订的开始修订是真实状态动作：先开启修订再进入工作台
            <AuthButton auth="institution.manual.draft_edit" type="link" size="small"
              onClick={() => this.handleStartRevision(row.file)}>
              开始修订
            </AuthButton>
          )
        )}
        {isActive && manualActive && row.file.assignment &&
          row.file.assignment.is_mine && (
          <Button type="link" size="small"
            onClick={() => this.handleSubmitCompile(row.file)}>
            提交编制
          </Button>
        )}
        <AuthButton type="link" size="small"
          onClick={() => this.openFileHistory(
            row.kind === 'active' ? row.file.id : row.snap.manual_file_id)}>
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

  /** 提交编制状态单元格（submission 仅工作区可见者下发；前端只映射不推断） */
  renderSubmissionCell(file) {
    const submission = file.submission;
    if (!submission) return '-';
    const meta = SUBMISSION_META[submission.state] || SUBMISSION_META.none;
    const tipParts = [];
    if (submission.state === 'submitted') {
      tipParts.push(
        `${submission.submitted_by_name || '-'} 提交于 ${formatDateTime(submission.submitted_at)}`,
        `提交时修订号 r${submission.submission_revision}`);
    } else if (submission.state === 'stale') {
      tipParts.push(
        `原提交 r${submission.submission_revision}，当前草稿已更新至 r${submission.draft_revision}`);
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

  renderRemovedSection(cf) {
    const status = store.draftStatus;
    if (!status) return null;
    const removed = status.removed_items || [];
    if (!removed.length) return null;
    const snapByFileId = {};
    if (cf && Array.isArray(cf.items)) {
      cf.items.forEach(s => { snapByFileId[s.manual_file_id] = s; });
    }
    const rows = removed.map(r => ({
      ...r, snapshot: snapByFileId[r.file_id] || null,
    }));
    return (
      <div style={{marginTop: 16}}>
        <Alert type="warning" showIcon style={{marginBottom: 8}}
          message={`已移除 ${removed.length} 份文件（仍保留在当前生效版本 v${status.current_version_no} 中，发布新版本后将不再包含；可从此处查阅，也可通过整套回退重新纳入）`}/>
        <Table rowKey="file_id" size="small" dataSource={rows} pagination={false}>
          <Table.Column title="文件名" dataIndex="name" ellipsis/>
          <Table.Column title="大小" dataIndex="file_size" width={85}
            render={v => formatSize(v)}/>
          <Table.Column title="哈希" dataIndex="file_hash" width={95}
            render={v => (v || '').slice(0, 8)}/>
          <Table.Column title="操作" width={125}
            render={(_, r) => (r.snapshot ? this.renderSnapshotActions(r.snapshot, cf) : '-')}/>
        </Table>
      </div>
    );
  }

  /** 行构建：工作区可见者=待发布集合为行；仅查看者=生效快照为行。 */
  buildRows(workspace, cf) {
    const snapByFileId = {};
    if (cf && Array.isArray(cf.items)) {
      cf.items.forEach(s => { snapByFileId[s.manual_file_id] = s; });
    }
    const relationByFileId = {};
    if (store.draftStatus && Array.isArray(store.draftStatus.items)) {
      store.draftStatus.items.forEach(x => { relationByFileId[x.file_id] = x; });
    }
    // 文件分工按文件条目 ID 连接（负责人对所有可见者下发）
    const assignmentByFileId = {};
    (store.files || []).forEach(f => { assignmentByFileId[f.id] = f.assignment || null; });
    let rows;
    if (workspace) {
      rows = (store.files || []).map(f => ({
        kind: 'active', key: `f-${f.id}`, file: f,
        snap: snapByFileId[f.id], relation: relationByFileId[f.id],
      }));
    } else {
      rows = ((cf && Array.isArray(cf.items)) ? cf.items : []).map(s => ({
        kind: 'snapshot', key: `s-${s.id}`, snap: s,
        assignment: assignmentByFileId[s.manual_file_id] || null,
      }));
    }
    const mineCount = rows.filter(
      r => r.assignment ? r.assignment.is_mine :
        (r.file && r.file.assignment && r.file.assignment.is_mine)).length;
    return {rows, mineCount};
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

  renderTable(rows, {viewPublished, workspace, cf, canEdit, canAssign,
    manualActive}) {
    const rowSelection = canAssign ? {
      selectedRowKeys: this.state.selectedKeys,
      onChange: keys => this.setState({selectedKeys: keys}),
      getCheckboxProps: r => ({disabled: r.kind !== 'active'}),
    } : null;
    return (
      <Table rowKey="key" size="small" scroll={{x: true}}
        rowSelection={rowSelection}
        loading={workspace ? store.isFetchingFiles : store.isFetchingCurrentFiles}
        dataSource={rows} pagination={false}>
        <Table.Column title="顺序" width={55}
          render={(_, r, i) => i + 1}/>
        <Table.Column title="文件名" ellipsis
          render={(_, r) => (r.kind === 'active'
            ? r.file.name : r.snap.file_name)}/>
        <Table.Column title="大小" width={85}
          render={(_, r) => {
            if (r.kind === 'snapshot') return formatSize(r.snap.file_size);
            const snapSize = r.snap && r.snap.file_size;
            return formatSize(snapSize != null
              ? snapSize : (r.file.draft && r.file.draft.file_size));
          }}/>
        <Table.Column title="负责人" width={120}
          render={(_, r) => this.renderOwnerCell(
            r.kind === 'active' ? r.file.assignment : r.assignment,
            canAssign && r.kind === 'active',
            r.kind === 'active' ? r.file : null)}/>
        {workspace && (
          <Table.Column title="状态" width={190}
            render={(_, r) => (r.kind === 'active'
              ? this.renderStateCell(r.file, r.relation) : '-')}/>
        )}
        {workspace && (
          <Table.Column title="编制提交" width={110}
            render={(_, r) => (r.kind === 'active'
              ? this.renderSubmissionCell(r.file) : '-')}/>
        )}
        <Table.Column title="操作" width={260} fixed="right"
          render={(_, r) => this.renderRowActions(
            r, cf, canEdit, manualActive)}/>
      </Table>
    );
  }

  render() {
    const manual = store.manual || {};
    const viewPublished = canViewPublished(manual);
    const workspace = canViewWorkspace(manual);
    const canEdit = (manual.my_roles || []).includes('edit');
    // 分工口径与后端写接口完全一致：@auth draft_edit 页面权限 +
    // （管理权限或手册编制角色，对应 _check_manage_or_edit_role）。
    // 缺 draft_edit 时保存必然被"权限拒绝"，入口必须保持只读
    const canAssign = hasPermission('institution.manual.draft_edit') &&
      (canEdit || hasPermission('institution.manual.edit') ||
        hasPermission('institution.manual.config'));
    const current = manual.current_version;
    const manualActive = manual.status === 'active';
    const cf = store.currentFiles;

    let {rows, mineCount} = this.buildRows(workspace, cf);
    // 「只看我负责的文件」筛选（编制者视角；行内负责人由服务端 is_mine 判定）。
    // 筛选切换同时清空勾选：不得对筛选后不可见的文件批量操作
    if (this.state.onlyMine) {
      rows = rows.filter(r => r.assignment ? r.assignment.is_mine :
        (r.file && r.file.assignment && r.file.assignment.is_mine));
    }

    return (
      <div>
        <div style={{marginBottom: 8, color: '#666', fontSize: 12}}>
          {workspace
            ? '制度以当前生效版本为准；修订（编辑）某份文件用行内「开始修订/继续编辑」进入草稿工作台，完成后在页面顶部发布整套。负责人列可点击修改分工，勾选多份文件可批量分工。修订号、工作副本来源与历史比较见草稿工作台与「变更记录」。'
            : '当前生效文件是最新一次发布形成的完整清单（不可变），逐份预览/下载即为最新内容；各文件的发布参与与维护动作见「变更记录」，最初上传的原始文件在「初始来源」。'}
        </div>
        {workspace && (
          <div style={{marginBottom: 8}}>
            <Checkbox checked={this.state.onlyMine}
              onChange={e => this.setState(
                {onlyMine: e.target.checked, selectedKeys: []})}>
              只看我负责的文件{mineCount > 0 ? `（${mineCount}）` : ''}
            </Checkbox>
          </div>
        )}
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
            message="该制度暂无生效版本。已发布的版本废止后此处为空；当前编辑内容见下方待发布清单，发布后在「版本与发布」生成新的生效版本。"/>
        )}
        {workspace && store.draftStatusError && (
          <Alert type="warning" showIcon style={{marginBottom: 8}}
            message="草稿与生效版本的关系加载失败，无法确认各文件是否有未发布变化"
            action={<Button size="small" type="primary"
              onClick={() => store.fetchDraftStatus(store.id)}>重试</Button>}/>
        )}
        {workspace && canAssign && this.renderBatchBar(rows)}
        {workspace && rows.length === 0 && !store.isFetchingFiles && (
          <Alert type="info" showIcon
            message="该制度还没有待发布文件。请在「初始来源」页签上传原始文件（每份文件各建一个制度文件与草稿）。"/>
        )}
        {rows.length > 0 && this.renderTable(rows,
          {viewPublished, workspace, cf, canEdit, canAssign, manualActive})}
        {workspace && this.renderRemovedSection(cf)}
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
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

function canPublishVisible(manual) {
  return (manual.my_roles || []).includes('publish');
}

export default FileListTab;
