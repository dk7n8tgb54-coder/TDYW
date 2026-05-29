/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 批量删除排班弹窗组件
 * 
 * 功能：
 * - 选择人员（多选）
 * - 选择日期范围
 * - 预览待删除排班
 * - 确认批量删除
 */
import React from 'react';
import { Modal, Form, Select, DatePicker, Button, Space, Table, message } from 'antd';
import moment from 'moment';
import store from '../../stores';

const { RangePicker } = DatePicker;
const { Option } = Select;

/**
 * 预览表格列定义
 */
const previewColumns = [
  {
    title: '日期',
    dataIndex: 'schedule_date',
    key: 'schedule_date',
  },
  {
    title: '人员',
    dataIndex: 'staff_name',
    key: 'staff_name',
  },
  {
    title: '班次',
    dataIndex: 'shift_name',
    key: 'shift_name',
  },
];

function BatchDeleteModal({ visible, onClose, onSuccess }) {
  const [form] = Form.useForm();
  const [previewSchedules, setPreviewSchedules] = React.useState([]);
  const [isLoading, setIsLoading] = React.useState(false);

  // 重置状态当弹窗关闭
  React.useEffect(() => {
    if (!visible) {
      form.resetFields();
      setPreviewSchedules([]);
    }
  }, [visible, form]);

  /**
   * 预览待删除的排班
   */
  const handlePreview = async () => {
    try {
      const values = await form.validateFields();
      const { staff_ids, date_range } = values;

      if (!staff_ids || staff_ids.length === 0) {
        message.warning('请选择要删除的人员');
        return;
      }

      if (!date_range || date_range.length !== 2) {
        message.warning('请选择日期范围');
        return;
      }

      const startDate = moment(date_range[0]).format('YYYY-MM-DD');
      const endDate = moment(date_range[1]).format('YYYY-MM-DD');

      setIsLoading(true);
      const staffSchedules = await store.batchQuerySchedules(
        staff_ids, 
        startDate, 
        endDate
      );
      setIsLoading(false);

      if (staffSchedules.length === 0) {
        message.warning('所选人员在指定日期范围内没有排班记录');
      }

      setPreviewSchedules(staffSchedules);
    } catch (error) {
      console.error('Failed to preview:', error);
      setIsLoading(false);
    }
  };

  /**
   * 确认批量删除
   */
  const handleConfirmDelete = async () => {
    if (previewSchedules.length === 0) {
      message.warning('没有可删除的排班记录');
      return;
    }

    try {
      setIsLoading(true);
      
      // 使用不刷新的删除方法，避免多次刷新
      for (const schedule of previewSchedules) {
        await store.deleteScheduleNoRefresh(schedule.id);
      }

      message.success(`已删除 ${previewSchedules.length} 条排班记录`);
      
      // 清理状态
      setPreviewSchedules([]);
      form.resetFields();
      
      // 通知父组件刷新
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Failed to batch delete:', error);
      message.error('删除失败，请重试');
      onSuccess(); // 刷新恢复一致状态
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      visible={visible}
      title="按人员批量删除排班"
      onCancel={onClose}
      footer={null}
      width={800}
    >
      <Form form={form} layout="vertical">
        {/* 人员选择 */}
        <Form.Item
          label="选择人员"
          name="staff_ids"
          rules={[{ required: true, message: '请选择要删除的人员' }]}
        >
          <Select
            mode="multiple"
            placeholder="请选择要删除排班的人员（可多选）"
            showSearch
            filterOption={(input, option) =>
              option.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
            }
          >
            {store.staffList.filter(s => s.is_active).map(staff => (
              <Option key={staff.id} value={staff.id} label={staff.user_name}>
                {staff.user_name}
                {staff.department && ` (${staff.department})`}
              </Option>
            ))}
          </Select>
        </Form.Item>

        {/* 日期范围 */}
        <Form.Item
          label="日期范围"
          name="date_range"
          rules={[{ required: true, message: '请选择日期范围' }]}
        >
          <RangePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
        </Form.Item>

        {/* 操作按钮 */}
        <Form.Item>
          <Space>
            <Button type="primary" onClick={handlePreview} loading={isLoading}>
              预览
            </Button>
            <Button onClick={onClose}>取消</Button>
          </Space>
        </Form.Item>
      </Form>

      {/* 预览列表 */}
      {previewSchedules.length > 0 && (
        <>
          <div style={{ marginTop: 16, marginBottom: 8 }}>
            <h4>待删除排班预览 ({previewSchedules.length}条):</h4>
          </div>
          <Table
            dataSource={previewSchedules}
            columns={previewColumns}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 5 }}
            scroll={{ y: 240 }}
          />
          <div style={{ marginTop: 16, textAlign: 'right' }}>
            <Space>
              <Button onClick={onClose}>取消</Button>
              <Button 
                type="primary" 
                danger 
                onClick={handleConfirmDelete}
                loading={isLoading}
              >
                确认删除 {previewSchedules.length} 条排班
              </Button>
            </Space>
          </div>
        </>
      )}
    </Modal>
  );
}

export default BatchDeleteModal;
