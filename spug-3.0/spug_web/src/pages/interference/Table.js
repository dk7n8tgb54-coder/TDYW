/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker } from 'antd';
import { PlusOutlined, ExportOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton } from "components";
import store from './store';
import * as XLSX from 'xlsx';
import moment from 'moment';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
  }

  state = {
    exportDateRange: null
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

  handleExport = () => {
    const { exportDateRange } = this.state;

    let data = store.dataSource;

    // 如果选择了日期范围，进行过滤
    if (exportDateRange && exportDateRange.length === 2) {
      const startDate = moment(exportDateRange[0]).format('YYYY-MM-DD');
      const endDate = moment(exportDateRange[1]).format('YYYY-MM-DD');
      data = data.filter(item => {
        const itemDate = moment(item.datetime).format('YYYY-MM-DD');
        return itemDate >= startDate && itemDate <= endDate;
      });
    }

    if (data.length === 0) {
      message.warning('没有可导出的数据');
      return;
    }

    try {
      // 准备导出数据，使用动态序号
      const exportData = data.map((item, index) => ({
        '序号': index + 1,
        '频率': item.frequency,
        '汇报科室': item.report_dept,
        '日期时间': item.datetime,
        '坐标': item.coordinates || '',
        '干扰类型': item.interference_type,
        '现象': item.phenomenon,
        '航班号': item.flight_number || '',
        '机型': item.aircraft_type || '',
        '是否上报': item.is_reported || '',
        '创建时间': item.created_at || ''
      }));

      // 创建工作簿和工作表
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, '干扰信息统计');

      // 生成文件名
      const now = moment().format('YYYYMMDD_HHmmss');
      const dateRangeText = exportDateRange
        ? `${moment(exportDateRange[0]).format('YYYYMMDD')}-${moment(exportDateRange[1]).format('YYYYMMDD')}`
        : 'all';
      const fileName = `干扰信息统计_${dateRangeText}_${now}.xlsx`;

      // 保存文件（让用户选择保存位置）
      XLSX.writeFile(wb, fileName);

      message.success(`成功导出 ${data.length} 条记录`);
    } catch (error) {
      console.error('导出失败:', error);
      message.error('导出失败，请重试');
    }
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
              value={this.state.exportDateRange}
              onChange={(dates) => this.setState({ exportDateRange: dates })}
              style={{ width: 280 }}
            />
          </span>,
          <AuthButton
            auth="interference.interference.view"
            icon={<ExportOutlined/>}
            onClick={this.handleExport}>导出</AuthButton>
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
