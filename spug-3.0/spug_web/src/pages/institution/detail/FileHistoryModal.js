/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 文件历史弹窗（2026-11-01 简化版）：文件清单行「文件历史」的唯一打开方式
 * （「当前生效版本」与「修订草稿」两种视图的行入口共用）。弹窗始终按
 * file_id 定位同一份制度文件，标题为该制度文件名，内部只有两个子页签：
 * - 发布记录：该文件参与了哪些发布版本、每次相对上一版本的变化（服务端
 *   按快照哈希计算）；被移除期间的版本不出现。属已发布内容
 *   （can_view_published），无权限时不发 version-history 请求，子页签
 *   仅提示；已按保留策略清理的快照只显示元数据与「已清理」，绝不渲染
 *   会失败的预览/下载入口。
 * - 操作记录：针对该文件的草稿与维护动作（后端 file_id 过滤 + 分页）；
 *   完整时间线见顶层「操作记录」页签。
 * 历史上传记录与「从历史上传文件重建草稿」能力已整体删除：本弹窗不提供
 * 历史来源/重建/更换来源/上传 任何入口。
 * 每次打开（含连续打开不同文件）都按当前 file_id 重新加载；切换文件先
 * store.clearFileRecords 防旧记录残留（同文件重复打开不额外清空），
 * fetchFileVersionHistory/fetchFileLogs 的 reqSeq 守卫保证快速切换时
 * 迟到响应不覆盖当前文件；打开弹窗不触碰清单视图、滚动位置与行勾选。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Alert, Tooltip, Tabs, Modal } from 'antd';
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
class FileHistoryModal extends React.Component {
  state = {preview: null};

  componentDidMount() {
    if (this.props.visible) this.loadFor(this.props.fileId);
  }

  componentDidUpdate(prevProps) {
    // 打开瞬间（含换了文件再打开）都重新加载；已打开期间 file_id 变化
    // 同样按新文件重取，绝不展示上一文件的数据
    if (!this.props.visible) return;
    if (!prevProps.visible || prevProps.fileId !== this.props.fileId) {
      this.loadFor(this.props.fileId);
    }
  }

  componentWillUnmount() {
    this.unmounted = true;
  }

  /** 按文件加载两类记录；先清空上一文件数据，loading 期间不残留旧内容 */
  loadFor(fileId) {
    if (fileId == null) return;
    if (this.loadedFileId !== fileId) store.clearFileRecords();
    this.loadedFileId = fileId;
    // 发布记录属已发布内容：无 can_view_published 口径权限时不发请求
    // （后端同口径拒绝，前端不产生注定失败的调用）
    if (canViewPublished(store.manual)) {
      store.fetchFileVersionHistory(store.id, fileId);
    }
    store.fetchFileLogs(store.id, fileId, 1).catch(() => {});
  }

  showPreview = (versionId, snapshotId, fileName, title) => {
    http.get(
      `/api/institution/manuals/${store.id}/versions/${versionId}/files/${snapshotId}/preview-url/`)
      .then(data => {
        this.setState({preview: {
          url: data.preview_url, fileName: data.file_name || fileName, title,
        }});
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
    const name = fileName || '该版本文件';
    return (
      <span>
        <AuthButton auth="institution.manual.view" type="link" size="small"
          onClick={() => this.showPreview(r.version_id, r.snapshot_id, name,
            `预览历史版本 v${r.version_no}：${name}`)}>预览</AuthButton>
        <AuthButton auth="institution.manual.download" type="link" size="small"
          onClick={() => downloadFile(
            `/api/institution/manuals/${store.id}/versions/${r.version_id}/files/${r.snapshot_id}/download/`,
            fileName || 'file.docx')}>下载</AuthButton>
      </span>
    );
  };

  /** 发布记录子页签内容（仅 can_view_published 通过者渲染） */
  renderPublishPane() {
    const fv = store.fileVersion;
    const fileId = this.props.fileId;
    return (
      <div>
        <div style={{marginBottom: 8, color: '#999', fontSize: 12}}>
          该文件在历次发布中的内容变化（与相邻上一版本按快照哈希比较）
        </div>
        {store.fileVersionError && (
          <Alert type="error" showIcon style={{marginBottom: 8}}
            message={store.fileVersionError}
            action={<AuthButton auth="institution.manual.view" size="small" type="primary"
              onClick={() => store.fetchFileVersionHistory(store.id, fileId)}>重试</AuthButton>}/>
        )}
        <Table rowKey="version_id" size="small" scroll={{x: true}}
          loading={store.isFetchingFileVersion}
          locale={{emptyText: '该文件尚未参与任何发布版本'}}
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

  /** 操作记录子页签内容：该文件的草稿与维护动作（分页携带当前 file_id） */
  renderLogsPane() {
    return (
      <div>
        <div style={{marginBottom: 8, color: '#999', fontSize: 12}}>
          仅「{this.props.fileName || '该文件'}」的操作，完整时间线见顶层
          「操作记录」页签
        </div>
        <Table rowKey="id" size="small" scroll={{x: true}}
          loading={store.isFetchingFileLogs}
          locale={{emptyText: '该文件暂无操作记录'}}
          dataSource={store.fileLogs}
          pagination={{current: store.fileLogsPage, pageSize: 15,
            total: store.fileLogsTotal,
            onChange: p => store.fetchFileLogs(store.id, this.props.fileId, p)
              .catch(() => {})}}>
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
    );
  }

  render() {
    const manual = store.manual || {};
    const canViewPub = canViewPublished(manual);
    const name = this.props.fileName || '';
    return (
      <Modal visible={this.props.visible} width={900}
        title={`文件历史：${name}`} footer={null} destroyOnClose
        onCancel={this.props.onClose}>
        {this.props.fileId != null && (
          <Tabs size="small" defaultActiveKey={canViewPub ? 'publish' : 'logs'}>
            <Tabs.TabPane tab="发布记录" key="publish">
              {canViewPub ? this.renderPublishPane() : (
                <Alert type="info" showIcon
                  message="当前账号不可查看该制度的发布记录，仅可查看操作记录。"/>
              )}
            </Tabs.TabPane>
            <Tabs.TabPane tab="操作记录" key="logs">
              {this.renderLogsPane()}
            </Tabs.TabPane>
          </Tabs>
        )}
        <PreviewModal visible={!!this.state.preview} url={this.state.preview && this.state.preview.url}
          fileName={this.state.preview && this.state.preview.fileName}
          title={this.state.preview && this.state.preview.title}
          onClose={() => this.setState({preview: null})}/>
      </Modal>
    );
  }
}

export default FileHistoryModal;
