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
import { Action, TableCard, AuthButton, AttachmentCountBadge } from "components";
import store from './store';

const STATUS_TAG_MAP = {
  normal: {color: 'green', text: '正常'},
  expiring: {color: 'orange', text: '即将到期'},
  expired: {color: 'red', text: '已过期'},
};

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
  }

  handleDelete = (text) => {
    const info = `${text['station_name']}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${info}】的执照记录?`,
      onOk: () => {
        return http.delete('/api/radio-license/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  renderStatus = (computed_status, record) => {
    const tagInfo = STATUS_TAG_MAP[computed_status] || STATUS_TAG_MAP.normal;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  renderDaysLeft = (days_left, record) => {
    if (days_left < 0) {
      return <span style={{color: '#ff4d4f'}}>已过期 {Math.abs(days_left)} 天</span>;
    } else if (days_left <= 45) {
      return <span style={{color: '#fa8c16'}}>{days_left} 天</span>;
    }
    return <span>{days_left} 天</span>;
  };

  renderFrequencies = (frequencies, record) => {
    if (!frequencies || frequencies.length === 0) return '-';
    const formatFreq = (f) => {
      const base = `${f.frequency_value} ${f.frequency_unit}`;
      return f.frequency_text ? `${base}（${f.frequency_text}）` : base;
    };
    if (frequencies.length === 1) {
      return formatFreq(frequencies[0]);
    }
    return `${formatFreq(frequencies[0])} 等 ${frequencies.length} 个`;
  };

  renderAttachmentCount = (text, record) => {
    return <AttachmentCountBadge count={record.attachment_count} onClick={() => store.showDetail(record)} />;
  };

  render() {
    return (
      <TableCard
        tKey="rl"
        title="执照列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => {
            store.showDetail(record);
          },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="radio_license.license.add"
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
        <Table.Column title="台站" dataIndex="station_name" width={160}/>
        <Table.Column title="频率" dataIndex="frequencies" width={180} render={this.renderFrequencies}/>
        <Table.Column title="用途" dataIndex="purpose" ellipsis width={160}/>
        <Table.Column title="起始日期" dataIndex="valid_from" width={110}/>
        <Table.Column title="截止日期" dataIndex="valid_to" width={110}/>
        <Table.Column title="剩余天数" width={120} render={(text, record) => this.renderDaysLeft(record.days_left, record)}/>
        <Table.Column title="状态" width={100} render={(text, record) => this.renderStatus(record.computed_status, record)}/>
        <Table.Column title="责任人" dataIndex="responsible_user_name" width={100}/>
        <Table.Column title="附件" width={60} render={this.renderAttachmentCount}/>
        <Table.Column title="创建时间" dataIndex="created_at" width={160} ellipsis/>
        {hasPermission('radio_license.license.edit|radio_license.license.del') && (
          <Table.Column title="操作" width={200} render={info => (
            <Action>
              <Action.Button auth="radio_license.license.view" onClick={() => store.showDetail(info)}>查看</Action.Button>
              <Action.Button auth="radio_license.license.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
              <Action.Button auth="radio_license.attachment.upload|radio_license.attachment.download|radio_license.attachment.delete" onClick={() => store.showDetail(info)}>附件</Action.Button>
              <Action.Button danger auth="radio_license.license.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
