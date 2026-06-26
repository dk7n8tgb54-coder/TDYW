/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton, ExportButton } from "components";
import store from './store';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
  }

  handleDelete = (text) => {
    const recordInfo = `${text['system_name']} - ${text['fault_date']}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${recordInfo}】的故障处置记录?`,
      onOk: () => {
        return http.delete('/api/fault/faultrecord/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  render() {
    return (
      <TableCard
        tKey="efr"
        title="故障处置记录列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => {
            store.showForm(record, true);
          },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="fault.faultrecord.add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm({}, false)}>新建</AuthButton>,
          <span key="date-range-picker" style={{ marginRight: 8 }}>
            <DatePicker.RangePicker
              placeholder={['开始日期', '结束日期']}
              value={store.f_export_date_range}
              onChange={(dates) => store.f_export_date_range = dates}
              style={{ width: 280 }}
            />
          </span>,
          <ExportButton
            auth="fault.faultrecord.view"
            url="/api/fault/faultrecord/export/"
            params={store.getExportParams()}
            filename="故障处置记录.xlsx">导出</ExportButton>
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}>
        <Table.Column title="系统名称" dataIndex="system_name"/>
        <Table.Column title="设备编号" dataIndex="device_code"/>
        <Table.Column title="日期" dataIndex="fault_date"/>
        <Table.Column title="处置人员" dataIndex="handler"/>
        <Table.Column title="记录人员" dataIndex="recorder"/>
        <Table.Column title="故障评级" dataIndex="fault_level"/>
        <Table.Column ellipsis title="故障现象" dataIndex="fault_phenomenon" width={200}/>
        <Table.Column ellipsis title="处置过程" dataIndex="handling_process" width={200}/>
        {hasPermission('fault.faultrecord.edit|fault.faultrecord.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button auth="fault.faultrecord.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
              <Action.Button danger auth="fault.faultrecord.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
