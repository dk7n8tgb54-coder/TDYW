/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 版本与发布页签（2026-10-29 信息层级调整后聚焦整套发布历史；
 * 2026-10-29 交互优化：发布主入口上移到详情头部整套待发布状态旁
 * （PublishButton），本页签保留 发布历史/版本文件清单/整套回退/
 * 长期保留 标记）：
 * - 版本历史行展示文件总数，"查看文件清单"Modal 展示该版本完整文件集合，
 *   含新增/修改/沿用/本版本移除状态；被移除文件不静默隐藏。
 * - 已清理（保留策略）版本不提供 预览/下载/回退，仅存清单与哈希元数据。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message, Alert, Button, Tooltip } from 'antd';
import { AuthButton } from 'components';
import ManualAuthButton from '../ManualAuthButton';
import { http } from 'libs';
import { canViewPublished, downloadFile, formatSize, formatDateTime } from '../utils';
import PreviewModal from './PreviewModal';
import store from './store';

// 版本文件清单 Modal 的状态文案
const HISTORY_CHANGE_LABELS = {
  added: '新增', modified: '修改', unchanged: '沿用上一版本', removed: '本版本移除',
};
const CHANGE_COLORS = {
  added: 'blue', modified: 'orange', unchanged: 'default', removed: 'red',
};
// 整版文件清理状态（保留策略）文案
const CLEAN_STATUS_LABELS = {
  cleaned: '文件已按保留策略清理',
  partial: '部分文件已清理（不可完整回退）',
};

@observer
class VersionsTab extends React.Component {
  state = {preview: null, filesModal: null};

  showPreview = (request, fileName, title) => {
    request.then(data => {
      this.setState({preview: {
        url: data.preview_url, fileName: data.file_name || fileName, title,
      }});
    });
  };

  handleRollback = (version) => {
    // 整版文件已按保留策略清理（或部分清理）的版本不可作为回退基线
    if (version.files_cleaned_at) {
      message.warning('该版本的文件已按保留策略清理（部分或全部），无法整套回退');
      return;
    }
    Modal.confirm({
      title: `回退到 v${version.version_no}`,
      content: '整套回退：将以该版本的完整文件清单重建待发布草稿集合，当前草稿集合会被替换，进行中的编辑会话将失效。确认继续？',
      onOk: () => http.post(
        `/api/institution/manuals/${store.id}/draft/from-version/`,
        {version_id: version.id})
        .then(data => {
          const count = data && data.restored_files != null ? data.restored_files : 0;
          message.success(`已按该版本完整文件清单重建 ${count} 份待发布草稿，可进入草稿工作台继续编辑`);
          this.refresh();
        }),
    });
  };

  /** 重要版本长期保留标记：受保护版本不参与保留策略清理候选 */
  handleProtect = (version) => {
    const next = !version.long_term_protected;
    http.post(`/api/institution/manuals/${store.id}/versions/${version.id}/protect/`,
      {long_term_protected: next})
      .then(() => {
        message.success(next ? '已设为长期保留' : '已取消长期保留');
        store.fetchVersions(store.id, store.versionsPage || 1);
      });
  };

  // 版本行预览：单文件版本旧端点仍可用；多文件走清单 Modal 逐份预览
  handleVersionPreview = (v) => {
    const files = Array.isArray(v.files) ? v.files : [];
    if (files.length === 1) {
      const name = v.file_name || files[0].file_name;
      this.showPreview(
        http.get(`/api/institution/manuals/${store.id}/versions/${v.id}/preview-url/`),
        name, `预览历史版本 v${v.version_no}：${name}`);
      return;
    }
    this.openFilesModal(v);
  };

  // 版本行下载：单文件版本旧端点仍可用；多文件打开清单 Modal（避免旧端点的多文件拒绝）
  handleVersionDownload = (v) => {
    const files = Array.isArray(v.files) ? v.files : [];
    if (files.length === 1) {
      downloadFile(`/api/institution/manuals/${store.id}/versions/${v.id}/download/`,
        v.file_name || files[0].file_name);
      return;
    }
    this.openFilesModal(v);
  };

  openFilesModal = (v) => {
    this.setState({filesModal: {
      versionId: v.id, versionNo: v.version_no,
      items: [], removedItems: [], fetching: true,
    }});
    http.get(`/api/institution/manuals/${store.id}/versions/${v.id}/files/`)
      .then(data => {
        this.setState({filesModal: {
          versionId: data.version_id != null ? data.version_id : v.id,
          versionNo: data.version_no != null ? data.version_no : v.version_no,
          changeNote: data.change_note,
          previousVersionNo: data.previous_version_no,
          items: data.items || [],
          removedItems: data.removed_items || [],
          fetching: false,
        }});
      })
      .catch(() => this.setState({filesModal: null}));
  };

  refresh() {
    // 发布/回退/废止等生命周期动作后的统一刷新（详情/版本/操作记录/
    // 整套草稿状态/当前生效文件清单由 store.refreshAfterLifecycle 承担）
    store.refreshAfterLifecycle(store.id);
  }

  renderErrorAlert = (text, onRetry) => (
    <Alert type="error" showIcon style={{marginTop: 8}} message={text}
      action={<Button size="small" type="primary" onClick={onRetry}>重试</Button>}/>
  );

  renderChangeTag = (changeType, labels) => (
    <Tag color={CHANGE_COLORS[changeType] || 'default'}>
      {labels[changeType] || '-'}
    </Tag>
  );

  renderLatestChanged = (row) => (
    row.latest_changed_version_no != null ? `v${row.latest_changed_version_no}` : '-'
  );

  renderFileActions = (versionId, snapshotId, fileName, isCleaned, versionNo) => {
    if (isCleaned) {
      return <Tooltip title="该文件已按保留策略清理，仅存清单与哈希元数据">
        <Tag color="default">已清理</Tag>
      </Tooltip>;
    }
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.showPreview(
            http.get(`/api/institution/manuals/${store.id}/versions/${versionId}/files/${snapshotId}/preview-url/`),
            fileName, `预览历史版本 v${versionNo}：${fileName}`)}>预览</AuthButton>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          onClick={() => downloadFile(
            `/api/institution/manuals/${store.id}/versions/${versionId}/files/${snapshotId}/download/`,
            fileName)}>下载</AuthButton>
      </span>
    );
  };

  renderFilesModal() {
    const fm = this.state.filesModal || {};
    const items = fm.items || [];
    const removed = fm.removedItems || [];
    return (
      <Modal visible={!!this.state.filesModal}
        title={`版本文件清单${fm.versionNo != null ? `：v${fm.versionNo}` : ''}`}
        width={760} footer={null} destroyOnClose
        onCancel={() => this.setState({filesModal: null})}>
        {fm.changeNote && <p style={{marginBottom: 4}}>变更说明：{fm.changeNote}</p>}
        {fm.previousVersionNo != null && (
          <p style={{marginBottom: 8, color: '#999'}}>
            对比版本：v{fm.previousVersionNo}（变更状态由服务端按快照哈希计算）
          </p>
        )}
        <Table rowKey="id" size="small" loading={!!fm.fetching}
          dataSource={items} pagination={false}>
          <Table.Column title="顺序" width={55} render={(_, f, i) => i + 1}/>
          <Table.Column title="文件名" dataIndex="file_name" ellipsis/>
          <Table.Column title="变更" width={110}
            render={(_, f) => this.renderChangeTag(f.change_type, HISTORY_CHANGE_LABELS)}/>
          <Table.Column title="大小" dataIndex="file_size" width={80}
            render={v => formatSize(v)}/>
          <Table.Column title="哈希" dataIndex="file_hash" width={95}
            render={v => (v || '').slice(0, 8)}/>
          <Table.Column title="最近变更" width={90}
            render={(_, f) => this.renderLatestChanged(f)}/>
          <Table.Column title="操作" width={125}
            render={(_, f) => this.renderFileActions(
              fm.versionId, f.id, f.file_name, f.is_cleaned, fm.versionNo)}/>
        </Table>
        {removed.length > 0 && (
          <div style={{marginTop: 12}}>
            <Alert type="warning" showIcon style={{marginBottom: 8}}
              message={`本版本移除了 ${removed.length} 份文件（内容仍保留在上一版本 v${fm.previousVersionNo}，可从此处查阅）`}/>
            <Table rowKey="previous_snapshot_id" size="small"
              dataSource={removed} pagination={false}>
              <Table.Column title="文件名" dataIndex="name" ellipsis/>
              <Table.Column title="变更" width={110}
                render={() => this.renderChangeTag('removed', HISTORY_CHANGE_LABELS)}/>
              <Table.Column title="大小" dataIndex="file_size" width={80}
                render={v => formatSize(v)}/>
              <Table.Column title="哈希" dataIndex="file_hash" width={95}
                render={v => (v || '').slice(0, 8)}/>
              <Table.Column title="操作" width={125}
                render={(_, r) => this.renderFileActions(
                  r.previous_version_id, r.previous_snapshot_id, r.name,
                  false, fm.previousVersionNo)}/>
            </Table>
          </div>
        )}
      </Modal>
    );
  }

  render() {
    const manual = store.manual || {};
    // 发布历史属已发布内容（can_view_published 口径）：无权限时后端拒绝
    // 版本清单，详情页挂载链同样不发请求——此处显式说明而非空表冒充
    if (!canViewPublished(manual)) {
      return (
        <Alert type="info" showIcon style={{marginTop: 12}}
          message="发布历史属于已发布内容：当前账号无可查看发布版本的授权，版本清单不展示。"/>
      );
    }
    const canPublish = (manual.my_roles || []).includes('publish');
    // 整套回退业务门=手册所有者或平台超管（2026-10-31 二轮权限模型：
    // 所有者对象级全权；后端 DraftFromVersionView 同口径，manual_auth
    // 放行所有者）；
    // 「设为/取消长期保留」仍按发布授权（my_roles.publish，发布域操作
    // 不走管理权限码；所有者经 my_roles 下发与 ManualAuthButton 豁免）
    const canRollback = !!manual.is_owner || !!manual.is_admin;
    return (
      <div>
        {/* 发布主入口在详情头部整套待发布状态旁（PublishButton）；
            本页签聚焦发布历史与回退/长期保留 */}
        {store.versionsError && this.renderErrorAlert(store.versionsError,
          () => store.fetchVersions(store.id, store.versionsPage || 1))}
        <Table rowKey="id" size="middle"
          loading={store.isFetchingVersions}
          dataSource={store.versions}
          pagination={{current: store.versionsPage, pageSize: 10, total: store.versionsTotal,
            onChange: p => store.fetchVersions(store.id, p)}}>
          <Table.Column title="版本" dataIndex="version_no" width={70}
            render={v => `v${v}`}/>
          <Table.Column title="变更说明" dataIndex="change_note"/>
          <Table.Column title="文件清单" width={180}
            render={(_, v) => {
              const count = Array.isArray(v.files) ? v.files.length : 0;
              return (
                <span>
                  {count} 份
                  <AuthButton auth="institution.manual.view" type="link" size="small"
                    onClick={() => this.openFilesModal(v)}>查看文件清单</AuthButton>
                </span>
              );
            }}/>
          <Table.Column title="发布人" dataIndex="published_by_name" width={110}/>
          <Table.Column title="发布时间" dataIndex="published_at" width={150}
            render={v => formatDateTime(v)}/>
          <Table.Column title="状态" width={170}
            render={(_, v) => (
              <span>
                {v.is_current
                  ? <Tag color="green">生效中</Tag>
                  : (v.is_effective ? <Tag>历史</Tag> : <Tag color="red">已废止</Tag>)}
                {v.long_term_protected && <Tag color="purple">长期保留</Tag>}
                {CLEAN_STATUS_LABELS[v.files_clean_status] && (
                  <Tooltip title={v.files_clean_status === 'partial'
                    ? (v.files_clean_error || '部分快照清理失败，可重试；整版不可完整回退')
                    : '该版本文件已按保留策略清理，仅存清单与哈希元数据'}>
                    <Tag color={v.files_clean_status === 'cleaned' ? 'red' : 'orange'}>
                      {CLEAN_STATUS_LABELS[v.files_clean_status]}
                    </Tag>
                  </Tooltip>
                )}
              </span>
            )}/>
          <Table.Column title="操作" width={250}
            render={(_, v) => {
              const cleaned = !!v.files_cleaned_at;
              return (
                <span>
                  {!cleaned && (
                    <span>
                      <AuthButton auth="institution.manual.view" type="link" size="small"
                        onClick={() => this.handleVersionPreview(v)}>预览</AuthButton>
                      <AuthButton auth="institution.manual.download" type="link" size="small"
                        onClick={() => this.handleVersionDownload(v)}>下载</AuthButton>
                    </span>
                  )}
                  {cleaned && (
                    <Tooltip title="该版本文件已按保留策略清理，预览/下载/回退不可用">
                      <Tag color="default">文件已清理</Tag>
                    </Tooltip>
                  )}
                  {canRollback && !cleaned && (
                    <ManualAuthButton manual={manual} auth="institution.manual.draft_edit"
                      type="link" size="small"
                      onClick={() => this.handleRollback(v)}>从历史版本回退</ManualAuthButton>
                  )}
                  {canPublish && !v.is_current && (
                    <ManualAuthButton manual={manual} auth="institution.manual.publish"
                      type="link" size="small"
                      onClick={() => this.handleProtect(v)}>
                      {v.long_term_protected ? '取消长期保留' : '设为长期保留'}
                    </ManualAuthButton>
                  )}
                </span>
              );
            }}/>
        </Table>
        {this.renderFilesModal()}
        <PreviewModalForTab state={this.state} onClose={() => this.setState({preview: null})}/>
      </div>
    );
  }
}

function PreviewModalForTab({state, onClose}) {
  return <PreviewModal visible={!!state.preview} url={state.preview && state.preview.url}
    fileName={state.preview && state.preview.fileName}
    title={state.preview && state.preview.title} onClose={onClose}/>;
}

export default VersionsTab;
