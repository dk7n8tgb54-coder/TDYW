import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Form, Input, Select, DatePicker, Button } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import moment from 'moment';
import store from './store';

export default observer(function () {
  const form = Form.useForm()[0];

  // 当 formVisible 改变时，更新表单的 initialValues
  useEffect(() => {
    if (store.formVisible) {
      const initialValues = { ...store.record };
      // 将字符串日期转换为 moment 对象
      if (initialValues.date) initialValues.date = moment(initialValues.date);
      if (initialValues.fault_date) initialValues.fault_date = moment(initialValues.fault_date);
      if (initialValues.fault_sent_date) initialValues.fault_sent_date = moment(initialValues.fault_sent_date);
      if (initialValues.test_return_date) initialValues.test_return_date = moment(initialValues.test_return_date);
      if (initialValues.archive_date) initialValues.archive_date = moment(initialValues.archive_date);

      form.setFieldsValue(initialValues);
    }
  }, [form]);

  function handleAddSystem() {
    let systemName;
    Modal.confirm({
      title: '添加系统',
      content: (
        <Form layout="vertical" style={{ marginTop: 24 }}>
          <Form.Item required label="系统名称">
            <Input onChange={e => systemName = e.target.value} placeholder="请输入系统名称" />
          </Form.Item>
        </Form>
      ),
      onOk: () => {
        if (systemName) {
          store.system_names.push(systemName);
          form.setFieldsValue({ system_name: systemName });
        }
      },
    });
  }

  function handleSubmit() {
    form.validateFields().then(values => {
      const data = {
        ...values,
        date: values.date.format('YYYY-MM-DD'),
        fault_date: values.fault_date.format('YYYY-MM-DD'),
        fault_sent_date: values.fault_sent_date ? values.fault_sent_date.format('YYYY-MM-DD') : null,
        test_return_date: values.test_return_date ? values.test_return_date.format('YYYY-MM-DD') : null,
        archive_date: values.archive_date ? values.archive_date.format('YYYY-MM-DD') : null
      };
      store.handleSubmit({ ...data, id: store.record.id });
    });
  }

  const statusOptions = [
    { value: '故障', label: '故障' },
    { value: '送修', label: '送修' },
    { value: '运回测试', label: '运回测试' },
    { value: '正常归档', label: '正常归档' }
  ];

  return (
    <Modal
      visible={store.formVisible}
      title={store.record.id ? '编辑故障件' : '新建故障件'}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
      width={600}
    >
      <Form form={form} labelCol={{ span: 6 }} wrapperCol={{ span: 14 }}>
        <Form.Item name="name" label="故障件名称" rules={[{ required: true, message: '请输入故障件名称' }]}>
          <Input placeholder="请输入故障件名称" />
        </Form.Item>
        <Form.Item label="所属系统" style={{ marginBottom: 0 }}>
          <Form.Item name="system_name" style={{ display: 'inline-block', width: 'calc(75%)', marginRight: 8 }} rules={[{ required: true, message: '请选择所属系统' }]}>
            <Select placeholder="请选择所属系统" showSearch>
              {store.system_names.map(name => (
                <Select.Option key={name} value={name}>{name}</Select.Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item style={{ display: 'inline-block', width: 'calc(25%-8px)' }}>
            <Button type="link" icon={<PlusOutlined />} onClick={handleAddSystem}>添加</Button>
          </Form.Item>
        </Form.Item>
        <Form.Item name="date" label="日期" rules={[{ required: true, message: '请选择日期' }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="fault_date" label="故障日期" rules={[{ required: true, message: '请选择故障日期' }]}>
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="status" label="状态" rules={[{ required: true, message: '请选择状态' }]}>
          <Select placeholder="请选择状态">
            {statusOptions.map(opt => (
              <Select.Option key={opt.value} value={opt.value}>{opt.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        <Form.Item name="fault_sent_date" label="送修日期">
          <DatePicker style={{ width: '100%' }} placeholder="状态为送修时自动记录" />
        </Form.Item>
        <Form.Item name="test_return_date" label="运回测试日期">
          <DatePicker style={{ width: '100%' }} placeholder="状态为运回测试时自动记录" />
        </Form.Item>
        <Form.Item name="archive_date" label="归档日期">
          <DatePicker style={{ width: '100%' }} placeholder="状态为正常归档时自动记录" />
        </Form.Item>
      </Form>
    </Modal>
  );
});
