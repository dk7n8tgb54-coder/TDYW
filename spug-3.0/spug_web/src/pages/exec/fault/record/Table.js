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

  handleExport = () => {
    const { exportDateRange } = this.state;
    
    let data = store.dataSource;
    
    // 如果选择了日期范围，进行过滤
    if (exportDateRange && exportDateRange.length === 2) {
      const startDate = moment(exportDateRange[0]).format('YYYY-MM-DD');
      const endDate = moment(exportDateRange[1]).format('YYYY-MM-DD');
      data = data.filter(item => {
        const itemDate = moment(item.fault_date).format('YYYY-MM-DD');
        return itemDate >= startDate && itemDate <= endDate;
      });
    }

    if (data.length === 0) {
      message.warning('没有可导出的数据');
      return;
    }

    try {
      // 准备导出数据
      const exportData = data.map(item => ({
        '系统名称': item.system_name,
        '设备编号': item.device_code || '',
        '日期': item.fault_date,
        '处置人员': item.handler || '',
        '记录人员': item.recorder || '',
        '故障评级': item.fault_level || '',
        '故障现象': item.fault_phenomenon || '',
        '处置过程': item.handling_process || '',
        '创建时间': item.created_at || ''
      }));

      // 创建工作簿和工作表
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, '故障处置记录');

      // 生成文件名
      const now = moment().format('YYYYMMDD_HHmmss');
      const dateRangeText = exportDateRange 
        ? `${moment(exportDateRange[0]).format('YYYYMMDD')}-${moment(exportDateRange[1]).format('YYYYMMDD')}`
        : 'all';
      const fileName = `故障处置记录_${dateRangeText}_${now}.xlsx`;

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
              value={this.state.exportDateRange}
              onChange={(dates) => this.setState({ exportDateRange: dates })}
              style={{ width: 280 }}
            />
          </span>,
          <AuthButton
            auth="fault.faultrecord.view"
            icon={<ExportOutlined/>}
            onClick={this.handleExport}>导出</AuthButton>
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
