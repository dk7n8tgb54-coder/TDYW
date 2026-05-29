/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker } from 'antd';
import { PlusOutlined, ExportOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton } from "components";
import store from './store';
import StatusTag from './components/StatusTag';
import * as XLSX from 'xlsx';
import moment from 'moment';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
    store.fetchFilterOptions();
  }

  state = {
    exportDateRange: null,
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

  handleExport = () => {
    const { exportDateRange } = this.state;
    let data = store.records;

    if (exportDateRange && exportDateRange.length === 2) {
      const startDate = moment(exportDateRange[0]).format('YYYY-MM-DD');
      const endDate = moment(exportDateRange[1]).format('YYYY-MM-DD');
      data = data.filter(item => {
        const itemDate = item.upgrade_time?.split(' ')[0] || '';
        return itemDate >= startDate && itemDate <= endDate;
      });
    }

    if (data.length === 0) {
      message.warning('没有可导出的数据');
      return;
    }

    try {
      const exportData = data.map(item => ({
        '升级单号': item.upgrade_no || '',
        '系统': item.system || '',
        '升级类型': item.upgrade_type || '',
        '版本': item.version || '',
        '升级时间': item.upgrade_time || '',
        '状态': item.status || '',
        '负责人': item.owner || '',
        '创建时间': item.created_at || ''
      }));

      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, '升级表单');

      const now = moment().format('YYYYMMDD_HHmmss');
      const dateRangeText = exportDateRange
        ? `${moment(exportDateRange[0]).format('YYYYMMDD')}-${moment(exportDateRange[1]).format('YYYYMMDD')}`
        : 'all';
      const fileName = `升级表单_${dateRangeText}_${now}.xlsx`;
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
        tKey="ur"
        title="升级表单列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => { store.showDetail(record); },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="upgrade.upgrade.add"
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
            auth="upgrade.upgrade.view"
            icon={<ExportOutlined/>}
            onClick={this.handleExport}>导出</AuthButton>
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
        <Table.Column title="升级单号" dataIndex="upgrade_no" width={150}/>
        <Table.Column title="系统" dataIndex="system" width={120}/>
        <Table.Column title="升级类型" dataIndex="upgrade_type" width={100}/>
        <Table.Column title="版本" dataIndex="version" width={120}/>
        <Table.Column title="升级时间" dataIndex="upgrade_time" width={180}/>
        <Table.Column title="状态" dataIndex="status" width={100} render={(text) => <StatusTag status={text}/>}/>
        <Table.Column title="负责人" dataIndex="owner" width={100}/>
        {hasPermission('upgrade.upgrade.edit|upgrade.upgrade.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button onClick={() => store.showDetail(info)}>查看</Action.Button>
              <Action.Button auth="upgrade.upgrade.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
              <Action.Button danger auth="upgrade.upgrade.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    );
  }
}

export default ComTable
