import React from 'react';
import { Table, Tag, Modal, message, Button, DatePicker } from 'antd';
import { observer } from 'mobx-react';
import { Action, TableCard, AuthButton } from 'components';
import { PlusOutlined, ExportOutlined } from '@ant-design/icons';
import store from './store';
import * as XLSX from 'xlsx';
import moment from 'moment';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  state = {
    exportDateRange: null
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除故障件"${record.name}"吗？`,
      onOk: () => store.handleDelete(record).then(() => message.success('删除成功'))
    });
  };

  handleExport = () => {
    const { exportDateRange } = this.state;
    
    let data = store.dataSource;
    
    // 如果选择了日期范围，进行过滤
    if (exportDateRange && exportDateRange.length === 2) {
      const startDate = moment(exportDateRange[0]).format('YYYY-MM-DD');
      const endDate = moment(exportDateRange[1]).format('YYYY-MM-DD');
      data = data.filter(item => {
        const itemDate = moment(item.date).format('YYYY-MM-DD');
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
        '故障件名称': item.name,
        '所属系统': item.system_name || '',
        '日期': item.date,
        '故障日期': item.fault_date || '',
        '状态': item.status || '',
        '送修日期': item.fault_sent_date || '',
        '运回测试日期': item.test_return_date || '',
        '归档日期': item.archive_date || '',
        '创建时间': item.created_at || ''
      }));

      // 创建工作簿和工作表
      const ws = XLSX.utils.json_to_sheet(exportData);
      const wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, '故障件管理');

      // 生成文件名
      const now = moment().format('YYYYMMDD_HHmmss');
      const dateRangeText = exportDateRange 
        ? `${moment(exportDateRange[0]).format('YYYYMMDD')}-${moment(exportDateRange[1]).format('YYYYMMDD')}`
        : 'all';
      const fileName = `故障件管理_${dateRangeText}_${now}.xlsx`;

      // 保存文件（让用户选择保存位置）
      XLSX.writeFile(wb, fileName);
      
      message.success(`成功导出 ${data.length} 条记录`);
    } catch (error) {
      console.error('导出失败:', error);
      message.error('导出失败，请重试');
    }
    };

  render() {
    const statusColors = {
      '故障': 'red',
      '送修': 'orange',
      '运回测试': 'blue',
      '正常归档': 'green'
    };

    return (
      <TableCard
        tKey="fp"
        title="故障件列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        actions={[
          <AuthButton 
            key="add"
            type="primary" 
            icon={<PlusOutlined />}
            auth="fault.faultpart.add"
            onClick={() => store.showForm()}
          >
            新建
          </AuthButton>,
          <span key="date-range-picker" style={{ marginRight: 8 }}>
            <DatePicker.RangePicker
              placeholder={['开始日期', '结束日期']}
              value={this.state.exportDateRange}
              onChange={(dates) => this.setState({ exportDateRange: dates })}
              style={{ width: 280 }}
            />
          </span>,
          <Button 
            key="export"
            icon={<ExportOutlined/>}
            onClick={this.handleExport}>导出</Button>
        ]}
        pagination={{
          showSizeChanger: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}
      >
        <Table.Column title="故障件名称" dataIndex="name" />
        <Table.Column title="所属系统" dataIndex="system_name" />
        <Table.Column title="日期" dataIndex="date" />
        <Table.Column title="故障日期" dataIndex="fault_date" />
        <Table.Column title="状态" dataIndex="status" render={(status) => (
          <Tag color={statusColors[status]}>{status}</Tag>
        )} />
        <Table.Column title="送修日期" dataIndex="fault_sent_date" />
        <Table.Column title="运回测试日期" dataIndex="test_return_date" />
        <Table.Column title="归档日期" dataIndex="archive_date" />
        <Table.Column title="操作" render={(info) => (
          <Action>
            <Action.Button auth="fault.faultpart.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
            <Action.Button auth="fault.faultpart.del" danger onClick={() => this.handleDelete(info)}>删除</Action.Button>
          </Action>
        )} />
      </TableCard>
    );
  }
}

export default ComTable;
