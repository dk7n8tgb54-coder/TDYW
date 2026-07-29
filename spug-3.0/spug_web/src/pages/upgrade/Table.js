/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker, Badge } from 'antd';
import { PlusOutlined, PaperClipOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton, ExportButton } from "components";
import store from './store';
import StatusTag from './components/StatusTag';
import history from 'libs/history';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchFilterOptions();
  }

  handleDelete = (text) => {
    const logInfo = `${text['upgrade_no']} - ${text['system']}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${logInfo}】的升级表单?`,
      onOk: () => {
        return http.delete(`/api/upgrade/records/${text.id}/delete/`)
          .then(() => {
            message.success('删除成功');
            store.fetchRecords();
          });
      }
    });
  };

  renderAttachmentCount = (text, record) => {
    const count = record.attachment_count || 0;
    return count > 0
      ? <Badge count={count} size="small"><PaperClipOutlined /></Badge>
      : <span>-</span>;
  };

  render() {
    return (
      <TableCard
        tKey="ur"
        title="升级表单列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => {
            history.push(`/upgrade/workbench/${record.id}`);
          },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="upgrade.upgrade.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showCreateForm()}>新建</AuthButton>,
          <span key="date-range-picker" style={{ marginRight: 8 }}>
            <DatePicker.RangePicker
              placeholder={['开始日期', '结束日期']}
              value={store.f_export_date_range}
              onChange={(dates) => store.f_export_date_range = dates}
              style={{ width: 280 }}
            />
          </span>,
          <ExportButton
            auth="upgrade.upgrade.view"
            url="/api/upgrade/records/export/"
            params={store.getExportParams()}
            filename="升级表单.xlsx">导出</ExportButton>
        ]}
        pagination={{
          current: store.page,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100'],
          onChange: (page, pageSize) => {
            store.page = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          },
        }}>
        <Table.Column title="标题" dataIndex="title" width={200}/>
        <Table.Column title="系统" dataIndex="system" width={120}/>
        <Table.Column title="升级类型" dataIndex="upgrade_type" width={100}/>
        <Table.Column title="升级时间" dataIndex="upgrade_time" width={180}/>
        <Table.Column title="状态" dataIndex="status" width={100} render={(text) => <StatusTag status={text}/>}/>
        <Table.Column title="负责人" dataIndex="owner" width={100}/>
        <Table.Column title="附件" width={60} render={this.renderAttachmentCount}/>
        {hasPermission('upgrade.upgrade.edit|upgrade.upgrade.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button onClick={() => history.push(`/upgrade/workbench/${info.id}`)}>详情/编辑</Action.Button>
              <Action.Button danger auth="upgrade.upgrade.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    );
  }
}

export default ComTable
