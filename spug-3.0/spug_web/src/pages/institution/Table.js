/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { history } from 'libs';
import { AuthButton, TableCard, Action } from 'components';
import { Table, Tag, Modal, Tooltip, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http } from 'libs';
import store from './store';

const STATUS_COLORS = {active: 'green', archived: 'default'};

// 列表工作状态（后端 work_status，服务端按 草稿哈希 vs 生效快照 与
// 文件新增/移除/改名/排序 计算；前端只做文案映射，不得以修订号或
// "有草稿"自行推断）。work_status 仅对具备草稿访问权的账号下发，
// 仅查看角色为 null（显示 '-'，不展示任何草稿语义）。
const WORK_STATUS_META = {
  synced: {color: 'green', label: '已生效'},
  awaiting_first_publish: {color: 'gold', label: '待首次发布'},
  pending_changes: {color: 'orange', label: '待发布变化'},
  revising: {color: 'orange', label: '修订进行中'},
  editing: {color: 'blue', label: '编辑中'},
  missing_draft: {color: 'red', label: '缺少草稿'},
  unverifiable: {color: 'volcano', label: '状态无法确认'},
  no_files: {color: 'default', label: '未上传文件'},
};

function workStatusDetail(ws) {
  const parts = [];
  if (ws.status === 'synced' && ws.current_version_no != null) {
    parts.push(`v${ws.current_version_no} 无未发布修改`);
  }
  if (ws.status === 'awaiting_first_publish') {
    parts.push(`${ws.total_files} 份文件待发布`);
  }
  if (ws.status === 'pending_changes') {
    if (ws.modified) parts.push(`${ws.modified} 份修改`);
    if (ws.added) parts.push(`${ws.added} 份新增`);
    if (ws.removed) parts.push(`${ws.removed} 份移除`);
    if (ws.renamed) parts.push(`${ws.renamed} 份改名`);
    if (ws.reordered) parts.push('顺序已调整');
  }
  if (ws.status === 'revising') {
    parts.push(`${ws.revising} 份修订进行中（暂无待发布变化）`);
  }
  if (ws.status === 'editing' && ws.session_busy) {
    parts.push(`${ws.session_busy} 份编辑中（暂不能确认）`);
  }
  if (ws.status === 'missing_draft') parts.push(`${ws.no_draft} 份缺草稿`);
  if (ws.status === 'unverifiable') {
    parts.push(`${ws.unconfirmed} 份暂不能确认`);
  }
  return parts.join(' · ');
}

function WorkStatusCell({ws}) {
  if (!ws) return '-';
  const meta = WORK_STATUS_META[ws.status];
  const detail = workStatusDetail(ws);
  return (
    <span>
      <Tag color={meta ? meta.color : 'default'}>{meta ? meta.label : ws.status}</Tag>
      {detail && (
        <div style={{fontSize: 12, color: '#999', lineHeight: '18px'}}>{detail}</div>
      )}
    </span>
  );
}

@observer
class ComTable extends React.Component {
  handleDelete = (record) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定删除手册「${record.name}」？删除后不可恢复。`,
      onOk: () => http.delete(`/api/institution/manuals/${record.id}/`)
        .then(() => {
          message.success('删除成功');
          store.fetchRecords();
        }),
    });
  };

  render() {
    return (
      <TableCard
        tKey="institution-manuals"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        actions={[
          <AuthButton
            key="create" auth="institution.manual.add" type="primary"
            icon={<PlusOutlined/>} onClick={() => store.showForm({})}>新建手册</AuthButton>,
          <AuthButton
            key="category" auth="institution.manual.config"
            onClick={store.showCategories}>类别管理</AuthButton>,
        ]}
        pagination={{
          current: store.pageNum,
          pageSize: store.pageSize,
          total: store.total,
          onChange: store.setPage,
        }}>
        <Table.Column title="手册名称" dataIndex="name"
          render={(_, record) => (
            <a onClick={() => history.push(`/institution/manuals/${record.id}`)}>{record.name}</a>
          )}/>
        <Table.Column title="编号" dataIndex="code" width={130}/>
        <Table.Column title="类别" dataIndex="category_name" width={110}
          render={v => v || '-'}/>
        <Table.Column title="归属" width={180}
          render={(_, record) => `${record.org_type_display || '-'} · ${record.org_name || '-'}`}/>
        <Table.Column title="所有者" width={110}
          render={(_, record) => record.owner_name
            ? <Tag color="purple" style={{marginRight: 0}}>{record.owner_name}</Tag>
            : <Tooltip title="尚未指定手册所有者：所有者负责账号授权与文件分工，请联系平台超级管理员指定">
                <Tag color="orange" style={{marginRight: 0}}>未指定</Tag>
              </Tooltip>}/>
        <Table.Column title="状态" dataIndex="status" width={80}
          render={v => <Tag color={STATUS_COLORS[v]}>{v === 'active' ? '启用' : '归档'}</Tag>}/>
        <Table.Column title="当前生效版本" width={150}
          render={(_, record) => record.current_version
            ? `v${record.current_version.version_no} · ${(record.current_version.published_at || '').slice(0, 10)}`
            : <Tag>未发布</Tag>}/>
        <Table.Column title="工作状态" width={180}
          render={(_, record) => <WorkStatusCell ws={record.work_status}/>}/>
        <Table.Column title="操作" width={240} fixed="right"
          render={(_, record) => {
            const roles = record.my_roles || [];
            // 草稿工作台后端要求手册编制角色，入口与后端口径一致
            const canDraft = roles.includes('edit');
            return (
              <Action>
                <Action.Button onClick={() => history.push(`/institution/manuals/${record.id}`)}>详情</Action.Button>
                {canDraft && (
                  <Action.Button onClick={() => history.push(`/institution/manuals/${record.id}/draft`)}>草稿</Action.Button>
                )}
                <Action.Button auth="institution.manual.edit" onClick={() => store.showForm(record)}>编辑</Action.Button>
                <Action.Button danger auth="institution.manual.delete"
                  disabled={!!record.current_version}
                  title={record.current_version ? '已有发布版本不可删除，请归档' : undefined}
                  onClick={() => this.handleDelete(record)}>删除</Action.Button>
              </Action>
            );
          }}/>
      </TableCard>
    );
  }
}

export default ComTable;
