/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 换班列表组件 (重构后)
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Card, Button, Modal, Form, Space } from 'antd';
import { SwapOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import { hasPermission } from 'libs';
import store from './stores';
import { useApproval } from './hooks';
import { useSwap } from './hooks/useSwap';
import { StatusTag } from './components/common/ApprovalActions';
import SwapForm from './components/SwapForm';
import { DatePicker } from 'antd';

function SwapList() {
  const [form] = Form.useForm();
  const {
    fromStaffSchedules,
    toStaffSchedules,
    fromDate,
    toDate,
    filterDates,
    handleFilterDateChange,
    handleSearch,
    handleReset,
    handleFromDateChange,
    handleToDateChange,
    handleAddSwap,
    resetForm
  } = useSwap(store);

  const { approve, reject, cancel, remove } = useApproval({
    apiUrl: '/api/schedule/swap/',
    refreshData: () => {
      handleSearch();
      store.fetchSchedule(store.currentDate.year(), store.currentDate.month() + 1);
    }
  });

  const handleCancel = (record) => {
    cancel(record, {
      withRestore: record.status === 'approved',
      extraParams: record.status === 'approved' ? { cancel_swap: true } : {}
    });
  };

  const handleDelete = (record) => {
    remove(record, { withRestore: record.status === 'approved' });
  };

  const onSubmit = async () => {
    const values = await form.validateFields();
    const success = await handleAddSwap(form, values);
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
        <Button type="link" size="small" onClick={() => handleCancel(record)}>撤销</Button>
      )}
      {hasPermission('schedule.schedule.del') && (
        <Button
          type="link"
          size="small"
          danger
          icon={<ExclamationCircleOutlined />}
          onClick={() => handleDelete(record)}
        >
          删除
        </Button>
      )}
    </Space>
  );

  const columns = [
    { title: '申请人', dataIndex: 'from_staff_name' },
    { title: '被换人', dataIndex: 'to_staff_name' },
    { title: '申请人日期', dataIndex: 'from_date', render: (val, r) => val || r.schedule_date },
    { title: '被换人日期', dataIndex: 'to_date', render: (val, r) => val || r.schedule_date },
    { title: '申请人班次', dataIndex: 'from_shift_name' },
    { title: '被换人班次', dataIndex: 'to_shift_name' },
    { title: '换班原因', dataIndex: 'reason', ellipsis: true },
    { title: '创建日期', dataIndex: 'created_at', width: 100, render: (val) => val ? val.split(' ')[0] : '' },
    { title: '状态', dataIndex: 'status', render: (val) => <StatusTag status={val} /> },
    { title: '操作', render: renderActions }
  ];

  const onCancel = () => resetForm(form);

  return (
    <>
      <Card
        title="换班记录"
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
              <Button icon={<SwapOutlined />} onClick={() => store.showSwapForm()}>申请换班</Button>
            )}
          </Space>
        }
      >
        <Table
          dataSource={store.swapList}
          rowKey="id"
          columns={columns}
          pagination={{ pageSize: 10 }}
          size="small"
        />
      </Card>

      <Modal
        visible={store.swapFormVisible}
        title="申请换班"
        onCancel={onCancel}
        onOk={onSubmit}
        width={600}
      >
        <SwapForm
          form={form}
          store={store}
          fromStaffSchedules={fromStaffSchedules}
          toStaffSchedules={toStaffSchedules}
          fromDate={fromDate}
          toDate={toDate}
          onFromDateChange={handleFromDateChange}
          onToDateChange={handleToDateChange}
          onFromStaffChange={() => {}}
          onToStaffChange={() => {}}
        />
      </Modal>
    </>
  );
}

export default observer(SwapList);
