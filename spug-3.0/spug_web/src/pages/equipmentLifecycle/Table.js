/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message } from 'antd';
import { AuthButton } from 'components';
import store from './store';
import { getDeviceStatusConfig } from './constants';

/**
 * 设备生命周期设备列表
 * 查看权限：equipment_lifecycle.device.view；维护权限：equipment_lifecycle.device.manage
 */
@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除设备「${record.device_name}（${record.device_sn}）」吗？存在系统关系记录（含历史）的设备无法删除。`,
      okText: '确定',
      cancelText: '取消',
      onOk: () => store.handleDelete(record.id).then(() => message.success('删除成功')),
    });
  }

  render() {
    const columns = [
      { title: '设备编号', dataIndex: 'device_sn', width: 150 },
      { title: '设备名称', dataIndex: 'device_name', width: 150 },
      { title: '设备型号', dataIndex: 'device_model', width: 120 },
      {
        title: '当前设备状况',
        dataIndex: 'current_status',
        width: 120,
        render: (status) => {
          const config = getDeviceStatusConfig(status);
          return <Tag color={config.color}>{config.text}</Tag>;
        }
      },
      { title: '当前位置', dataIndex: 'current_location', width: 180, ellipsis: true, render: (v) => v || '-' },
      { title: '安装时间', dataIndex: 'install_time', width: 110, render: (v) => v || '-' },
      { title: '启用时间', dataIndex: 'enable_time', width: 110, render: (v) => v || '-' },
      { title: '备注', dataIndex: 'remark', ellipsis: true, render: (v) => v || '-' },
      {
        title: '操作',
        width: 180,
        fixed: 'right',
        render: (text, record) => (
          <React.Fragment>
            <AuthButton auth="equipment_lifecycle.device.view" type="link"
                        onClick={() => store.showDetail(record)}>详情</AuthButton>
            <AuthButton auth="equipment_lifecycle.device.manage" type="link"
                        onClick={() => store.showForm(record)}>编辑</AuthButton>
            <AuthButton auth="equipment_lifecycle.device.manage" type="link" danger
                        onClick={() => this.handleDelete(record)}>删除</AuthButton>
          </React.Fragment>
        )
      }
    ];

    return (
      <Table
        loading={store.isFetching}
        dataSource={store.records}
        rowKey="id"
        columns={columns}
        pagination={{
          current: store.page,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (page, pageSize) => {
            store.page = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          }
        }}
        scroll={{ x: 1180 }}
      />
    );
  }
}

export default ComTable
