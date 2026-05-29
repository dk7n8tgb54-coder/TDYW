/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 已有排班列表组件
 * 
 * 显示指定日期的已有排班，支持：
 * - 单条删除
 * - 批量选择
 * - 批量删除
 */
import React from 'react';
import { Space, Checkbox, Button, Popconfirm } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';

/**
 * 单个排班项组件
 */
const ScheduleItem = ({ 
  schedule, 
  checked, 
  onCheckChange, 
  onDelete 
}) => (
  <Space>
    <Checkbox
      checked={checked}
      onChange={(e) => onCheckChange(e.target.checked)}
    />
    <span style={{
      backgroundColor: schedule.shift_color || '#1890ff',
      color: '#fff',
      padding: '2px 8px',
      borderRadius: '4px',
      marginLeft: '8px'
    }}>
      {schedule.staff_name} - {schedule.shift_name}
    </span>
    <Popconfirm
      title="确定删除此排班？"
      onConfirm={onDelete}
      okText="确定"
      cancelText="取消"
    >
      <Button type="link" danger icon={<DeleteOutlined />} size="small">
        删除
      </Button>
    </Popconfirm>
  </Space>
);

/**
 * 批量操作工具栏
 */
const BatchOperations = ({ 
  selectAll, 
  onSelectAllChange, 
  checkedCount,
  onBatchDelete 
}) => (
  <Space>
    <Checkbox
      checked={selectAll}
      onChange={(e) => onSelectAllChange(e.target.checked)}
    >
      全选
    </Checkbox>
    <Popconfirm
      title={`确定要删除选中的 ${checkedCount} 条排班吗？`}
      onConfirm={onBatchDelete}
      okText="确定"
      cancelText="取消"
    >
      <Button type="primary" danger size="small">
        批量删除
      </Button>
    </Popconfirm>
  </Space>
);

/**
 * 已有排班列表主组件
 * 
 * @param {Object} props
 * @param {Array} props.schedules - 排班列表
 * @param {Array} props.checkedIds - 选中的排班ID列表
 * @param {boolean} props.selectAll - 是否全选
 * @param {Function} props.onCheckChange - 选择变化回调 (id, checked) => void
 * @param {Function} props.onSelectAllChange - 全选变化回调 (checked) => void
 * @param {Function} props.onDelete - 删除回调 (id) => void
 * @param {Function} props.onBatchDelete - 批量删除回调 () => void
 */
function ExistingSchedules({
  schedules,
  checkedIds,
  selectAll,
  onCheckChange,
  onSelectAllChange,
  onDelete,
  onBatchDelete
}) {
  if (schedules.length === 0) {
    return (
      <div style={{ marginBottom: 16 }}>
        <h4>已有排班 (0条):</h4>
        <p style={{ color: '#999' }}>暂无排班，点击日历单元格添加排班</p>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        marginBottom: 8,
        alignItems: 'center'
      }}>
        <h4 style={{ margin: 0 }}>已有排班 ({schedules.length}条):</h4>
        <BatchOperations
          selectAll={selectAll}
          onSelectAllChange={onSelectAllChange}
          checkedCount={checkedIds.length}
          onBatchDelete={onBatchDelete}
        />
      </div>
      
      <Space direction="vertical" style={{ width: '100%' }}>
        {schedules.map(schedule => (
          <ScheduleItem
            key={schedule.id}
            schedule={schedule}
            checked={checkedIds.includes(schedule.id)}
            onCheckChange={(checked) => onCheckChange(schedule.id, checked)}
            onDelete={() => onDelete(schedule.id)}
          />
        ))}
      </Space>
    </div>
  );
}

export default ExistingSchedules;
