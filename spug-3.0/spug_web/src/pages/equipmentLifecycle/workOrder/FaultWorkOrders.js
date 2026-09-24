/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * "生成维修工单"按钮：默认故障维修类型、作业系统固定为故障所属系统；
 * 作业期间影响系统运行默认为"否"（拆下部件离线维修不改变系统状态），
 * 需要影响运行时由用户在表单中明确开启（前后端默认一致）。
 * 带入现象/位置/对象描述，全部可编辑。
 * 幂等：每次打开生成表单生成新的 client_token，重复提交返回已有工单。
 */
import React, { useState, useEffect } from 'react';
import { Table, Tag, Button, Empty } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http } from 'libs';
import { AuthButton } from 'components';
import WorkOrderForm from './WorkOrderForm';
import WorkOrderDetail from './WorkOrderDetail';
import store from './store';
import {
  WO_PERM, WORK_TYPE_TEXT, WO_STATUS_TEXT, WO_STATUS_COLOR, PRIORITY_TEXT,
} from './constants';

const API_PREFIX = '/api/equipment-lifecycle';

export function GenerateWorkOrderButton({fault}) {
  const [visible, setVisible] = useState(false);
  const disabled = fault.status === 'cancelled';
  if (disabled) return null;
  return (
    <span>
      <AuthButton
        auth={WO_PERM.ADD}
        type="primary"
        icon={<PlusOutlined/>}
        onClick={() => {store.showConvertFromFault(fault); setVisible(true);}}
      >
        生成维修工单
      </AuthButton>
      <FaultConvertModal visible={visible} fault={fault} onClose={() => setVisible(false)}/>
    </span>
  );
}

function FaultConvertModal({visible, fault, onClose}) {
  const [submitting, setSubmitting] = useState(false);
  // 影响运行默认"否"：部件离线维修不影响系统状态，需要时用户明确开启
  const initialValues = {
    title: `${fault.fault_no || ''} 维修工单`,
    work_type: 'repair',
    priority: 'normal',
    system: fault.system,
    affects_system_operation: false,
    work_location: fault.fault_location || '',
    work_object_desc: [fault.fault_object_name, fault.fault_object_model, fault.fault_object_sn]
      .filter(Boolean).join(' / '),
    work_requirement: fault.phenomenon || '',
  };
  return (
    <WorkOrderForm
      visible={visible}
      onClose={onClose}
      title="生成维修工单"
      initialValues={initialValues}
      onSubmit={(values) => {
        setSubmitting(true);
        return store.submitConvertFromFault(values)
          .finally(() => setSubmitting(false));
      }}
    />
  );
}

/**
 * 故障详情"关联工单"页签：该故障生成的全部工单（一个故障允许多张）。
 */
export function FaultWorkOrdersTab({fault}) {
  const [records, setRecords] = useState([]);
  const [fetching, setFetching] = useState(false);
  const [detailId, setDetailId] = useState(null);
  const [detailVisible, setDetailVisible] = useState(false);

  useEffect(() => {
    if (!fault || !fault.id) return;
    setFetching(true);
    http.get(`${API_PREFIX}/faults/${fault.id}/work-orders/`)
      .then(res => setRecords(res.data || []))
      .catch(() => {})
      .finally(() => setFetching(false));
  }, [fault && fault.id, fault && fault.updated_at]);

  const columns = [{
    title: '工单编号',
    dataIndex: 'work_no',
    width: 150,
  }, {
    title: '标题',
    dataIndex: 'title',
    ellipsis: true,
  }, {
    title: '类型',
    dataIndex: 'work_type',
    width: 90,
    render: t => WORK_TYPE_TEXT[t] || t,
  }, {
    title: '状态',
    dataIndex: 'status',
    width: 90,
    render: t => <Tag color={WO_STATUS_COLOR[t]}>{WO_STATUS_TEXT[t] || t}</Tag>,
  }, {
    title: '优先级',
    dataIndex: 'priority',
    width: 70,
    render: t => PRIORITY_TEXT[t] || t,
  }, {
    title: '负责人',
    dataIndex: 'owner_name',
    width: 90,
    render: t => t || '-',
  }, {
    title: '操作',
    width: 70,
    render: (t, record) => (
      <Button
        type="link"
        size="small"
        style={{padding: 0}}
        onClick={() => {setDetailId(record.id); setDetailVisible(true);}}
      >
        详情
      </Button>
    ),
  }];

  return (
    <div>
      <p style={{color: '#999', marginTop: 0}}>
        一个故障可根据实际需要生成多张维修工单；工单完成不会自动关闭本故障，恢复确认仍由故障流程完成。
      </p>
      <Table
        rowKey="id"
        size="small"
        loading={fetching}
        columns={columns}
        dataSource={records}
        pagination={false}
        locale={{emptyText: <Empty description="尚未生成工单" image={Empty.PRESENTED_IMAGE_SIMPLE}/>}}
      />
      {detailVisible && (
        <WorkOrderDetail
          woId={detailId}
          visible={detailVisible}
          onClose={() => setDetailVisible(false)}
        />
      )}
    </div>
  );
}
