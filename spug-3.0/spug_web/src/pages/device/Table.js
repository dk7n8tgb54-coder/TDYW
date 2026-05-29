/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { AuthButton } from 'components';
import store from './store';
import { getDeviceStatusConfig } from './constants';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
    store.fetchFilterOptions()
  }

  handleDelete = (id) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除该设备档案吗？删除后将无法恢复。',
      okText: '确定',
      cancelText: '取消',
      onOk: () => {
        store.handleDelete(id).then(() => message.success('删除成功'));
      }
    });
  }

  render() {
    const columns = [
      { title: '设备编号', dataIndex: 'device_sn', width: 150 },
      { title: '设备名称', dataIndex: 'device_name', width: 120 },
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
      { title: '使用单位', dataIndex: 'use_unit', width: 150 },
      { title: '负责人', dataIndex: 'responsible_user_name', width: 100 },
      {
        title: '操作',
        width: 200,
        fixed: 'right',
        render: (text, record) => (
          <React.Fragment>
            <AuthButton auth="device.device_resume.view" type="link" onClick={() => store.showDetail(record)}>详情</AuthButton>
            <AuthButton auth="device.device_resume.edit" type="link" onClick={() => store.showForm(record)}>编辑</AuthButton>
            <AuthButton auth="device.device_resume.delete" type="link" danger onClick={() => this.handleDelete(record.id)}>删除</AuthButton>
          </React.Fragment>
        )
      }
    ];

    return (
      <React.Fragment>
        <div style={{ marginBottom: 16 }}>
          <AuthButton auth="device.device_resume.add" type="primary" icon={<PlusOutlined />} onClick={() => store.showForm({})}>
            新增设备履历
          </AuthButton>
        </div>
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
          scroll={{ x: 1200 }}
        />
      </React.Fragment>
    );
  }
}

export default ComTable
