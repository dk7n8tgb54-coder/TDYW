/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件变更记录页签（按具体文件回看，2026-10-29 信息层级调整；
 * 2026-10-29 交互优化：文件下拉改用 originals-overview 全集——
 * 已从待发布集合移除的文件同样可选，变更记录必须能找到它们；
 * 按保留策略清理的快照行只显示元数据与"已清理"状态，不渲染
 * 会失败的预览/下载按钮）：
 * - 发布记录：该文件参与了哪些发布版本、每次相对上一版本的变化
 *   （新增/修改/沿用，服务端按快照哈希计算）；被移除期间的版本不出现。
 * - 操作记录：针对该文件的草稿与维护动作（后端 file_id 过滤 + 分页）。
 * 发布记录属已发布内容（can_view_published），无权限时只展示操作记录。
 * 文件清单行「变更记录」经 store.fileChangeTarget 直达本页签并预选；
 * 页签保持挂载期间再次跳转由 reaction 消费新目标（2026-10-30 修复：
 * 此前仅 componentDidMount 消费，页签已挂载时二次跳转不生效）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { reaction } from 'mobx';
import { Table, Tag, Select, Alert, Tooltip } from 'antd';
import { AuthButton } from 'components';
import { http } from 'libs';
import { downloadFile, formatSize, formatDateTime, canViewPublished } from '../utils';
import { oplogActionLabel, oplogActionHighlight, renderOplogDetail } from './oplogShared';
import PreviewModal from './PreviewModal';
import store from './store';

const CHANGE_LABELS = {
  added: '新增', modified: '修改', unchanged: '沿用上一版本',
};
const CHANGE_COLORS = {added: 'blue', modified: 'orange', unchanged: 'default'};

@observer
class FileChangeTab extends React.Component {
  state = {fileId: null, preview: null};

  componentDidMount() {
    // 全部制度文件行（含已移除条目，一次聚合请求）；失败置错误态可重试
    // （store 记录 originalsOverviewError，拦截器已提示），不冒充成功
    store.fetchOriginalsOverview(store.id)
      .then(() => this.syncSelection())
      .catch(() => {});
    // 页签首次激活后保持挂载（rc-tabs 默认），文件清单行再次「变更记录」
    // 时不会重新执行 componentDidMount——用 reaction 感知 store
    // .fileChangeTarget 变化并消费（与 React 渲染时机解耦，页签未重新
    // 挂载同样生效；快速连续切换时目标值变化才触发，最新值在加载完成后
    // 由 syncSelection 统一解析）
    this.disposeTargetReaction = reaction(
      () => store.fileChangeTarget,
      () => this.syncSelection(),
      {fireImmediately: true},
    );
  }

  componentWillUnmount() {
    if (this.disposeTargetReaction) {
      this.disposeTargetReaction();
      this.disposeTargetReaction = null;
    }
    this.unmounted = true;
  }

  /**
   * 统一选中决策（可重复调用，幂等）：优先消费文件清单行「变更记录」的
   * 跳转目标——全集加载中或加载失败时保留目标，待加载/重试成功后再解析；
   * 目标不在全集中时回退首个文件（下拉可见回退结果，绝不把旧文件的记录
   * 冒充目标文件）；无目标且尚未选中时选中首个文件。
   */
  syncSelection() {
    if (this.unmounted) return;
    const files = store.originalsOverview || [];
    const target = store.fileChangeTarget;
    if (target != null) {
      if (store.isFetchingOriginalsOverview) return;
      if (!files.length) {
        // 加载失败保留目标待重试；空制度目标无处落地则丢弃
        if (store.originalsOverviewError) return;
        store.fileChangeTarget = null;
        return;
      }
      store.fileChangeTarget = null;
      if (!files.some(f => f.file_id === target)) {
        this.selectFile(files[0].file_id);
        return;
      }
      this.selectFile(target);
      return;
    }
    if (this.state.fileId == null && files.length &&
        !store.isFetchingOriginalsOverview) {
      this.selectFile(files[0].file_id);
    }
  }

  selectFile = (fileId) => {
    // 切换文件即清空上一份的记录：loading 期间不残留上一文件的数据
    // （重复选中同一文件不清空，保持已展示内容）
    if (this.state.fileId !== fileId) store.clearFileRecords();
    this.setState({fileId});
    // 发布记录属已发布内容：无 can_view_published 口径权限时不发请求
    // （后端同口径拒绝，前端不产生注定失败的调用）
    if (canViewPublished(store.manual)) {
      store.fetchFileVersionHistory(store.id, fileId);
    }
    store.fetchFileLogs(store.id, fileId, 1);
  };

  showPreview = (versionId, snapshotId, fileName) => {
    http.get(
      `/api/institution/manuals/${store.id}/versions/${versionId}/files/${snapshotId}/preview-url/`)
      .then(data => {
        this.setState({preview: {url: data.preview_url, fileName: data.file_name || fileName}});
      });
  };

  /** 已清理快照仅存元数据：不渲染会失败的预览/下载入口 */
  renderHistoryActions = (r, fileName) => {
    if (r.is_cleaned) {
      return (
        <Tooltip title="该文件快照已按保留策略清理，仅存清单与哈希元数据">
          <Tag color="default">已清理</Tag>
        </Tooltip>
      );
    }
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.showPreview(r.version_id, r.snapshot_id, '该版本文件')}>预览</AuthButton>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          onClick={() => downloadFile(
            `/api/institution/manuals/${store.id}/versions/${r.version_id}/files/${r.snapshot_id}/download/`,
            fileName || 'file.docx')}>下载</AuthButton>
      </span>
    );
  };

  renderOriginalsError() {
    return (
      <Alert type="error" showIcon style={{marginBottom: 12}}
        message={store.originalsOverviewError || '制度文件清单加载失败，请重试'}
        action={<AuthButton auth="institution.manual.view" size="small" type="primary"
          onClick={() => store.fetchOriginalsOverview(store.id)
            .then(() => this.syncSelection())
            .catch(() => {})}>重试</AuthButton>}/>
    );
  }

  renderPublishSection(canViewPub) {
    if (!canViewPub) {
      return (
        <Alert type="info" showIcon style={{marginBottom: 16}}
          message="当前账号不可查看该制度的发布记录，仅展示操作记录。"/>
      );
    }
    const fv = store.fileVersion;
    return (
      <div style={{marginBottom: 20}}>
        <div style={{marginBottom: 8}}>
          <strong>发布记录</strong>
          <span style={{color: '#999', fontSize: 12, marginLeft: 8}}>
            该文件在历次发布中的内容变化（与相邻上一版本按快照哈希比较）
          </span>
        </div>
        {store.fileVersionError && (
          <Alert type="error" showIcon style={{marginBottom: 8}}
            message={store.fileVersionError}
            action={<AuthButton auth="institution.manual.view" size="small" type="primary"
              onClick={() => this.state.fileId &&
                store.fetchFileVersionHistory(store.id, this.state.fileId)}>重试</AuthButton>}/>
        )}
        <Table rowKey="version_id" size="small"
          loading={store.isFetchingFileVersion}
          dataSource={(fv && fv.items) || []} pagination={false}>
          <Table.Column title="版本" dataIndex="version_no" width={70}
            render={v => `v${v}`}/>
          <Table.Column title="该文件变化" width={110}
            render={(_, r) => (
              <Tag color={CHANGE_COLORS[r.change_type] || 'default'}>
                {CHANGE_LABELS[r.change_type] || r.change_type || '-'}
              </Tag>)}/>
          <Table.Column title="变更说明" dataIndex="change_note" ellipsis/>
          <Table.Column title="大小" dataIndex="file_size" width={85}
            render={v => formatSize(v)}/>
          <Table.Column title="哈希" dataIndex="file_hash" width={95}
            render={v => (v || '').slice(0, 8)}/>
          <Table.Column title="发布人" dataIndex="published_by_name" width={110}/>
          <Table.Column title="发布时间" dataIndex="published_at" width={150}
            render={v => formatDateTime(v)}/>
          <Table.Column title="操作" width={125}
            render={(_, r) => this.renderHistoryActions(
              r, (store.fileVersion && store.fileVersion.file_name) || 'file.docx')}/>
        </Table>
      </div>
    );
  }

  render() {
    const manual = store.manual || {};
    const canViewPub = canViewPublished(manual);
    const files = store.originalsOverview || [];
    const selected = files.find(f => f.file_id === this.state.fileId);
    return (
      <div>
        <div style={{marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8}}>
          <span>制度文件：</span>
          <Select value={this.state.fileId} style={{width: 360}}
            placeholder="选择制度文件" onChange={this.selectFile}>
            {files.map(f => (
              <Select.Option key={f.file_id} value={f.file_id}>
                {f.name}
                {f.is_removed && <Tag color="red" style={{marginLeft: 6}}>已移除</Tag>}
              </Select.Option>
            ))}
          </Select>
          {selected && selected.is_removed && (
            <span style={{color: '#999', fontSize: 12}}>
              该文件已从待发布集合移除；历史发布记录与操作记录仍可回看。
            </span>
          )}
        </div>
        {store.originalsOverviewError && this.renderOriginalsError()}
        <div style={{marginBottom: 12, color: '#666', fontSize: 12}}>
          按文件回看：发布记录是该文件在各生效版本中的内容变化；
          操作记录是针对该文件的草稿与维护动作（创建/保存/恢复/改名/移除等）。
          已从待发布集合移除的文件同样在此列示。
        </div>
        {files.length === 0 && !store.isFetchingOriginalsOverview &&
          !store.originalsOverviewError && (
          <Alert type="info" showIcon style={{marginBottom: 12}}
            message="该制度还没有制度文件，请先在「初始来源」页签上传。"/>
        )}
        {selected && this.renderPublishSection(canViewPub)}
        {selected && (
          <div>
            <div style={{marginBottom: 8}}>
              <strong>操作记录</strong>
              <span style={{color: '#999', fontSize: 12, marginLeft: 8}}>
                仅「{selected.name}」的操作，完整时间线见「操作记录」页签
              </span>
            </div>
            <Table rowKey="id" size="small"
              loading={store.isFetchingFileLogs}
              dataSource={store.fileLogs}
              pagination={{current: store.fileLogsPage, pageSize: 15,
                total: store.fileLogsTotal,
                onChange: p => store.fetchFileLogs(store.id, selected.file_id, p)}}>
              <Table.Column title="时间" dataIndex="created_at" width={160}
                render={v => formatDateTime(v)}/>
              <Table.Column title="操作账号" dataIndex="user_name" width={130}
                render={v => v || '-'}/>
              <Table.Column title="动作" dataIndex="action" width={130}
                render={v => (oplogActionHighlight(v)
                  ? <Tag color="orange">{oplogActionLabel(v)}</Tag>
                  : <Tag>{oplogActionLabel(v)}</Tag>)}/>
              <Table.Column title="详情" render={(_, record) => renderOplogDetail(record)}/>
            </Table>
          </div>
        )}
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

export default FileChangeTab;
