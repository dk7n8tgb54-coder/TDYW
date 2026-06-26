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
    const logInfo = `${text['frequency']} - ${text['datetime']}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${logInfo}】的干扰记录?`,
      onOk: () => {
        return http.delete('/api/interference/', {params: {id: text.id}})
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
        tKey="ei"
        title="干扰记录列表"
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
            auth="interference.interference.add"
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
            auth="interference.interference.view"
            url="/api/interference/export/"
            params={store.getExportParams()}
            filename="干扰信息统计.xlsx">导出</ExportButton>
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
        <Table.Column
          title="序号"
          align="center"
          width={80}
          render={(text, record, index) => {
            // 动态生成序号：基于当前页码和每页大小计算
            const pagination = store.pagination || {};
            const currentPage = pagination.current || 1;
            const pageSize = pagination.pageSize || 10;
            return (currentPage - 1) * pageSize + index + 1;
          }}
        />
        <Table.Column title="频率" dataIndex="frequency"/>
        <Table.Column title="汇报科室" dataIndex="report_dept"/>
        <Table.Column title="日期时间" dataIndex="datetime"/>
        <Table.Column title="坐标" dataIndex="coordinates" ellipsis/>
        <Table.Column title="干扰类型" dataIndex="interference_type"/>
        <Table.Column title="现象" dataIndex="phenomenon" ellipsis width={200}/>
        <Table.Column title="航班号" dataIndex="flight_number"/>
        <Table.Column title="机型" dataIndex="aircraft_type"/>
        <Table.Column title="是否上报" dataIndex="is_reported"/>
          {hasPermission('interference.interference.edit|interference.interference.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button auth="interference.interference.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
              <Action.Button danger auth="interference.interference.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
