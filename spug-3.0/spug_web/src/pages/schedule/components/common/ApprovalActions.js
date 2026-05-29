/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 审批操作组件
 * 
 * 通用的审批/拒绝/撤销/删除操作按钮组
 * 用于SwapList和SubstituteList减少重复代码
 */
import React from 'react';
import { Button, Space, Popconfirm } from 'antd';
import { 
  CheckOutlined, 
  CloseOutlined, 
  DeleteOutlined,
  UndoOutlined,
  ExclamationCircleOutlined 
} from '@ant-design/icons';

/**
 * 审批状态标签
 */
export const StatusTag = ({ status }) => {
  const statusMap = {
    pending: { color: 'warning', text: '待审批' },
    approved: { color: 'success', text: '已通过' },
    rejected: { color: 'error', text: '已拒绝' },
    cancelled: { color: 'default', text: '已撤销' },
  };
  
  const config = statusMap[status] || { color: 'default', text: status };
  
  return (
    <span style={{ 
      color: config.color === 'success' ? '#52c41a' : 
            config.color === 'error' ? '#ff4d4f' :
            config.color === 'warning' ? '#faad14' : '#999'
    }}>
      {config.text}
    </span>
  );
};

/**
 * 待审批状态的操作按钮
 */
export const PendingActions = ({ onApprove, onReject }) => (
  <Space>
    <Button 
      type="primary" 
      size="small" 
      icon={<CheckOutlined />}
      onClick={onApprove}
    >
      通过
    </Button>
    <Button 
      danger 
      size="small" 
      icon={<CloseOutlined />}
      onClick={onReject}
    >
      拒绝
    </Button>
  </Space>
);

/**
 * 已通过状态的操作按钮
 */
export const ApprovedActions = ({ onCancel, onDelete }) => (
  <Space>
    <Popconfirm
      title="确定要撤销吗？"
      onConfirm={onCancel}
      okText="确定"
      cancelText="取消"
    >
      <Button size="small" icon={<UndoOutlined />}>
        撤销
      </Button>
    </Popconfirm>
    <Popconfirm
      title="确定要删除吗？删除后将恢复原排班。"
      icon={<ExclamationCircleOutlined style={{ color: 'red' }} />}
      onConfirm={onDelete}
      okText="确定"
      cancelText="取消"
    >
      <Button danger size="small" icon={<DeleteOutlined />}>
        删除
      </Button>
    </Popconfirm>
  </Space>
);

/**
 * 其他状态的操作按钮
 */
export const DefaultActions = ({ onDelete }) => (
  <Popconfirm
    title="确定要删除此记录吗？"
    onConfirm={onDelete}
    okText="确定"
    cancelText="取消"
  >
    <Button danger size="small" icon={<DeleteOutlined />}>
      删除
    </Button>
  </Popconfirm>
);

/**
 * 根据状态渲染操作按钮
 * 
 * @param {Object} props
 * @param {string} props.status - 审批状态
 * @param {Function} props.onApprove - 审批通过回调
 * @param {Function} props.onReject - 拒绝回调
 * @param {Function} props.onCancel - 撤销回调
 * @param {Function} props.onDelete - 删除回调
 */
export const ApprovalActions = ({ 
  status, 
  onApprove, 
  onReject, 
  onCancel, 
  onDelete 
}) => {
  switch (status) {
    case 'pending':
      return <PendingActions onApprove={onApprove} onReject={onReject} />;
    case 'approved':
      return <ApprovedActions onCancel={onCancel} onDelete={onDelete} />;
    default:
      return <DefaultActions onDelete={onDelete} />;
  }
};

export default ApprovalActions;
