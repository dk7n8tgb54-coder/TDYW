/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 替班列表组件 (重构后)
 * 
 * 拆分后结构:
 * - useSubstitute: 业务逻辑 Hook
 * - SubstituteForm: 表单组件
 * - useApproval: 审批逻辑 Hook (已有)
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Card, Button, Modal, Form, Space } from 'antd';
import { UserSwitchOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { hasPermission } from 'libs';
import store from './stores';
import { useApproval } from './hooks';
import { useSubstitute } from './hooks/useSubstitute';
import { StatusTag } from './components/common/ApprovalActions';
import SubstituteForm from './components/SubstituteForm';
import { DatePicker } from 'antd';

function SubstituteList() {
  const [form] = Form.useForm();
  const {
    dateSchedules,
    selectedDate,
    filterDates,
    handleFilterDateChange,
    handleSearch,
    handleReset,
    handleDateChange,
    handleAddSubstitute,
    resetForm
  } = useSubstitute(store);

  const { approve, reject, cancel, remove } = useApproval({
    apiUrl: '/api/schedule/substitute/',
    refreshData: () => {
      handleSearch();
      store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
    }
  });

  const onSubmit = async () => {
    const values = await form.validateFields();
    const success = await handleAddSubstitute(form, values);
    if (success) {
      resetForm(form);
    }
  };

  const renderActions = (_, record) => (
    <Space>
      {record.status === 'pending' && hasPermission('schedule.schedule.edit') && (
        <>
          <Button type="link" size="small" onClick={() => approve(record)}>通过</Button>
          <Button type="link" size="small" danger onClick={() => reject(record)}>拒绝</Button>
        </>
      )}
      {record.status === 'pending' && hasPermission('schedule.schedule.add') && (
        <Button type="link" size="small" onClick={() => cancel(record)}>撤销</Button>
      )}
      {hasPermission('schedule.schedule.del') && (
        <Button
          type="link"
          size="small"
          danger
          icon={<ExclamationCircleOutlined />}
          onClick={() => remove(record, { withRestore: record.status === 'approved' })}
        >
          删除
        </Button>
      )}
    </Space>
  );

  const columns = [
    { title: '原值班人', dataIndex: 'original_staff_name' },
    { title: '替班人', dataIndex: 'substitute_staff_name' },
    { title: '替班日期', dataIndex: 'schedule_date' },
    { title: '班次', dataIndex: 'shift_name' },
    { title: '替班原因', dataIndex: 'reason', ellipsis: true },
    { title: '创建日期', dataIndex: 'created_at', width: 100, render: (val) => val ? val.split(' ')[0] : '' },
    { title: '状态', dataIndex: 'status', render: (val) => <StatusTag status={val} /> },
    { title: '操作', render: renderActions }
  ];

  const onCancel = () => resetForm(form);

  return (
    <>
      <Card
        title="替班记录"
        extra={
          <Space>
            <DatePicker.RangePicker
              value={filterDates}
              onChange={handleFilterDateChange}
              format="YYYY-MM-DD"
              placeholder={['开始日期', '结束日期']}
              allowClear
            />
            <Button type="primary" onClick={handleSearch}>查询</Button>
            <Button onClick={handleReset}>重置</Button>
            {hasPermission('schedule.schedule.add') && (
              <Button icon={<UserSwitchOutlined />} onClick={() => store.showSubstituteForm()}>
                申请替班
              </Button>
            )}
          </Space>
        }
      >
        <Table
          dataSource={store.substituteList}
          rowKey="id"
          columns={columns}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>

      <Modal
        visible={store.substituteFormVisible}
        title="申请替班"
        onCancel={onCancel}
        onOk={onSubmit}
        width={600}
      >
        <SubstituteForm
          form={form}
          store={store}
          dateSchedules={dateSchedules}
          selectedDate={selectedDate}
          onDateChange={handleDateChange}
          onStaffChange={() => {}}
        />
      </Modal>
    </>
  );
}

export default observer(SubstituteList);
