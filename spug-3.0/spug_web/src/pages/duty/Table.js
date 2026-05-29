/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Modal, message, DatePicker } from 'antd';
import { PlusOutlined, FilePdfOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import { Action, TableCard, AuthButton } from "components";
import store from './store';
import moment from 'moment';

@observer
class ComTable extends React.Component {
  abortController = null;

  componentDidMount() {
    this.abortController = new AbortController();
    store.fetchRecords(this.abortController.signal)
  }

  componentWillUnmount() {
    if (this.abortController) {
      this.abortController.abort();
    }
  }

  state = {
    exportDateRange: null
  }

  handleDelete = (text) => {
    const logInfo = `${text['duty_person']} - ${text['duty_date']}`;
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${logInfo}】的值班日志?`,
      onOk: () => {
        return http.post('/api/duty/duty/', {id: text.id, action: 'delete'})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  handleExport = () => {
    const { exportDateRange } = this.state;
    const hide = message.loading('正在生成PDF...');

    const params = {};
    if (exportDateRange && exportDateRange.length === 2) {
      params.start_date = moment(exportDateRange[0]).format('YYYY-MM-DD');
      params.end_date = moment(exportDateRange[1]).format('YYYY-MM-DD');
    }

    http.post('/api/duty/duty/export/pdf/', params, {
      responseType: 'arraybuffer',
      timeout: 60000
    }).then(response => {
      const contentType = response.headers['content-type'] || response.headers['Content-Type'] || '';
      if (contentType.includes('application/json')) {
        const errorData = JSON.parse(new TextDecoder().decode(response.data));
        message.error(errorData.error || '导出PDF失败');
        return;
      }
      const blob = new Blob([response.data], { type: 'application/pdf' });
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      const dateRangeText = params.start_date
        ? `${params.start_date}-${params.end_date}`
        : '全部';
      const now = moment().format('YYYYMMDD_HHmmss');
      link.download = `值班日志_${dateRangeText}_${now}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
      message.success('PDF导出成功');
    }).catch(err => {
      console.error('PDF导出失败:', err);
      message.error('导出PDF失败，请重试');
    }).finally(() => hide());
  };

  render() {
    return (
      <TableCard
        tKey="dr"
        title="值班日志列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => {
            store.showDetail(record);
          },
          style: { cursor: 'pointer' }
        })}
        actions={[
          <AuthButton
            auth="duty.duty.add"
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
            auth="duty.duty.view"
            icon={<FilePdfOutlined/>}
            onClick={this.handleExport}>导出PDF</AuthButton>
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}>
        <Table.Column title="序号" width={60} render={(_, __, index) => index + 1}/>
        <Table.Column title="值班人员" dataIndex="duty_person" width={120}/>
        <Table.Column title="所属科室" dataIndex="department" width={120}/>
        <Table.Column title="值班日期" dataIndex="duty_date" width={120}/>
        <Table.Column title="填报人" dataIndex="reporter" width={120}/>
        <Table.Column title="创建时间" dataIndex="created_at" width={180}/>
          {hasPermission('duty.duty.edit|duty.duty.del') && (
          <Table.Column title="操作" render={info => (
            <Action>
              <Action.Button onClick={() => store.showDetail(info)}>查看</Action.Button>
              <Action.Button auth="duty.duty.edit" onClick={() => store.showForm(info, false)}>编辑</Action.Button>
              <Action.Button danger auth="duty.duty.del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
            </Action>
          )}/>
        )}
      </TableCard>
    )
  }
}

export default ComTable
