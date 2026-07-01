/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import {
  Modal, Form, Input, Button, message, Table, Tag,
  Popconfirm, Space, Card, Empty
} from 'antd';
import {
  PlusOutlined, EditOutlined, DeleteOutlined
} from '@ant-design/icons';
import store from '../store';
import PlanForm from './PlanForm';

// 步骤详情查看弹窗
function StepDetailModal({ visible, plan, onCancel }) {
  if (!plan) return null;

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 60,
      render: text => <span style={{ color: '#999' }}>{text}</span>,
    },
    { title: '步骤标题', dataIndex: 'title', key: 'title' },
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
      title={`方案详情 - ${plan.name}`}
      visible={visible}
      onCancel={onCancel}
      footer={<Button onClick={onCancel}>关闭</Button>}
      width={720}
    >
      {plan.description && (
        <div style={{ marginBottom: 12, color: '#666' }}>{plan.description}</div>
      )}
      {plan.system || plan.upgrade_type || plan.version ? (
        <div style={{ marginBottom: 12 }}>
          {plan.system && <Tag>{plan.system}</Tag>}
          {plan.upgrade_type && <Tag color="cyan">{plan.upgrade_type}</Tag>}
          {plan.version && <Tag color="purple">{plan.version}</Tag>}
          {plan.owner && <Tag color="geekblue">{plan.owner}</Tag>}
        </div>
      ) : null}
      <Table
        dataSource={plan.steps || []}
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
  const [editingPlan, setEditingPlan] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailPlan, setDetailPlan] = useState(null);

  useEffect(() => {
    store.fetchPlans();
    store.fetchFilterOptions();
  }, []);

  function handleCreate() {
    setEditingPlan(null);
    setFormVisible(true);
  }

  function handleViewDetail(plan) {
    store.fetchPlanDetail(plan.id).then(data => {
      if (!data) {
        message.error('获取详情失败');
        return;
      }
      setDetailPlan(data);
      setDetailVisible(true);
    });
  }

  function handleEdit(plan) {
    // 先获取详情以拿到完整步骤列表
    store.fetchPlanDetail(plan.id).then(data => {
      if (!data) {
        message.error('获取详情失败');
        return;
      }
      setEditingPlan(data);
      setFormVisible(true);
    });
  }

  function handleDelete(plan) {
    store.deletePlan(plan.id).then(() => {
      message.success('删除成功');
      store.fetchPlans();
    });
  }

  function handleSubmit(values) {
    const action = editingPlan
      ? store.updatePlan(editingPlan.id, values)
      : store.createPlan(values);

    action.then(() => {
      message.success(editingPlan ? '更新成功' : '创建成功');
      setFormVisible(false);
      setEditingPlan(null);
      store.fetchPlans();
    }).catch(() => {
      message.error('操作失败');
    });
  }

  const columns = [
    {
      title: '方案名称',
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
      title: '系统',
      dataIndex: 'system',
      key: 'system',
      width: 120,
      render: text => text || '-',
    },
    {
      title: '升级类型',
      dataIndex: 'upgrade_type',
      key: 'upgrade_type',
      width: 100,
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
            title={`确定删除方案「${record.name}」？关联的预设步骤也将被删除。`}
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
      title="升级方案管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建方案
        </Button>
      }
    >
      <div style={{ marginBottom: 12, color: '#999', fontSize: 12 }}>
        预设升级方案（含基本信息+步骤清单），创建升级表单时可一次性应用，自动填充字段并生成步骤执行跟踪列表。
      </div>
      <Table
        dataSource={store.plans}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={false}
      />

      <PlanForm
        visible={formVisible}
        title={editingPlan ? '编辑方案' : '新建方案'}
        initialValues={editingPlan}
        onSubmit={handleSubmit}
        onCancel={() => { setFormVisible(false); setEditingPlan(null); }}
      />

      <StepDetailModal
        visible={detailVisible}
        plan={detailPlan}
        onCancel={() => { setDetailVisible(false); setDetailPlan(null); }}
      />
    </Card>
  );
})
