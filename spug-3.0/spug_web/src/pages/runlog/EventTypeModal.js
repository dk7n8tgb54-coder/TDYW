/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, Button, Table, Popconfirm, message, Space, Tag } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import S from './store';

export default observer(function EventTypeModal() {
  const [form] = Form.useForm();
  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleAdd = () => {
    setEditingId(null);
    form.resetFields();
  };

  const handleEdit = (record) => {
    setEditingId(record.id);
    form.setFieldsValue(record);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);
      if (editingId) {
        await S.updateEventType(editingId, values);
        message.success('更新成功');
      } else {
        await S.addEventType(values);
        message.success('添加成功');
      }
      setEditingId(null);
      form.resetFields();
    } catch (e) {
      if (e.error) {
        message.error(e.error);
      }
      // else it's probably a validation error or user cancelled
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await S.deleteEventType(id);
      message.success('删除成功');
    } catch (e) {
      message.error(e?.error || '删除失败');
    }
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (isActive) => (
        <Tag color={isActive ? 'green' : 'red'}>
          {isActive ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '操作',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          />
          <Popconfirm
            title="确定删除该类型？"
            onConfirm={() => handleDelete(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 只有当 eventTypeModalVisible 为 true 时才渲染
  if (!S.eventTypeModalVisible) {
    return null;
  }

  return (
    <Modal
      title="事件类型管理"
      visible={S.eventTypeModalVisible}
      onCancel={S.hideEventTypeModal}
      footer={null}
      width={600}
      destroyOnClose
    >
      <div style={{ marginBottom: 16 }}>
        <Form form={form} layout="inline" onFinish={handleSubmit}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入类型名称' }]}>
            <Input placeholder="请输入类型名称" style={{ width: 120 }} />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<PlusOutlined />}
            >
              {editingId ? '更新' : '添加'}
            </Button>
          </Form.Item>
          {editingId && (
            <Form.Item>
              <Button onClick={() => { setEditingId(null); form.resetFields(); }}>
                取消
              </Button>
            </Form.Item>
          )}
        </Form>
      </div>

      <Table
        dataSource={S.eventTypes}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
        locale={{ emptyText: '暂无事件类型' }}
      />
    </Modal>
  );
});