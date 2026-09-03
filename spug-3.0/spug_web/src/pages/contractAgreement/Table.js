/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, Tag, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton, AttachmentCountBadge } from 'components';
import store from './store';

const STATUS_TAG_MAP = {
  normal: {color: 'green', text: '正常'},
  expiring: {color: 'orange', text: '即将到期'},
  expired: {color: 'default', text: '已关闭'},
};

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${record.contract_name}】合同协议记录？`,
      onOk: () => {
        return http.delete('/api/contract-agreement/', {params: {id: record.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords();
          });
      }
    });
  };

  renderStatus = (text, record) => {
    const tagInfo = STATUS_TAG_MAP[record.computed_status || record.status] || STATUS_TAG_MAP.normal;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  renderDaysLeft = (text, record) => {
    if (record.days_left < 0) {
      return <span style={{color: '#8c8c8c'}}>已关闭</span>;
    }
    return <span>{record.days_left} 天</span>;
  };

  renderFee = (text, record) => {
    if (!record.has_fee) return '无';
    return record.fee_amount ? `人民币 ${record.fee_amount}` : '有';
  };

  renderAttachmentCount = (text, record) => {
    return <AttachmentCountBadge count={record.attachment_count} onClick={() => store.showDetail(record)} />;
  };

  render() {
    return (
      <TableCard
        tKey="contract_agreement"
        resizable
        title="合同协议列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => store.showDetail(record),
          style: {cursor: 'pointer'}
        })}
        actions={[
          <AuthButton
            auth="contract_agreement.agreement.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm({})}>新建</AuthButton>,
        ]}
        pagination={{
          current: store.pageNum,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100'],
          onChange: (page, pageSize) => {
            store.pageNum = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          }
        }}>
        <Table.Column title="合同名称" dataIndex="contract_name" width={190} ellipsis/>
        <Table.Column title="合同编号" dataIndex="contract_no" width={140} ellipsis/>
        <Table.Column title="类型" dataIndex="contract_type_display" width={130}/>
        <Table.Column title="起始日期" dataIndex="valid_start_date" width={110}/>
        <Table.Column title="截止日期" dataIndex="valid_end_date" width={110}/>
        <Table.Column title="剩余天数" width={120} render={this.renderDaysLeft}/>
        <Table.Column title="费用" width={130} render={this.renderFee}/>
        <Table.Column title="责任人" dataIndex="responsible_user_name" width={100} ellipsis/>
        <Table.Column title="签约方" dataIndex="signing_party" width={160} ellipsis/>
        <Table.Column title="附件" width={70} render={this.renderAttachmentCount}/>
        <Table.Column title="状态" width={80} render={this.renderStatus}/>
        <Table.Column title="创建时间" dataIndex="created_at" width={160} ellipsis/>
        {hasPermission('contract_agreement.agreement.view|contract_agreement.agreement.edit|contract_agreement.agreement.del') && (
          <Table.Column title="操作" width={150} fixed="right" render={record => (
            <Action>
              <Action.Button auth="contract_agreement.agreement.view" onClick={() => store.showDetail(record)}>查看</Action.Button>
              <Action.Button auth="contract_agreement.agreement.edit" onClick={() => store.showForm(record)}>编辑</Action.Button>
              <Action.Button danger auth="contract_agreement.agreement.del" onClick={() => this.handleDelete(record)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    );
  }
}

export default ComTable;

