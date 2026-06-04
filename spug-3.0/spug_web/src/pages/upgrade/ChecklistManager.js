/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Button, message, Table, Switch,
  Popconfirm, Space, Card, Tag, Empty
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined, MinusCircleOutlined
} from '@ant-design/icons';
import store from './store';

const { TextArea } = Input;

// 步骤编辑行
function StepEditRow({ step, index, onRemove, onChange }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: 8, gap: 8 }}>
      <span style={{ lineHeight: '32px', color: '#999', minWidth: 24 }}>{index + 1}.</span>
      <Input
        placeholder="步骤标题"
        value={step.title}
        onChange={e => onChange(index, { ...step, title: e.target.value })}
        style={{ flex: 1 }}
      />
      <TextArea
        placeholder="步骤描述（选填）"
        value={step.description}
        onChange={e => onChange(index, { ...step, description: e.target.value })}
        style={{ flex: 1, minHeight: 32 }}
        autoSize={{ minRows: 1, maxRows: 3 }}
      />
      <Switch
        checked={step.is_required}
        onChange={v => onChange(index, { ...step, is_required: v })}
        checkedChildren="必选"
        unCheckedChildren="可选"
        style={{ minWidth: 56 }}
      />
      <Button
        type="text"
        danger
        icon={<MinusCircleOutlined />}
        onClick={() => onRemove(index)}
      />
    </div>
  );
}

// 清单表单弹窗
function ChecklistFormModal({ visible, title, initialValues, onSubmit, onCancel }) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState([]);

  useEffect(() => {
    if (visible) {
      if (initialValues) {
        form.setFieldsValue({
          name: initialValues.name || '',
          description: initialValues.description || '',
          is_default: initialValues.is_default || false,
        });
        setSteps(initialValues.steps || []);
      } else {
        form.resetFields();
        setSteps([]);
      }
    }
  }, [visible, initialValues, form]);

  function handleAddStep() {
    setSteps([...steps, { title: '', description: '', is_required: true, sequence: steps.length + 1 }]);
  }

  function handleStepChange(index, updatedStep) {
    const newSteps = [...steps];
    newSteps[index] = updatedStep;
    setSteps(newSteps);
  }

  function handleStepRemove(index) {
    setSteps(steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, sequence: i + 1 })));
  }

  function handleOk() {
    form.validateFields().then(values => {
      // 新建模式必须至少有一个步骤，且所有步骤标题不能为空
      if (!initialValues) {
        const validSteps = steps.filter(s => s.title.trim());
        if (validSteps.length === 0) {
          message.warning('请至少添加一个步骤');
          return;
        }
      }
      setLoading(true);
      onSubmit({ ...values, steps: steps.filter(s => s.title.trim()) });
    });
  }

  return (
    <Modal
      title={title}
      visible={visible}
      onCancel={onCancel}
      onOk={handleOk}
      confirmLoading={loading}
      width={750}
    >
      <Form form={form} labelCol={{ span: 4 }} wrapperCol={{ span: 18 }}>
        <Form.Item name="name" label="清单名称" rules={[{ required: true, message: '请输入清单名称' }]}>
          <Input placeholder="请输入清单名称" />
        </Form.Item>
        <Form.Item name="description" label="清单描述">
          <TextArea rows={2} placeholder="清单描述（选填）" />
        </Form.Item>
        <Form.Item name="is_default" label="设为默认" valuePropName="checked">
          <Switch checkedChildren="默认" unCheckedChildren="普通" />
        </Form.Item>
      </Form>

      <div style={{ marginTop: 16, borderTop: '1px solid #f0f0f0', paddingTop: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <strong>升级步骤</strong>
          <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={handleAddStep}>
            添加步骤
          </Button>
        </div>
        {steps.length === 0 ? (
          <Empty description="暂无步骤，点击上方按钮添加" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          steps.map((step, index) => (
            <StepEditRow
              key={index}
              step={step}
              index={index}
              onRemove={handleStepRemove}
              onChange={handleStepChange}
            />
          ))
        )}
      </div>
    </Modal>
  );
}

// 步骤详情弹窗
function StepDetailModal({ visible, checklist, onCancel }) {
  if (!checklist) return null;

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 60,
      render: (text) => <span style={{ color: '#999' }}>{text}</span>,
    },
    {
      title: '步骤标题',
      dataIndex: 'title',
      key: 'title',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: text => text || '-',
    },
    {
      title: '必执行',
      dataIndex: 'is_required',
      key: 'is_required',
      width: 80,
      render: v => v ? <Tag color="blue">必选</Tag> : <Tag>可选</Tag>,
    },
  ];

  return (
    <Modal
      title={`清单详情 - ${checklist.name}`}
      visible={visible}
      onCancel={onCancel}
      footer={<Button onClick={onCancel}>关闭</Button>}
      width={700}
    >
      {checklist.description && (
        <div style={{ marginBottom: 12, color: '#666' }}>{checklist.description}</div>
      )}
      <Table
        dataSource={checklist.steps || []}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
      />
    </Modal>
  );
}

export default observer(function () {
  const [formVisible, setFormVisible] = useState(false);
  const [editingChecklist, setEditingChecklist] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailChecklist, setDetailChecklist] = useState(null);

  useEffect(() => {
    store.fetchChecklists();
  }, []);

  function handleCreate() {
    setEditingChecklist(null);
    setFormVisible(true);
  }

  function handleViewDetail(checklist) {
    store.fetchChecklistDetail(checklist.id).then(data => {
      setDetailChecklist(data);
      setDetailVisible(true);
    });
  }

  function handleEdit(checklist) {
    // 先获取详情以获取完整步骤列表
    store.fetchChecklistDetail(checklist.id).then(data => {
      setEditingChecklist(data);
      setFormVisible(true);
    });
  }

  function handleDelete(checklist) {
    store.deleteChecklist(checklist.id).then(() => {
      message.success('删除成功');
      store.fetchChecklists();
    });
  }

  function handleSubmit(values) {
    const action = editingChecklist
      ? store.updateChecklist(editingChecklist.id, values)
      : store.createChecklist(values);

    action.then(() => {
      message.success(editingChecklist ? '更新成功' : '创建成功');
      setFormVisible(false);
      setEditingChecklist(null);
      store.fetchChecklists();
    }).catch(() => {
      message.error('操作失败');
    });
  }

  const columns = [
    {
      title: '清单名称',
      dataIndex: 'name',
      key: 'name',
      render: (text, record) => (
        <a onClick={() => handleViewDetail(record)}>
          {record.is_default && <Tag color="blue" style={{ marginRight: 4 }}>默认</Tag>}
          {text}
        </a>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: text => text || '-',
    },
    {
      title: '步骤数',
      dataIndex: 'step_count',
      key: 'step_count',
      width: 80,
      render: count => <Tag color="blue">{count}</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 160,
      render: text => text || '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" onClick={() => handleViewDetail(record)}>
            详情
          </Button>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
          <Popconfirm
            title={`确定删除清单「${record.name}」？关联的步骤也将被删除。`}
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
      title="升级步骤清单管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建清单
        </Button>
      }
    >
      <div style={{ marginBottom: 12, color: '#999', fontSize: 12 }}>
        预设升级步骤清单，创建升级表单时可快速应用，自动生成步骤执行跟踪列表。
      </div>
      <Table
        dataSource={store.checklists}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
      />

      <ChecklistFormModal
        visible={formVisible}
        title={editingChecklist ? '编辑清单' : '新建清单'}
        initialValues={editingChecklist}
        onSubmit={handleSubmit}
        onCancel={() => { setFormVisible(false); setEditingChecklist(null); }}
      />

      <StepDetailModal
        visible={detailVisible}
        checklist={detailChecklist}
        onCancel={() => { setDetailVisible(false); setDetailChecklist(null); }}
      />
    </Card>
  );
})
