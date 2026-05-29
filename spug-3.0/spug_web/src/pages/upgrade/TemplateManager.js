/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Select, Button, message, Table, Switch,
  Popconfirm, Space, Card, Tag
} from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import store from './store';

const { Option } = Select;
const UPGRADE_TYPES = ['功能升级', 'Bug修复', '安全补丁', '性能优化'];
const STATUSES = ['处理中', '已完成'];

function TemplateFormModal({ visible, title, initialValues, onSubmit, onCancel }) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (visible) {
      if (initialValues) {
        form.setFieldsValue({
          name: initialValues.name || '',
          system: initialValues.system || undefined,
          upgrade_type: initialValues.upgrade_type || undefined,
          version: initialValues.version || '',
          owner: initialValues.owner || '',
          status: initialValues.status || '处理中',
          detail_content: initialValues.detail_content || '',
          is_default: initialValues.is_default || false,
        });
      } else {
        form.resetFields();
      }
    }
  }, [visible, initialValues, form]);

  function handleOk() {
    form.validateFields().then(values => {
      setLoading(true);
      onSubmit(values);
    });
  }

  return (
    <Modal
      title={title}
      visible={visible}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={loading}
      width={600}
    >
      <Form form={form} labelCol={{ span: 5 }} wrapperCol={{ span: 17 }}>
        <Form.Item
          name="name"
          label="模板名称"
          rules={[{ required: true, message: '请输入模板名称' }]}
        >
          <Input placeholder="请输入模板名称" />
        </Form.Item>
        <Form.Item name="system" label="系统">
          <Select allowClear showSearch placeholder="请选择系统（可选）"
            filterOption={(input, option) =>
              option.children?.toLowerCase().indexOf(input.toLowerCase()) >= 0
            }
          >
            {store.filterOptions.systems.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="upgrade_type" label="升级类型">
          <Select allowClear placeholder="请选择升级类型（可选）">
            {UPGRADE_TYPES.map(t => (
              <Option value={t} key={t}>{t}</Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="version" label="默认版本">
          <Input placeholder="请输入默认版本（可选）" />
        </Form.Item>
        <Form.Item name="owner" label="负责人">
          <Input placeholder="请输入负责人（可选）" />
        </Form.Item>
        <Form.Item name="status" label="默认状态">
          <Select placeholder="请选择默认状态">
            {STATUSES.map(s => (
              <Option value={s} key={s}>{s}</Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="is_default" label="设为默认" valuePropName="checked">
          <Switch checkedChildren="默认" unCheckedChildren="普通" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

export default observer(function () {
  const [formVisible, setFormVisible] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState(null);

  useEffect(() => {
    store.fetchTemplates();
  }, []);

  function handleCreate() {
    setEditingTemplate(null);
    setFormVisible(true);
  }

  function handleEdit(template) {
    setEditingTemplate(template);
    setFormVisible(true);
  }

  function handleDelete(template) {
    store.deleteTemplate(template.id).then(() => {
      message.success('删除成功');
      store.fetchTemplates();
    });
  }

  function handleSubmit(values) {
    const action = editingTemplate
      ? store.updateTemplate(editingTemplate.id, values)
      : store.createTemplate(values);

    action.then(() => {
      message.success(editingTemplate ? '更新成功' : '创建成功');
      setFormVisible(false);
      setEditingTemplate(null);
      store.fetchTemplates();
    }).catch(() => {
      message.error('操作失败');
    });
  }

  const columns = [
    {
      title: '模板名称',
      dataIndex: 'name',
      key: 'name',
      render: (text, record) => (
        <span>
          {record.is_default && <Tag color="blue" style={{ marginRight: 4 }}>默认</Tag>}
          {text}
        </span>
      ),
    },
    { title: '系统', dataIndex: 'system', key: 'system', width: 120 },
    { title: '升级类型', dataIndex: 'upgrade_type', key: 'upgrade_type', width: 100 },
    { title: '默认版本', dataIndex: 'version', key: 'version', width: 100 },
    { title: '负责人', dataIndex: 'owner', key: 'owner', width: 80 },
    { title: '默认状态', dataIndex: 'status', key: 'status', width: 80 },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Popconfirm
            title={`确定删除模板「${record.name}」？`}
            onConfirm={() => handleDelete(record)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="升级模板管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建模板
        </Button>
      }
    >
      <Table
        dataSource={store.templates}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
      />

      <TemplateFormModal
        visible={formVisible}
        title={editingTemplate ? '编辑模板' : '新建模板'}
        initialValues={editingTemplate}
        onSubmit={handleSubmit}
        onCancel={() => { setFormVisible(false); setEditingTemplate(null); }}
      />
    </Card>
  );
})
