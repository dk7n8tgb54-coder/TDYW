/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Table, Card, Tag, Modal, Form, Input, Switch, message } from 'antd';
import { PlusOutlined, StopOutlined, PlayCircleOutlined } from '@ant-design/icons';
import { http } from 'libs';
import { AuthButton, AuthDiv } from 'components';
import store from './stores';

function StaffList() {
  const [form] = Form.useForm();

  useEffect(() => {
    store.fetchStaffList();
  }, []);

  const handleAdd = () => {
    Modal.confirm({
      title: '添加值班人员',
      content: (
        <Form form={form} layout="vertical">
          <Form.Item label="值班人员" name="user_name" rules={[{ required: true, message: '请输入值班人员姓名' }]}>
            <Input placeholder="请输入值班人员姓名" />
          </Form.Item>
          <Form.Item label="部门" name="department">
            <Input placeholder="请输入部门" />
          </Form.Item>
          <Form.Item label="联系电话" name="phone">
            <Input placeholder="请输入联系电话" />
          </Form.Item>
          <Form.Item label="是否激活" name="is_active" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      ),
      onOk: async () => {
        try {
          const values = await form.validateFields();
          const data = {
            user_name: values.user_name,
            department: values.department,
            phone: values.phone,
            is_active: values.is_active,
          };
          await http.post('/api/schedule/staff/', data);
          message.success('添加成功');
          store.fetchStaffList();
          form.resetFields();
        } catch (error) {
          console.error('Failed to add staff:', error);
        }
      }
    });
  };

  const handleToggleStatus = (record) => {
    http.patch('/api/schedule/staff/', { id: record.id, is_active: !record.is_active })
      .then(() => {
        message.success('状态更新成功');
        store.fetchStaffList();
      });
  };

  const columns = [
    { title: '用户名', dataIndex: 'user_name' },
    { title: '部门', dataIndex: 'department' },
    { title: '联系电话', dataIndex: 'phone' },
    {
      title: '状态',
      dataIndex: 'is_active',
      render: (val) => (
        <Tag color={val ? 'green' : 'red'}>{val ? '激活' : '停用'}</Tag>
      )
    },
    {
      title: '操作',
      render: (_, record) => (
        <AuthButton
          auth="schedule.staff.edit"
          danger={!record.is_active}
          type={record.is_active ? 'default' : 'primary'}
          size="small"
          icon={record.is_active ? <StopOutlined /> : <PlayCircleOutlined />}
          onClick={() => handleToggleStatus(record)}
        >
          {record.is_active ? '停用' : '激活'}
        </AuthButton>
      )
    }
  ];

  return (
    <AuthDiv auth="schedule.staff.view">
      <Card title="值班人员" extra={
        <AuthButton auth="schedule.staff.add" type="primary" icon={<PlusOutlined />} onClick={handleAdd}>添加</AuthButton>
      }>
        <Table
          dataSource={store.staffList}
          rowKey="id"
          columns={columns}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>
    </AuthDiv>
  );
}

export default observer(StaffList);
